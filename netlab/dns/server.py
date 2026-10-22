"""UDP front ends: authoritative servers and the recursive resolver, plus a command line.

    python3 -m netlab.dns.server auth --zone example --ip 10.0.0.2 --port 53 ...
    python3 -m netlab.dns.server resolver --root 10.0.0.1 --bind 10.0.0.9 ...

``delay_ms`` adds a fixed latency before every reply; on one machine it stands in for the
network distance between hosts, on the testbed it stays 0 (netem provides the delay).
"""

from __future__ import annotations

import argparse
import select
import socket
import threading
import time
from typing import Callable

from netlab.dns import message as m


class UdpServer(threading.Thread):
    """Runs ``handle(Message) -> Message`` on every datagram."""

    def __init__(self, handle: Callable[[m.Message], m.Message], ip: str = "127.0.0.1", port: int = 53,
                 delay_ms: float = 0.0, name: str = "dns") -> None:
        super().__init__(daemon=True, name=name)
        self.handle = handle
        self.delay = delay_ms / 1000
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((ip, port))
        self.address = self.sock.getsockname()
        self._stop_flag = threading.Event()

    def run(self) -> None:
        while not self._stop_flag.is_set():
            if not select.select([self.sock], [], [], 0.1)[0]:
                continue
            try:
                data, addr = self.sock.recvfrom(4096)
            except OSError:
                break
            threading.Thread(target=self._serve, args=(data, addr), daemon=True).start()

    def _serve(self, data: bytes, addr) -> None:
        try:
            query = m.Message.decode(data)
        except m.DnsError:
            return
        reply = self.handle(query).encode()
        if self.delay:
            time.sleep(self.delay)
        try:
            self.sock.sendto(reply, addr)
        except OSError:
            pass

    def stop(self) -> None:
        self._stop_flag.set()
        self.join(timeout=1)
        self.sock.close()


def recursive_handler(resolver) -> Callable[[m.Message], m.Message]:
    def handle(query: m.Message) -> m.Message:
        if len(query.questions) != 1:
            return m.make_response(query, rcode=m.RCODE_FORMERR, recursion_available=True)
        q = query.questions[0]
        res = resolver.resolve(q.name, q.qtype)
        return m.make_response(query, answers=res.answers, rcode=res.rcode, recursion_available=True)
    return handle


def main() -> None:
    from netlab.dns.hierarchy import Addresses, build_servers
    from netlab.dns.resolver import Resolver, UdpTransport, SequentialTxid, random_txid

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="role", required=True)
    auth = sub.add_parser("auth", help="root, TLD or example.lab server")
    auth.add_argument("--zone", choices=["root", "tld", "example"], required=True)
    for p in (auth,):
        p.add_argument("--root-ip", required=True)
        p.add_argument("--tld-ip", required=True)
        p.add_argument("--example-ip", required=True)
    res = sub.add_parser("resolver")
    res.add_argument("--root", required=True)
    res.add_argument("--weak", action="store_true", help="sequential IDs + fixed source port (vulnerable)")
    res.add_argument("--upstream-port", type=int, default=53)
    for p in (auth, res):
        p.add_argument("--bind", default="127.0.0.1", help="address to listen on (pass the host's own IP on the testbed)")
        p.add_argument("--port", type=int, default=53)
        p.add_argument("--delay-ms", type=float, default=0.0)
    args = parser.parse_args()

    if args.role == "auth":
        servers = build_servers(Addresses(args.root_ip, args.tld_ip, args.example_ip))
        handler = servers[args.zone].handle
    else:
        transport = UdpTransport(port=args.upstream_port, fixed_source_port=44444 if args.weak else None)
        resolver = Resolver([args.root], transport, txid=SequentialTxid() if args.weak else random_txid)
        handler = recursive_handler(resolver)
    server = UdpServer(handler, args.bind, args.port, args.delay_ms)
    print(f"{args.role} listening on {server.address}", flush=True)
    server.start()
    server.join()


if __name__ == "__main__":
    main()
