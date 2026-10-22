import pytest

from netlab.analyzer import packets as pk
from netlab.analyzer.analyze import analyze_file
from netlab.analyzer.pcap import read_pcap, write_pcap
from netlab.dns import message as dns

C, S = "10.0.0.2", "10.0.0.14"


def tcp(ts, frm, seq, ack, flags, n=0, win=1000, sport=40000, dport=5201):
    if frm == "c":
        return ts, pk.tcp_frame(C, S, sport, dport, seq, ack, flags, n, win)
    return ts, pk.tcp_frame(S, C, dport, sport, seq, ack, flags, n, win)


def test_pcap_roundtrip(tmp_path):
    path = tmp_path / "x.pcap"
    frames = [(1.5, tcp(0, "c", 1, 0, pk.SYN)[1]), (1.250001, tcp(0, "s", 5, 2, pk.SYN | pk.ACK)[1])]
    write_pcap(path, frames)
    got = list(read_pcap(path))
    assert [round(g.ts, 6) for g in got] == [1.250001, 1.5]
    assert pk.decode(got[1]).flags == pk.SYN


def test_rejects_pcapng_and_garbage(tmp_path):
    ng = tmp_path / "x.pcapng"
    ng.write_bytes(b"\x0a\x0d\x0d\x0a" + bytes(40))
    with pytest.raises(ValueError, match="pcapng"):
        list(read_pcap(ng))
    bad = tmp_path / "bad.pcap"
    bad.write_bytes(bytes(30))
    with pytest.raises(ValueError):
        list(read_pcap(bad))


def test_tcp_handshake_rtt_retransmission_dupacks_throughput(tmp_path):
    # Vantage point: the client. RTT is 40 ms.
    t = [
        tcp(0.000, "c", 1000, 0, pk.SYN),
        tcp(0.040, "s", 9000, 1001, pk.SYN | pk.ACK),
        tcp(0.040, "c", 1001, 9001, pk.ACK),
        tcp(0.041, "c", 1001, 9001, pk.ACK, 1000),   # bytes 1..1000
        tcp(0.042, "c", 2001, 9001, pk.ACK, 1000),   # lost on the way
        tcp(0.043, "c", 3001, 9001, pk.ACK, 1000),
        tcp(0.081, "s", 9001, 2001, pk.ACK),         # ACK for the first segment: RTT 40 ms
        tcp(0.083, "s", 9001, 2001, pk.ACK),         # dup ACK (hole at 2001)
        tcp(0.084, "s", 9001, 2001, pk.ACK),         # dup ACK
        tcp(0.140, "c", 2001, 9001, pk.ACK, 1000),   # retransmission
        tcp(0.180, "s", 9001, 4001, pk.ACK),
        tcp(0.200, "c", 4001, 9001, pk.FIN | pk.ACK),
    ]
    path = tmp_path / "t.pcap"
    write_pcap(path, [(ts + 100, f) for ts, f in t])
    (flow,) = analyze_file(path)["tcp"]
    assert flow["syn_to_synack_ms"] == pytest.approx(40, abs=0.01)
    assert flow["synack_to_ack_ms"] == pytest.approx(0, abs=0.01)
    up = flow["a_to_b"]
    assert up["payload_bytes"] == 3000 and up["data_packets"] == 4 and up["retransmissions"] == 1
    assert up["retransmitted_bytes"] == 1000
    assert flow["b_to_a"]["dup_acks"] == 2
    assert flow["rtt_ms"]["min"] == pytest.approx(40, abs=0.01)  # retransmitted segment gives no sample
    assert flow["rtt_ms"]["samples"] == 2 and flow["closed"]
    # rate over the sender's whole active span (SYN at 0.000 to FIN at 0.200)
    assert up["throughput_mbps"] == pytest.approx(3000 * 8 / 0.200 / 1e6, rel=0.01)


def test_dns_latency_matching_and_unanswered(tmp_path):
    q1 = dns.make_query("www.example.lab", dns.A, 0x1111)
    r1 = dns.make_response(q1, answers=[dns.Record("www.example.lab", dns.A, 60, "10.20.0.10")])
    q2 = dns.make_query("lost.example.lab", dns.A, 0x2222)
    frames = [
        (0.0, pk.udp_frame(C, S, 5555, 53, q1.encode())),
        (0.0215, pk.udp_frame(S, C, 53, 5555, r1.encode())),
        (1.0, pk.udp_frame(C, S, 5556, 53, q2.encode())),
    ]
    path = tmp_path / "d.pcap"
    write_pcap(path, frames)
    d = analyze_file(path)["dns"]
    assert d["queries_answered"] == 1 and d["queries_unanswered"] == 1
    assert d["lookups"][0]["name"] == "www.example.lab" and d["lookups"][0]["latency_ms"] == pytest.approx(21.5, abs=0.01)


def test_rip_and_ospf_packets(tmp_path):
    frames = [
        (0.0, pk.rip_frame("10.0.0.1", 2, [("10.1.0.0", 1), ("10.2.0.0", 2)])),
        (1.0, pk.rip_frame("10.0.0.5", 1, [])),
        (2.0, pk.ospf_frame("10.0.0.1", "1.1.1.1", 1)),
        (3.0, pk.ospf_frame("10.0.0.5", "2.2.2.2", 4)),
    ]
    path = tmp_path / "r.pcap"
    write_pcap(path, frames)
    rep = analyze_file(path)
    assert rep["rip"]["packets"] == {"Response": 1, "Request": 1} and rep["rip"]["routes_advertised"] == 2
    assert rep["ospf"]["packets"] == {"Hello": 1, "LS Update": 1}
    assert rep["ospf"]["router_ids"] == ["1.1.1.1", "2.2.2.2"]
    assert rep["protocols"]["OSPF"] == 2


def test_non_ip_frames_are_skipped(tmp_path):
    arp = b"\xff" * 6 + b"\x02\x00\x00\x00\x00\x01" + b"\x08\x06" + bytes(28)
    path = tmp_path / "a.pcap"
    write_pcap(path, [(0.0, arp)])
    assert analyze_file(path)["packets"] == 0
