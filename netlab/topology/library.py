"""Named topologies used by the Phase 1 experiments."""

from __future__ import annotations

from netlab.topology.model import Link, Node, Topology


def trap() -> Topology:
    """Slow direct path vs fast 3-hop path between h1 and h2.

        h1 ── r1 ───────── 1 Mbit/s ───────── r4 ── h2
               │                               │
               r2 ───── 100 Mbit/s ───── r3 ───┘

    RIP (hop count) takes r1→r4 directly: 1 router hop, 1 Mbit/s.
    OSPF (cost = 1000/bw) takes r1→r2→r3→r4: cost 30 vs 1000, 100 Mbit/s.
    """
    nodes = {
        "h1": Node("h1", "host", (0, 1)),
        "r1": Node("r1", "router", (1, 1)),
        "r2": Node("r2", "router", (1.7, 0)),
        "r3": Node("r3", "router", (3.3, 0)),
        "r4": Node("r4", "router", (4, 1)),
        "h2": Node("h2", "host", (5, 1)),
    }
    links = [
        Link("h1", "r1", bw_mbps=100, hosts=50),
        Link("r1", "r4", bw_mbps=1, delay_ms=1),
        Link("r1", "r2", bw_mbps=100),
        Link("r2", "r3", bw_mbps=100),
        Link("r3", "r4", bw_mbps=100),
        Link("r4", "h2", bw_mbps=100, hosts=50),
    ]
    return Topology("trap", nodes, links, description=trap.__doc__ or "")


def mesh() -> Topology:
    """Six routers with mixed link speeds; used to validate simulator vs FRR tables.

            r1 ──100── r2 ──10─── r3
            │ ╲         │          │
           10  1000    100        100
            │     ╲     │          │
            r4 ──100── r5 ──1000── r6
    """
    nodes = {
        "h1": Node("h1", "host", (-1, 1)),
        "r1": Node("r1", "router", (0, 1)),
        "r2": Node("r2", "router", (1, 1)),
        "r3": Node("r3", "router", (2, 1)),
        "r4": Node("r4", "router", (0, 0)),
        "r5": Node("r5", "router", (1, 0)),
        "r6": Node("r6", "router", (2, 0)),
        "h2": Node("h2", "host", (3, 0)),
    }
    links = [
        Link("h1", "r1", hosts=50),
        Link("r1", "r2", bw_mbps=100),
        Link("r2", "r3", bw_mbps=10),
        Link("r1", "r4", bw_mbps=10),
        Link("r1", "r5", bw_mbps=1000),
        Link("r2", "r5", bw_mbps=100),
        Link("r3", "r6", bw_mbps=100),
        Link("r4", "r5", bw_mbps=100),
        Link("r5", "r6", bw_mbps=1000),
        Link("r6", "h2", hosts=50),
    ]
    return Topology("mesh", nodes, links, description=mesh.__doc__ or "")


TOPOLOGIES = {"trap": trap, "mesh": mesh}


def get(name: str) -> Topology:
    try:
        return TOPOLOGIES[name]()
    except KeyError:
        raise SystemExit(f"unknown topology {name!r}; choose from {', '.join(TOPOLOGIES)}")


# Small abstract graphs for the distance-vector count-to-infinity demos (simulation only).
COUNT_TO_INFINITY = {
    # A ── B ── C ; the B–C link fails. Classic two-node loop between A and B.
    "line": {
        "graph": {"A": {"B": 1}, "B": {"A": 1, "C": 1}, "C": {"B": 1}},
        "fail": ("B", "C"),
        "dest": "C",
    },
    # Triangle A, B, C with D hanging off C; the C–D link fails. Split horizon alone
    # cannot stop this three-node loop.
    "triangle": {
        "graph": {
            "A": {"B": 1, "C": 1},
            "B": {"A": 1, "C": 1},
            "C": {"A": 1, "B": 1, "D": 1},
            "D": {"C": 1},
        },
        "fail": ("C", "D"),
        "dest": "D",
    },
}
