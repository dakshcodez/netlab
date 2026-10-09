import ipaddress

import pytest

from netlab.addressing import vlsm
from netlab.routing.distance_vector import DistanceVector
from netlab.routing.link_state import dijkstra
from netlab.routing.tables import path, predict
from netlab.topology import library


# --- VLSM -------------------------------------------------------------------------------

def test_prefix_for():
    assert vlsm.prefix_for(2) == 30
    assert vlsm.prefix_for(1) == 30
    assert vlsm.prefix_for(30) == 27
    assert vlsm.prefix_for(62) == 26
    assert vlsm.prefix_for(63) == 25
    assert vlsm.prefix_for(254) == 24


def test_vlsm_plan_is_aligned_and_disjoint():
    reqs = [("Eng", 100), ("Sales", 50), ("Branch", 30), ("Admin", 20),
            ("HQ-BR", 2), ("HQ-Core", 2), ("Core-BR", 2)]
    allocs = vlsm.plan("172.16.0.0/23", reqs)
    assert [a.name for a in allocs[:2]] == ["Eng", "Sales"]
    assert str(allocs[0].network) == "172.16.0.0/25"
    assert str(allocs[1].network) == "172.16.0.128/26"
    nets = [a.network for a in allocs]
    for i, a in enumerate(nets):
        for b in nets[i + 1:]:
            assert not a.overlaps(b)
    for a in allocs:
        assert a.usable >= a.hosts_needed


def test_vlsm_out_of_space():
    with pytest.raises(ValueError):
        vlsm.plan("192.168.1.0/26", [("big", 100)])


# --- Topology ---------------------------------------------------------------------------

def test_trap_addressing():
    topo = library.trap()
    gw = topo.gateway("h1")
    (h1_if,) = topo.interfaces["h1"]
    assert gw == topo.interface("r1", h1_if.link).ip.ip
    assert gw == h1_if.ip.network.network_address + 1  # router takes first usable
    assert [i.name for i in topo.interfaces["r1"]] == ["r1-eth0", "r1-eth1", "r1-eth2"]
    all_ips = [i.ip.ip for ifs in topo.interfaces.values() for i in ifs]
    assert len(all_ips) == len(set(all_ips))


# --- Link state -------------------------------------------------------------------------

def test_dijkstra_ecmp():
    graph = {"A": {"B": 1, "C": 1}, "B": {"A": 1, "D": 1}, "C": {"A": 1, "D": 1}, "D": {"B": 1, "C": 1}}
    spf = dijkstra(graph, "A")
    assert spf.dist["D"] == 2
    assert spf.first_hops["D"] == {"B", "C"}
    assert spf.order[0] == "A"


# --- Distance vector --------------------------------------------------------------------

def _fail_and_run(name, **opts):
    case = library.COUNT_TO_INFINITY[name]
    dv = DistanceVector(case["graph"], **opts)
    dv.run()
    dv.set_link(*case["fail"], None)
    rounds = dv.run()
    return dv, case["dest"], rounds


def test_dv_matches_dijkstra_when_converged():
    topo = library.mesh()
    graph = topo.router_graph("ospf")
    dv = DistanceVector(graph, infinity=10_000)
    dv.run()
    for src in graph:
        spf = dijkstra(graph, src)
        for dst in graph:
            assert dv.cost(src, dst) == spf.dist[dst]


def test_count_to_infinity_line():
    plain, dest, plain_rounds = _fail_and_run("line")
    assert plain.cost("A", dest) == 16
    _, _, sh_rounds = _fail_and_run("line", split_horizon=True)
    assert sh_rounds < plain_rounds
    assert plain_rounds >= 10  # counts up from 2 to 16


def test_split_horizon_cannot_fix_triangle():
    dv, dest, rounds = _fail_and_run("triangle", split_horizon=True)
    assert dv.cost("A", dest) == 16
    assert rounds >= 10


# --- Route prediction -------------------------------------------------------------------

def test_trap_paths():
    topo = library.trap()
    assert path(topo, "h1", "h2", "rip") == ["h1", "r1", "r4", "h2"]
    assert path(topo, "h1", "h2", "ospf") == ["h1", "r1", "r2", "r3", "r4", "h2"]


def test_trap_predicted_metrics():
    topo = library.trap()
    h2_lan = str(topo.interfaces["h2"][0].ip.network)
    rip = predict(topo, "r1", "rip")[h2_lan]
    ospf = predict(topo, "r1", "ospf")[h2_lan]
    assert rip.metric == 2  # r4's connected LAN (1) + one hop
    assert ospf.metric == 10 + 10 + 10 + 10  # three 100M hops + r4's LAN interface
    r4_via_r1_r4 = str(topo.interface("r4", topo.link_between("r1", "r4")).ip.ip)
    r2_via_r1_r2 = str(topo.interface("r2", topo.link_between("r1", "r2")).ip.ip)
    assert rip.next_hops == {r4_via_r1_r4}
    assert ospf.next_hops == {r2_via_r1_r2}
    assert all(ipaddress.ip_address(ip) for ip in rip.next_hops)


def test_rip_tie_reports_both_next_hops():
    topo = library.trap()
    h2_lan = str(topo.interfaces["h2"][0].ip.network)
    # r2 reaches r4 in two hops via r1 or via r3
    assert len(predict(topo, "r2", "rip")[h2_lan].next_hops) == 2
