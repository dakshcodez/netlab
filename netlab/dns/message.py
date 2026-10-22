"""DNS wire format (RFC 1035): header, question, A / NS / CNAME / SOA records, name compression.

``Message.encode()`` compresses names (pointers to earlier occurrences of a name suffix);
``Message.decode()`` follows pointers with loop protection. Anything else (unknown record
types) is kept as raw bytes so messages survive a decode/encode round trip.
"""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass, field

A, NS, CNAME, SOA = 1, 2, 5, 6
TYPE_NAMES = {A: "A", NS: "NS", CNAME: "CNAME", SOA: "SOA"}
IN = 1

# Header flag bits
QR, AA, TC, RD, RA = 0x8000, 0x0400, 0x0200, 0x0100, 0x0080
RCODE_OK, RCODE_FORMERR, RCODE_SERVFAIL, RCODE_NXDOMAIN, RCODE_REFUSED = 0, 1, 2, 3, 5


class DnsError(ValueError):
    pass


def normalize(name: str) -> str:
    """Lower-case, no trailing dot; the root is the empty string."""
    return name.rstrip(".").lower()


def in_zone(name: str, zone: str) -> bool:
    """True if ``name`` is ``zone`` or a descendant of it (both normalized)."""
    return zone == "" or name == zone or name.endswith("." + zone)


@dataclass(frozen=True)
class Question:
    name: str
    qtype: int = A
    qclass: int = IN


@dataclass(frozen=True)
class Record:
    name: str
    rtype: int
    ttl: int
    data: object  # A: "1.2.3.4"; NS/CNAME: name; SOA: SoaData; other: bytes
    rclass: int = IN


@dataclass(frozen=True)
class SoaData:
    mname: str
    rname: str
    serial: int = 1
    refresh: int = 3600
    retry: int = 600
    expire: int = 86400
    minimum: int = 30  # negative-caching TTL (RFC 2308)


@dataclass
class Message:
    id: int = 0
    flags: int = 0
    questions: list[Question] = field(default_factory=list)
    answers: list[Record] = field(default_factory=list)
    authority: list[Record] = field(default_factory=list)
    additional: list[Record] = field(default_factory=list)

    @property
    def rcode(self) -> int:
        return self.flags & 0xF

    @property
    def is_response(self) -> bool:
        return bool(self.flags & QR)

    @property
    def authoritative(self) -> bool:
        return bool(self.flags & AA)

    # --- encoding ---------------------------------------------------------------------

    def encode(self) -> bytes:
        out = bytearray(struct.pack(">HHHHHH", self.id, self.flags, len(self.questions),
                                    len(self.answers), len(self.authority), len(self.additional)))
        offsets: dict[str, int] = {}
        for q in self.questions:
            _write_name(out, q.name, offsets)
            out += struct.pack(">HH", q.qtype, q.qclass)
        for section in (self.answers, self.authority, self.additional):
            for r in section:
                _write_record(out, r, offsets)
        return bytes(out)

    @staticmethod
    def decode(data: bytes) -> "Message":
        if len(data) < 12:
            raise DnsError("message shorter than header")
        id_, flags, qd, an, ns, ar = struct.unpack_from(">HHHHHH", data)
        pos = 12
        msg = Message(id=id_, flags=flags)
        try:
            for _ in range(qd):
                name, pos = _read_name(data, pos)
                qtype, qclass = struct.unpack_from(">HH", data, pos)
                pos += 4
                msg.questions.append(Question(name, qtype, qclass))
            for count, section in ((an, msg.answers), (ns, msg.authority), (ar, msg.additional)):
                for _ in range(count):
                    record, pos = _read_record(data, pos)
                    section.append(record)
        except (struct.error, IndexError) as exc:
            raise DnsError(f"truncated message: {exc}") from exc
        return msg


def make_query(name: str, qtype: int = A, id_: int = 0, recursion_desired: bool = True) -> Message:
    return Message(id=id_, flags=RD if recursion_desired else 0, questions=[Question(normalize(name), qtype)])


