"""Error injection for detection experiments: random bit errors, bursts and adversarial edits."""

from __future__ import annotations

import random


def flip_bits(data: bytes, positions: list[int] | set[int]) -> bytes:
    """Flip the given bit positions (0 = MSB of the first byte)."""
    out = bytearray(data)
    for p in positions:
        out[p // 8] ^= 0x80 >> (p % 8)
    return bytes(out)


def random_bit_errors(data: bytes, ber: float, rng: random.Random) -> bytes:
    """Flip each bit independently with probability ``ber`` (binary symmetric channel)."""
    nbits = len(data) * 8
    positions = [i for i in range(nbits) if rng.random() < ber]
    return flip_bits(data, positions)


def exactly_k_errors(data: bytes, k: int, rng: random.Random) -> bytes:
    return flip_bits(data, rng.sample(range(len(data) * 8), k))


def burst_error(data: bytes, length: int, rng: random.Random, start: int | None = None) -> bytes:
    """A burst of ``length`` bits: first and last bit of the window are flipped, the bits in
    between are flipped with probability 1/2 (the standard definition of a burst)."""
    nbits = len(data) * 8
    if not 1 <= length <= nbits:
        raise ValueError("burst length out of range")
    if start is None:
        start = rng.randrange(nbits - length + 1)
    positions = {start, start + length - 1}
    positions |= {start + i for i in range(1, length - 1) if rng.random() < 0.5}
    return flip_bits(data, positions)


def swap_words(data: bytes, i: int, j: int) -> bytes:
    """Swap 16-bit words i and j. The Internet checksum is a sum, so it cannot see this."""
    out = bytearray(data)
    a, b = slice(2 * i, 2 * i + 2), slice(2 * j, 2 * j + 2)
    out[a], out[b] = data[b], data[a]
    return bytes(out)


def add_and_subtract(data: bytes, i: int, j: int, delta: int = 1) -> bytes:
    """Add ``delta`` to 16-bit word i and subtract it from word j (mod 2^16): the ones'
    complement sum is unchanged, so the checksum still verifies."""
    out = bytearray(data)
    wi = (int.from_bytes(out[2 * i:2 * i + 2], "big") + delta) & 0xFFFF
    wj = (int.from_bytes(out[2 * j:2 * j + 2], "big") - delta) & 0xFFFF
    out[2 * i:2 * i + 2] = wi.to_bytes(2, "big")
    out[2 * j:2 * j + 2] = wj.to_bytes(2, "big")
    return bytes(out)
