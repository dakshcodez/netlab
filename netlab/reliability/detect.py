"""Error-detection and error-correction codes, implemented from scratch.

Every detection scheme is a ``Scheme``: ``tag(data)`` computes the check bytes sent along with
the message and ``verify(data, tag)`` says whether a received (data, tag) pair looks intact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


# --- parity ---------------------------------------------------------------------------

def parity_bit(data: bytes) -> int:
    """Even parity over all bits: 1 if the number of set bits is odd."""
    ones = sum(bin(b).count("1") for b in data)
    return ones & 1


def parity_tag(data: bytes) -> bytes:
    return bytes([parity_bit(data)])


def parity_verify(data: bytes, tag: bytes) -> bool:
    return len(tag) == 1 and parity_tag(data) == tag


def parity2d_tag(data: bytes) -> bytes:
    """Two-dimensional parity: one parity bit per byte (row) plus one parity byte over the
    columns (XOR of all bytes). Row bits are packed MSB-first and followed by the column byte."""
    column = 0
    rows = bytearray((len(data) + 7) // 8)
    for i, b in enumerate(data):
        column ^= b
        if parity_bit(bytes([b])):
            rows[i // 8] |= 0x80 >> (i % 8)
    return bytes(rows) + bytes([column])


def parity2d_verify(data: bytes, tag: bytes) -> bool:
    return parity2d_tag(data) == tag


# --- Internet checksum (RFC 1071) -----------------------------------------------------

def internet_checksum(data: bytes) -> int:
    """16-bit ones' complement of the ones' complement sum of 16-bit big-endian words."""
    if len(data) % 2:
        data += b"\x00"
    total = 0
    for i in range(0, len(data), 2):
        total += (data[i] << 8) | data[i + 1]
        total = (total & 0xFFFF) + (total >> 16)  # end-around carry
    return ~total & 0xFFFF


def checksum_tag(data: bytes) -> bytes:
    return internet_checksum(data).to_bytes(2, "big")


def checksum_verify(data: bytes, tag: bytes) -> bool:
    return len(tag) == 2 and internet_checksum(data) == int.from_bytes(tag, "big")


# --- CRC-32 (IEEE 802.3), table driven ------------------------------------------------

_POLY = 0xEDB88320  # reflected form of 0x04C11DB7


def _make_table() -> tuple[int, ...]:
    table = []
    for n in range(256):
        c = n
        for _ in range(8):
            c = (c >> 1) ^ _POLY if c & 1 else c >> 1
        table.append(c)
    return tuple(table)


CRC_TABLE = _make_table()


def crc32(data: bytes, crc: int = 0) -> int:
    """CRC-32 of ``data``; pass a previous result as ``crc`` to continue over more data."""
    c = crc ^ 0xFFFFFFFF
    for b in data:
        c = CRC_TABLE[(c ^ b) & 0xFF] ^ (c >> 8)
    return c ^ 0xFFFFFFFF


def crc32_tag(data: bytes) -> bytes:
    return crc32(data).to_bytes(4, "big")


def crc32_verify(data: bytes, tag: bytes) -> bool:
    return len(tag) == 4 and crc32(data) == int.from_bytes(tag, "big")


# --- scheme registry ------------------------------------------------------------------

@dataclass(frozen=True)
class Scheme:
    name: str
    tag: Callable[[bytes], bytes]
    verify: Callable[[bytes, bytes], bool]


SCHEMES: dict[str, Scheme] = {
    "parity": Scheme("parity", parity_tag, parity_verify),
    "2d-parity": Scheme("2d-parity", parity2d_tag, parity2d_verify),
    "checksum": Scheme("checksum", checksum_tag, checksum_verify),
    "crc32": Scheme("crc32", crc32_tag, crc32_verify),
}


# --- Hamming(7,4) ---------------------------------------------------------------------
# Codeword layout (positions 1..7): p1 p2 d1 p3 d2 d3 d4. Parity bit p_k sits at position 2^(k-1)
# and covers every position whose index has bit k set, so the syndrome is the position of a
# single flipped bit.

def hamming74_encode(nibble: int) -> int:
    """Encode 4 data bits into a 7-bit codeword (returned as an int, position 1 = MSB)."""
    if not 0 <= nibble < 16:
        raise ValueError("nibble must be 0..15")
    d1, d2, d3, d4 = (nibble >> 3) & 1, (nibble >> 2) & 1, (nibble >> 1) & 1, nibble & 1
    p1 = d1 ^ d2 ^ d4
    p2 = d1 ^ d3 ^ d4
    p3 = d2 ^ d3 ^ d4
    bits = [p1, p2, d1, p3, d2, d3, d4]
    word = 0
    for bit in bits:
        word = (word << 1) | bit
    return word


def hamming74_decode(word: int) -> tuple[int, int]:
    """Decode a 7-bit codeword. Returns (nibble, error_position); position 0 means no error was
    seen, 1..7 is the bit that was flipped back. Two or more errors are miscorrected silently."""
    bits = [(word >> (6 - i)) & 1 for i in range(7)]  # bits[i] is position i+1
    s1 = bits[0] ^ bits[2] ^ bits[4] ^ bits[6]
    s2 = bits[1] ^ bits[2] ^ bits[5] ^ bits[6]
    s3 = bits[3] ^ bits[4] ^ bits[5] ^ bits[6]
    pos = s1 | (s2 << 1) | (s3 << 2)
    if pos:
        bits[pos - 1] ^= 1
    nibble = (bits[2] << 3) | (bits[4] << 2) | (bits[5] << 1) | bits[6]
    return nibble, pos