def make_response(query: Message, answers=(), authority=(), additional=(), rcode: int = 0,
                  authoritative: bool = False, recursion_available: bool = False) -> Message:
    flags = QR | (query.flags & RD) | rcode
    if authoritative:
        flags |= AA
    if recursion_available:
        flags |= RA
    return Message(id=query.id, flags=flags, questions=list(query.questions),
                   answers=list(answers), authority=list(authority), additional=list(additional))


# --- names ----------------------------------------------------------------------------

def _write_name(out: bytearray, name: str, offsets: dict[str, int]) -> None:
    labels = [l for l in normalize(name).split(".") if l]
    for i in range(len(labels)):
        suffix = ".".join(labels[i:])
        if suffix in offsets:
            out += struct.pack(">H", 0xC000 | offsets[suffix])
            return
        if len(out) < 0x3FFF:
            offsets[suffix] = len(out)
        label = labels[i].encode("ascii")
        if not 1 <= len(label) <= 63:
            raise DnsError(f"bad label length in {name!r}")
        out.append(len(label))
        out += label
    out.append(0)


def _read_name(data: bytes, pos: int) -> tuple[str, int]:
    labels: list[str] = []
    end = None  # position after the name in the original stream (set at first pointer)
    jumps = 0
    while True:
        if pos >= len(data):
            raise DnsError("name runs past end of message")
        length = data[pos]
        if length & 0xC0 == 0xC0:
            if pos + 1 >= len(data):
                raise DnsError("truncated compression pointer")
            if end is None:
                end = pos + 2
            pos = ((length & 0x3F) << 8) | data[pos + 1]
            jumps += 1
            if jumps > 64:
                raise DnsError("compression pointer loop")
        elif length == 0:
            return ".".join(labels).lower(), (end if end is not None else pos + 1)
        elif length & 0xC0:
            raise DnsError("unsupported label type")
        else:
            labels.append(data[pos + 1:pos + 1 + length].decode("ascii", "replace"))
            pos += 1 + length


# --- records --------------------------------------------------------------------------

def _write_record(out: bytearray, r: Record, offsets: dict[str, int]) -> None:
    _write_name(out, r.name, offsets)
    out += struct.pack(">HHI", r.rtype, r.rclass, r.ttl)
    len_pos = len(out)
    out += b"\x00\x00"  # RDLENGTH placeholder
    if r.rtype == A:
        out += socket.inet_aton(str(r.data))
    elif r.rtype in (NS, CNAME):
        _write_name(out, str(r.data), offsets)
    elif r.rtype == SOA:
        soa: SoaData = r.data  # type: ignore[assignment]
        _write_name(out, soa.mname, offsets)
        _write_name(out, soa.rname, offsets)
        out += struct.pack(">IIIII", soa.serial, soa.refresh, soa.retry, soa.expire, soa.minimum)
    else:
        out += bytes(r.data)  # type: ignore[arg-type]
    struct.pack_into(">H", out, len_pos, len(out) - len_pos - 2)


def _read_record(data: bytes, pos: int) -> tuple[Record, int]:
    name, pos = _read_name(data, pos)
    rtype, rclass, ttl, rdlen = struct.unpack_from(">HHIH", data, pos)
    pos += 10
    end = pos + rdlen
    if end > len(data):
        raise DnsError("record data runs past end of message")
    if rtype == A:
        if rdlen != 4:
            raise DnsError("bad A record length")
        value: object = socket.inet_ntoa(data[pos:end])
    elif rtype in (NS, CNAME):
        value, _ = _read_name(data, pos)
    elif rtype == SOA:
        mname, p = _read_name(data, pos)
        rname, p = _read_name(data, p)
        serial, refresh, retry, expire, minimum = struct.unpack_from(">IIIII", data, p)
        value = SoaData(mname, rname, serial, refresh, retry, expire, minimum)
    else:
        value = data[pos:end]
    return Record(name, rtype, ttl, value, rclass), end
