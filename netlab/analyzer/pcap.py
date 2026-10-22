"""Read and write classic libpcap capture files (what ``tcpdump -w`` produces)."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

LINKTYPE_ETHERNET = 1
MAGICS = {  # magic → (byte order, timestamp unit in seconds)
    0xA1B2C3D4: ("<", 1e-6), 0xD4C3B2A1: (">", 1e-6),
    0xA1B23C4D: ("<", 1e-9), 0x4D3CB2A1: (">", 1e-9),
}


@dataclass(frozen=True)
class RawPacket:
    ts: float
    linktype: int
    data: bytes
    orig_len: int


def read_pcap(path: str | Path) -> Iterator[RawPacket]:
    with open(path, "rb") as f:
        header = f.read(24)
        if len(header) < 24:
            raise ValueError(f"{path}: too short to be a pcap file")
        magic = struct.unpack("<I", header[:4])[0]
        if magic == 0x0A0D0D0A:
            raise ValueError(f"{path} is pcapng; capture with `tcpdump -w` (classic pcap) or convert: "
                             "editcap -F pcap in.pcapng out.pcap")
        if magic not in MAGICS:
            raise ValueError(f"{path}: not a pcap file (magic {magic:#x})")
        order, unit = MAGICS[magic]
        linktype = struct.unpack(order + "I", header[20:24])[0]
        while True:
            rec = f.read(16)
            if len(rec) < 16:
                return
            sec, frac, caplen, origlen = struct.unpack(order + "IIII", rec)
            data = f.read(caplen)
            if len(data) < caplen:
                return  # truncated capture
            yield RawPacket(sec + frac * unit, linktype, data, origlen)


def write_pcap(path: str | Path, packets: list[tuple[float, bytes]], linktype: int = LINKTYPE_ETHERNET) -> None:
    with open(path, "wb") as f:
        f.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, linktype))
        for ts, data in sorted(packets, key=lambda p: p[0]):
            sec = int(ts)
            f.write(struct.pack("<IIII", sec, int(round((ts - sec) * 1e6)), len(data), len(data)))
            f.write(data)
