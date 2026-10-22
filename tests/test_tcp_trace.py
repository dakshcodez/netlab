from netlab.tcp.trace import parse_ss, parse_timed_log

SS = """ESTAB 0 3640 10.0.0.2:46534 10.0.0.14:5201
\t cubic wscale:7,7 rto:244 rtt:43.9/1.8 mss:1448 pmtu:1500 rcvmss:536 advmss:1448 cwnd:44 ssthresh:31 bytes_sent:812344 bytes_retrans:14480 bytes_acked:790000 segs_out:561 delivery_rate 9.6Mbps retrans:0/10
"""


def test_parse_ss_fields():
    (s,) = parse_ss(SS)
    assert s["cc"] == "cubic" and s["cwnd"] == 44 and s["ssthresh"] == 31
    assert s["rtt_ms"] == 43.9 and s["retrans_total"] == 10 and s["bytes_acked"] == 790000


def test_parse_ss_without_ssthresh_and_empty():
    line = "ESTAB 0 0 a b\n\t reno cwnd:10 rtt:20/5\n"
    assert "ssthresh" not in parse_ss(line)[0]
    assert parse_ss("") == []


def test_timed_log_relative_times():
    log = "100.0\n" + SS + "100.1\n" + SS.replace("cwnd:44", "cwnd:50")
    samples = parse_timed_log(log)
    assert [s["t"] for s in samples] == [0.0, 0.1]
    assert [s["cwnd"] for s in samples] == [44, 50]
