"""Tests for the testbed's pure logic (config generation, parsing); no Mininet needed."""

from netlab.testbed import frr, measure, netem
from netlab.topology import library


def test_netem_args():
    shape = netem.Shape(rate_mbit=10, delay_ms=50, jitter_ms=5, loss_pct=1.5, reorder_pct=25)
    cmd = netem.apply_cmd("r1-eth0", shape)
    assert cmd == ("tc qdisc replace dev r1-eth0 root netem delay 50ms 5ms distribution normal "
                   "loss 1.5% reorder 25% rate 10mbit")
    assert netem.Shape().args() == []


def test_ospf_config_costs_and_passive():
    topo = library.trap()
    conf = frr.render_config(topo, "r1", "ospf")
    assert "interface r1-eth1\n ip ospf cost 1000" in conf  # 1 Mbit/s direct link to r4
    assert "interface r1-eth2\n ip ospf cost 10" in conf  # 100 Mbit/s link to r2
    assert " passive-interface r1-eth0" in conf  # faces h1
    assert "ospf router-id 1.1.1.1" in conf
    assert conf.count("point-to-point") == 2


def test_rip_config_timers():
    topo = library.trap()
    conf = frr.render_config(topo, "r4", "rip", frr.Timers(rip_update=5, rip_timeout=30, rip_garbage=20))
    assert "timers basic 5 30 20" in conf
    assert "network 10.0.0.0/16" in conf


def test_daemon_cmd_paths(tmp_path):
    cmd = frr.daemon_cmd("ospfd", "r2", tmp_path)
    assert f"-z {tmp_path}/zserv.api" in cmd and "-N r2" in cmd
    assert "-z" not in frr.daemon_cmd("mgmtd", "r2", tmp_path)


PING = """PING 10.0.0.66 (10.0.0.66) 56(84) bytes of data.
[1000.000] 64 bytes from 10.0.0.66: icmp_seq=1 ttl=61 time=3.1 ms
[1000.010] 64 bytes from 10.0.0.66: icmp_seq=2 ttl=61 time=3.0 ms
[1000.020] 64 bytes from 10.0.0.66: icmp_seq=3 ttl=61 time=3.0 ms
[1002.530] 64 bytes from 10.0.0.66: icmp_seq=254 ttl=62 time=25.0 ms
[1002.540] 64 bytes from 10.0.0.66: icmp_seq=255 ttl=62 time=25.0 ms
"""


def test_parse_ping_outage():
    o = measure.parse_ping(PING, interval=0.01)
    assert abs(o.outage_s - 2.5) < 1e-6
    assert o.lost == 250
    assert o.received == 5
    assert o.gap_start == 1000.020


def test_expected_outage_ordering():
    rip_silent = measure.expected_outage("rip", "silent")
    ospf_silent = measure.expected_outage("ospf", "silent")
    assert ospf_silent[1] < rip_silent[0]
