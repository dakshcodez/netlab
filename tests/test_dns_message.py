import pytest

from netlab.dns import message as m


def test_query_wire_bytes_match_known_packet():
    # A standard query for example.com A, id 0x1234, RD set (hand-built from RFC 1035 layout)
    wire = m.make_query("example.com", m.A, id_=0x1234).encode()
    assert wire == (b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
                    b"\x07example\x03com\x00\x00\x01\x00\x01")


def test_response_roundtrip_with_all_record_types():
    q = m.make_query("www.example.lab", m.A, id_=7)
    soa = m.SoaData("ns.example.lab", "admin.example.lab", serial=5, minimum=60)
    resp = m.make_response(
        q,
        answers=[m.Record("www.example.lab", m.CNAME, 300, "web.example.lab"),
                 m.Record("web.example.lab", m.A, 300, "10.1.2.3")],
        authority=[m.Record("example.lab", m.NS, 600, "ns.example.lab"),
                   m.Record("example.lab", m.SOA, 600, soa)],
        additional=[m.Record("ns.example.lab", m.A, 600, "10.9.9.9")],
        authoritative=True)
    back = m.Message.decode(resp.encode())
    assert back == resp
    assert back.authoritative and back.is_response and back.rcode == 0


def test_name_compression_shrinks_message_and_decodes():
    q = m.make_query("a.example.lab")
    resp = m.make_response(q, answers=[m.Record("a.example.lab", m.A, 1, "1.1.1.1"),
                                       m.Record("b.example.lab", m.A, 1, "2.2.2.2")])
    wire = resp.encode()
    assert b"\xc0" in wire                       # at least one pointer
    assert wire.count(b"\x07example") == 1       # the shared suffix is written once
    assert m.Message.decode(wire) == resp


def test_decode_compressed_response_from_real_server():
    # Response to "example.com A" with a pointer (0xC00C) in the answer, as real servers send
    wire = (b"\x12\x34\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00"
            b"\x07example\x03com\x00\x00\x01\x00\x01"
            b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x01\x2c\x00\x04\x5d\xb8\xd8\x22")
    msg = m.Message.decode(wire)
    assert msg.answers == [m.Record("example.com", m.A, 300, "93.184.216.34")]
    assert msg.flags & m.RA


def test_pointer_loop_and_truncation_rejected():
    loop = b"\x00\x01\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\xc0\x0c\x00\x01\x00\x01"
    with pytest.raises(m.DnsError):
        m.Message.decode(loop)
    good = m.make_query("example.lab").encode()
    with pytest.raises(m.DnsError):
        m.Message.decode(good[:-3])
    with pytest.raises(m.DnsError):
        m.Message.decode(b"\x00")


def test_unknown_record_type_survives_roundtrip():
    resp = m.Message(id=1, flags=m.QR, answers=[m.Record("x.lab", 16, 5, b"\x04text")])
    assert m.Message.decode(resp.encode()) == resp


def test_normalize_and_in_zone():
    assert m.normalize("WWW.Example.LAB.") == "www.example.lab"
    assert m.in_zone("a.b.lab", "lab") and m.in_zone("lab", "lab") and m.in_zone("x", "")
    assert not m.in_zone("notlab", "lab")
