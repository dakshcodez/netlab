import random
import zlib

from netlab.reliability import detect, inject


def test_crc32_matches_zlib():
    rng = random.Random(1)
    for n in (0, 1, 5, 64, 1000):
        data = rng.randbytes(n)
        assert detect.crc32(data) == zlib.crc32(data)
    assert detect.crc32(b"123456789") == 0xCBF43926  # standard check value


def test_crc32_incremental():
    assert detect.crc32(b"world", detect.crc32(b"hello ")) == detect.crc32(b"hello world")


def test_internet_checksum_rfc1071_example():
    data = bytes([0x00, 0x01, 0xF2, 0x03, 0xF4, 0xF5, 0xF6, 0xF7])
    # RFC 1071 section 3: the ones' complement sum is 0xDDF2, so the checksum is its complement.
    assert detect.internet_checksum(data) == 0x220D


def test_checksum_over_data_plus_checksum_is_zero():
    data = random.Random(2).randbytes(40)
    assert detect.internet_checksum(data + detect.checksum_tag(data)) == 0


def test_every_scheme_accepts_intact_and_flags_single_bit_error():
    data = random.Random(3).randbytes(32)
    for scheme in detect.SCHEMES.values():
        tag = scheme.tag(data)
        assert scheme.verify(data, tag)
        for bit in (0, 7, 100, 255):
            assert not scheme.verify(inject.flip_bits(data, [bit]), tag), scheme.name


def test_parity_misses_two_bit_errors_but_2d_parity_does_not_miss_these():
    data = bytes(16)
    tag = detect.parity_tag(data)
    assert detect.parity_verify(inject.flip_bits(data, [0, 9]), tag)
    tag2 = detect.parity2d_tag(data)
    assert not detect.parity2d_verify(inject.flip_bits(data, [0, 9]), tag2)


def test_2d_parity_misses_rectangle_pattern():
    data = bytes(16)
    tag = detect.parity2d_tag(data)
    # four flips at the corners of a rectangle keep every row and column parity even
    assert detect.parity2d_verify(inject.flip_bits(data, [0, 3, 8, 11]), tag)


def test_checksum_blind_to_swapped_words_but_crc_is_not():
    data = bytes(range(32))
    swapped = inject.swap_words(data, 1, 5)
    assert swapped != data
    assert detect.checksum_verify(swapped, detect.checksum_tag(data))
    assert not detect.crc32_verify(swapped, detect.crc32_tag(data))
    shifted = inject.add_and_subtract(data, 2, 7)
    assert detect.checksum_verify(shifted, detect.checksum_tag(data))
    assert not detect.crc32_verify(shifted, detect.crc32_tag(data))


def test_crc32_detects_every_burst_up_to_32_bits():
    rng = random.Random(4)
    data = rng.randbytes(64)
    tag = detect.crc32_tag(data)
    for length in range(1, 33):
        for _ in range(50):
            assert not detect.crc32_verify(inject.burst_error(data, length, rng), tag)


def test_hamming74_roundtrip_and_single_error_correction():
    for nibble in range(16):
        word = detect.hamming74_encode(nibble)
        assert detect.hamming74_decode(word) == (nibble, 0)
        for pos in range(1, 8):
            corrupted = word ^ (1 << (7 - pos))
            assert detect.hamming74_decode(corrupted) == (nibble, pos)


def test_hamming74_double_error_is_miscorrected():
    word = detect.hamming74_encode(0b1010)
    nibble, pos = detect.hamming74_decode(word ^ 0b1100000)
    assert pos != 0 and nibble != 0b1010
