"""Predict the per-prefix routing tables RIP and OSPF should install, from a Topology.

These predictions are compared against FRR's real tables (``show ip route json``) in the
validation experiment.

- RIP: distance-vector simulator with hop metric. A connected network has metric 1, each
  router hop adds 1 (FRR's RIP metric as shown in zebra).
- OSPF: Dijkstra with cost = reference bw / link bw. Cost to a prefix = path cost to an
  attached router + that router's interface cost on the prefix.
"""

from __future__ import annotations

from dataclasses import dataclass

from netlab.routing.distance_vector import DistanceVector
from netlab.routing.link_state import all_pairs
from netlab.topology.model import Topology


@dataclass(frozen=True)
class Route:
    prefix: str
    metric: int
    next_hops: frozenset[str]  # next-hop IP addresses


def _node_distances(topo: Topology, protocol: str):
    """Return dist(src, dst) and first_hops(src, dst) callables over routers."""
    if protocol == "ospf":
        spf = all_pairs(topo.router_graph("ospf"))
        return (lambda s, d: spf[s].dist.get(d)), (lambda s, d: spf[s].first_hops.get(d, frozenset()))
    if protocol == "rip":
        dv = DistanceVector(topo.router_graph("hops"), split_horizon=True)
        dv.run()
        dist = lambda s, d: None if dv.cost(s, d) >= dv.infinity else dv.cost(s, d)
        return dist, dv.next_hops
    raise ValueError(f"unknown protocol {protocol!r}")


def predict(topo: Topology, router: str, protocol: str) -> dict[str, Route]:
    """Routes `router` should learn via `protocol` (connected prefixes excluded)."""
    dist, first_hops = _node_distances(topo, protocol)
    connected = {topo.subnet(i.link) for i in topo.interfaces[router]}
    routes = {}
    for link in topo.links:
        prefix = topo.subnet(link)
        if prefix in connected:
            continue
        candidates = []  # (metric, first-hop routers)
        for end in (link.a, link.b):
            if not topo.nodes[end].is_router or dist(router, end) is None:
                continue
            last_hop = 1 if protocol == "rip" else link.ospf_cost()
            candidates.append((dist(router, end) + last_hop, first_hops(router, end)))
        if not candidates:
            continue
        best = min(m for m, _ in candidates)
        hop_routers = frozenset().union(*(h for m, h in candidates if m == best))
        next_hop_ips = frozenset(
            str(topo.interface(nbr, topo.link_between(router, nbr)).ip.ip) for nbr in hop_routers
        )
        routes[str(prefix)] = Route(str(prefix), best, next_hop_ips)
    return routes


def path(topo: Topology, src_host: str, dst_host: str, protocol: str) -> list[str]:
    """Router-level path a packet takes from src_host to dst_host (deterministic tie-break)."""
    dist, first_hops = _node_distances(topo, protocol)
    (src_if,) = topo.interfaces[src_host]
    (dst_if,) = topo.interfaces[dst_host]
    node, goal = src_if.peer, dst_if.peer
    hops = [src_host, node]
    while node != goal:
        node = min(first_hops(node, goal))
        hops.append(node)
    return hops + [dst_host]
