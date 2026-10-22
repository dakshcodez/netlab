"""A recursive, caching DNS resolver that walks the hierarchy iteratively.

Behaviour that the experiments depend on:

- positive caching by TTL (answers, delegations and glue) and negative caching (RFC 2308) using
  the SOA ``minimum`` of NXDOMAIN / NODATA answers;
- queries go out over a ``Transport``: ``UdpTransport`` for real sockets, or an in-memory network
  for the poisoning simulation. The transport owns the *source port* policy; the resolver owns the
  *transaction ID* policy. Two weak settings (sequential IDs, one fixed source port) and the
  hardened one (random ID, random source port) are the point of the security demo;
- a response is accepted only if its ID and question match and the transport says it came from
  the server we asked.
"""

from __future__ import annotations

import secrets
import select
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from netlab.dns import message as m
from netlab.dns.message import Message, Record, normalize

MAX_STEPS = 24
MAX_CNAME = 8


class SequentialTxid:
    """Predictable transaction IDs (what old resolvers did): 1, 2, 3, ..."""

    def __init__(self, start: int = 1) -> None:
        self.value = start - 1

    def __call__(self) -> int:
        self.value = (self.value + 1) & 0xFFFF
        return self.value


def random_txid() -> int:
    return secrets.randbelow(65536)


class Transport(Protocol):
    def exchange(self, server: str, wire: bytes, accept: Callable[[bytes], bool], timeout: float) -> bytes | None: ...


class UdpTransport:
    """Real UDP. ``fixed_source_port=None`` → a fresh OS-chosen ephemeral port for every query."""

    def __init__(self, port: int = 53, timeout: float = 1.0, fixed_source_port: int | None = None,
                 bind_ip: str = "0.0.0.0") -> None:
        self.port = port
        self.timeout = timeout
        self.fixed_source_port = fixed_source_port
        self.bind_ip = bind_ip
        self._fixed: socket.socket | None = None
        self._lock = threading.Lock()

    def exchange(self, server: str, wire: bytes, accept: Callable[[bytes], bool], timeout: float | None = None) -> bytes | None:
        timeout = self.timeout if timeout is None else timeout
        if self.fixed_source_port is not None:
            with self._lock:
                if self._fixed is None:
                    self._fixed = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    self._fixed.bind((self.bind_ip, self.fixed_source_port))
                return self._exchange(self._fixed, server, wire, accept, timeout)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind((self.bind_ip, 0))
            return self._exchange(sock, server, wire, accept, timeout)

    def _exchange(self, sock, server, wire, accept, timeout):
        sock.sendto(wire, (server, self.port))
        deadline = time.monotonic() + timeout
        while (left := deadline - time.monotonic()) > 0:
            if not select.select([sock], [], [], left)[0]:
                break
            data, addr = sock.recvfrom(4096)
            if addr == (server, self.port) and accept(data):
                return data
        return None


# --- cache ----------------------------------------------------------------------------

class Cache:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._pos: dict[tuple[str, int], tuple[float, list[Record]]] = {}
        self._neg: dict[tuple[str, int], tuple[float, int]] = {}
        self.hits = self.misses = 0

    def put(self, name: str, rtype: int, records: list[Record]) -> None:
        if records:
            ttl = min(r.ttl for r in records)
            if ttl > 0:
                self._pos[(name, rtype)] = (self.clock() + ttl, records)

    def get(self, name: str, rtype: int) -> list[Record] | None:
        entry = self._pos.get((name, rtype))
        if entry is None:
            return None
        expires, records = entry
        left = expires - self.clock()
        if left <= 0:
            del self._pos[(name, rtype)]
            return None
        return [Record(r.name, r.rtype, max(1, int(left)), r.data, r.rclass) for r in records]

    def put_negative(self, name: str, rtype: int, rcode: int, ttl: int) -> None:
        if ttl > 0:
            self._neg[(name, rtype)] = (self.clock() + ttl, rcode)

    def get_negative(self, name: str, rtype: int) -> int | None:
        entry = self._neg.get((name, rtype))
        if entry is None:
            return None
        if entry[0] <= self.clock():
            del self._neg[(name, rtype)]
            return None
        return entry[1]

    def clear(self) -> None:
        self._pos.clear()
        self._neg.clear()


# --- resolver -------------------------------------------------------------------------

@dataclass
class Resolution:
    rcode: int
    answers: list[Record] = field(default_factory=list)
    upstream: list[tuple[str, str, float]] = field(default_factory=list)  # (server, qname, seconds)
    cached: bool = False  # answered without sending any upstream query

    def addresses(self) -> list[str]:
        return [str(r.data) for r in self.answers if r.rtype == m.A]


