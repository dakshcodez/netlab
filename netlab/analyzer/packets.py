"""Decode captured frames into IPv4 / TCP / UDP / ICMP / OSPF headers, and build them (for tests)."""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass

from netlab.analyzer.pcap import RawPacket

SYN, ACK, FIN, RST, PSH = 0x02, 0x10, 0x01, 0x04, 0x08


@dataclass(frozen=True)
class Packet:
    ts: float
    src: str
    dst: str
    proto: int  # 1 ICMP, 6 TCP, 17 UDP, 89 OSPF
    length: int  # IP total length
    sport: int = 0
    dport: int = 0
    seq: int = 0
    ack: int = 0
    flags: int = 0
    window: int = 0
    payload: bytes = b""

    @property
    def payload_len(self) -> int:
        return len(self.payload)


def _l3_offset(raw: RawPacket) -> int | None:
    d, lt = raw.data, raw.linktype
    if lt == 1:  # Ethernet
        if len(d) < 14:
            return None
        ethertype, off = struct.unpack_from(">H", d, 12)[0], 14
        while ethertype in (0x8100, 0x88A8) and len(d) >= off + 4:  # skip VLAN tags
            ethertype = struct.unpack_from(">H", d, off + 2)[0]
            off += 4
        return off if ethertype == 0x0800 else None
    if lt == 113:  # Linux cooked capture
        return 16 if len(d) >= 16 and struct.unpack_from(">H", d, 14)[0] == 0x0800 else None
    if lt in (101, 228, 12, 14):  # raw IP
        return 0
    return None


def decode(raw: RawPacket) -> Packet | None:
    """Return a Packet for IPv4 frames, or None for anything else (ARP, IPv6, truncated...)."""
    off = _l3_offset(raw)
    d = raw.data
    if off is None or len(d) < off + 20 or d[off] >> 4 != 4:
        return None
    ihl = (d[off] & 0x0F) * 4
    total_len = struct.unpack_from(">H", d, off + 2)[0]
    proto = d[off + 9]
    src, dst = socket.inet_ntoa(d[off + 12:off + 16]), socket.inet_ntoa(d[off + 16:off + 20])
    if struct.unpack_from(">H", d, off + 6)[0] & 0x1FFF:  # non-first fragment: no transport header
        return Packet(raw.ts, src, dst, proto, total_len)
    l4 = off + ihl
    end = min(len(d), off + total_len)
    base = dict(ts=raw.ts, src=src, dst=dst, proto=proto, length=total_len)
    if proto == 6 and end >= l4 + 20:
        sport, dport, seq, ack, offs, flags, win = struct.unpack_from(">HHIIBBH", d, l4)
        hdr = (offs >> 4) * 4
        return Packet(**base, sport=sport, dport=dport, seq=seq, ack=ack, flags=flags, window=win,
                      payload=d[l4 + hdr:end])
    if proto == 17 and end >= l4 + 8:
        sport, dport, length = struct.unpack_from(">HHH", d, l4)
        return Packet(**base, sport=sport, dport=dport, payload=d[l4 + 8:min(end, l4 + length)])
    return Packet(**base, payload=d[l4:end])


# --- builders (tests, and exporting simulator traces) ---------------------------------

def _checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\0"
    total = sum(struct.unpack(f">{len(data) // 2}H", data))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def build_ip(src: str, dst: str, proto: int, l4: bytes, ttl: int = 64, ident: int = 0) -> bytes:
    header = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(l4), ident, 0, ttl, proto, 0,
                         socket.inet_aton(src), socket.inet_aton(dst))
    header = header[:10] + struct.pack(">H", _checksum(header)) + header[12:]
    return header + l4


def ethernet(ip_packet: bytes) -> bytes:
    return b"\x02\x00\x00\x00\x00\x02" + b"\x02\x00\x00\x00\x00\x01" + b"\x08\x00" + ip_packet


def tcp_frame(src: str, dst: str, sport: int, dport: int, seq: int, ack: int, flags: int,
              payload_len: int = 0, window: int = 65535) -> bytes:
    seg = struct.pack(">HHIIBBHHH", sport, dport, seq & 0xFFFFFFFF, ack & 0xFFFFFFFF, 5 << 4, flags, window, 0, 0)
    return ethernet(build_ip(src, dst, 6, seg + bytes(payload_len)))


def udp_frame(src: str, dst: str, sport: int, dport: int, payload: bytes) -> bytes:
    seg = struct.pack(">HHHH", sport, dport, 8 + len(payload), 0) + payload
    return ethernet(build_ip(src, dst, 17, seg))


def ospf_frame(src: str, router_id: str, ospf_type: int, area: str = "0.0.0.0") -> bytes:
    body = struct.pack(">BBH4s4sHHQ", 2, ospf_type, 24, socket.inet_aton(router_id), socket.inet_aton(area), 0, 0, 0)
    return ethernet(build_ip(src, "224.0.0.5", 89, body, ttl=1))


def rip_frame(src: str, command: int, routes: list[tuple[str, int]], version: int = 2) -> bytes:
    body = struct.pack(">BBH", command, version, 0)
    for prefix, metric in routes:
        body += struct.pack(">HH4s4s4sI", 2, 0, socket.inet_aton(prefix), b"\xff\xff\xff\x00", b"\0\0\0\0", metric)
    return udp_frame(src, "224.0.0.9", 520, 520, body)