class Resolver:
    def __init__(self, root_hints: list[str], transport: Transport, txid: Callable[[], int] = random_txid,
                 clock: Callable[[], float] = time.monotonic, timeout: float = 1.0, retries: int = 1) -> None:
        self.root_hints = list(root_hints)
        self.transport = transport
        self.txid = txid
        self.cache = Cache(clock)
        self.timeout = timeout
        self.retries = retries
        self.lock = threading.RLock()

    # public ---------------------------------------------------------------------------

    def resolve(self, name: str, qtype: int = m.A) -> Resolution:
        with self.lock:
            res = Resolution(m.RCODE_OK)
            res.answers, res.rcode = self._resolve(normalize(name), qtype, res, 0)
            res.cached = not res.upstream
            if res.cached:
                self.cache.hits += 1
            else:
                self.cache.misses += 1
            return res

    # internals ------------------------------------------------------------------------

    def _resolve(self, name: str, qtype: int, res: Resolution, depth: int) -> tuple[list[Record], int]:
        chain: list[Record] = []
        for _ in range(MAX_CNAME):
            neg = self.cache.get_negative(name, qtype)
            if neg is not None:
                return chain, neg
            hit = self.cache.get(name, qtype)
            if hit:
                return chain + hit, m.RCODE_OK
            alias = self.cache.get(name, m.CNAME) if qtype != m.CNAME else None
            if alias:
                chain += alias
                name = str(alias[0].data)
                continue
            answers, rcode = self._iterate(name, qtype, res, depth)
            if rcode != m.RCODE_OK or not answers:
                return chain, rcode
            wanted = [r for r in answers if r.name == name and r.rtype == qtype]
            if wanted:
                return chain + answers, m.RCODE_OK
            cname = [r for r in answers if r.name == name and r.rtype == m.CNAME]
            if not cname:
                return chain, m.RCODE_SERVFAIL
            chain += answers
            name = str(cname[0].data)
            if any(r.name == name and r.rtype == qtype for r in answers):
                return chain, m.RCODE_OK
        return chain, m.RCODE_SERVFAIL

    def _closest_servers(self, name: str, depth: int, res: Resolution) -> tuple[str, list[str]]:
        labels = name.split(".") if name else []
        for i in range(len(labels) + 1):
            zone = ".".join(labels[i:])
            ns = self.cache.get(zone, m.NS)
            if not ns:
                continue
            addrs = []
            for record in ns:
                glue = self.cache.get(str(record.data), m.A)
                if glue:
                    addrs += [str(g.data) for g in glue]
            if addrs:
                return zone, addrs
        return "", list(self.root_hints)

    def _iterate(self, name: str, qtype: int, res: Resolution, depth: int) -> tuple[list[Record], int]:
        zone, servers = self._closest_servers(name, depth, res)
        for _ in range(MAX_STEPS):
            response = self._ask(servers, name, qtype, res)
            if response is None:
                return [], m.RCODE_SERVFAIL
            if response.rcode == m.RCODE_NXDOMAIN:
                self._cache_negative(name, qtype, response, m.RCODE_NXDOMAIN)
                return [], m.RCODE_NXDOMAIN
            if response.rcode != m.RCODE_OK:
                return [], m.RCODE_SERVFAIL
            if response.answers:
                self._cache_answers(response.answers)
                return response.answers, m.RCODE_OK
            ns = [r for r in response.authority if r.rtype == m.NS]
            if ns and not response.authoritative:
                owner = ns[0].name
                if not (m.in_zone(owner, zone) and m.in_zone(name, owner)):
                    return [], m.RCODE_SERVFAIL  # out-of-bailiwick referral
                self.cache.put(owner, m.NS, ns)
                glue = [r for r in response.additional if r.rtype == m.A and m.in_zone(r.name, zone)]
                by_name: dict[str, list[Record]] = {}
                for g in glue:
                    by_name.setdefault(g.name, []).append(g)
                for host, records in by_name.items():
                    self.cache.put(host, m.A, records)
                servers = [str(g.data) for g in glue if g.name in {str(r.data) for r in ns}]
                if not servers:  # no glue: resolve the name server's own address first
                    for r in ns:
                        sub, _ = self._resolve_ns(str(r.data), res)
                        servers += [str(a.data) for a in sub if a.rtype == m.A]
                if not servers:
                    return [], m.RCODE_SERVFAIL
                zone = owner
                continue
            self._cache_negative(name, qtype, response, m.RCODE_OK)  # NODATA
            return [], m.RCODE_OK
        return [], m.RCODE_SERVFAIL

    def _resolve_ns(self, host: str, res: Resolution) -> tuple[list[Record], int]:
        return self._resolve(host, m.A, res, 1)

    def _ask(self, servers: list[str], name: str, qtype: int, res: Resolution) -> Message | None:
        for server in servers:
            for _ in range(1 + self.retries):
                txid = self.txid() & 0xFFFF
                wire = m.make_query(name, qtype, txid, recursion_desired=False).encode()
                sent = time.monotonic()

                def accept(data: bytes, txid=txid, name=name, qtype=qtype) -> bool:
                    try:
                        msg = Message.decode(data)
                    except m.DnsError:
                        return False
                    return (msg.is_response and msg.id == txid and len(msg.questions) == 1
                            and msg.questions[0].name == name and msg.questions[0].qtype == qtype)

                data = self.transport.exchange(server, wire, accept, self.timeout)
                res.upstream.append((server, name, time.monotonic() - sent))
                if data is not None:
                    return Message.decode(data)
        return None

    def _cache_answers(self, answers: list[Record]) -> None:
        groups: dict[tuple[str, int], list[Record]] = {}
        for r in answers:
            groups.setdefault((r.name, r.rtype), []).append(r)
        for (name, rtype), records in groups.items():
            self.cache.put(name, rtype, records)

    def _cache_negative(self, name: str, qtype: int, response: Message, rcode: int) -> None:
        for r in response.authority:
            if r.rtype == m.SOA:
                soa: m.SoaData = r.data  # type: ignore[assignment]
                self.cache.put_negative(name, qtype, rcode, min(r.ttl, soa.minimum))
                return
