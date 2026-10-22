"""Link-state routing (what OSPF does): every router knows the full graph and runs Dijkstra."""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

Graph = dict[str, dict[str, int]]


@dataclass
class SPF:
    source: str
    dist: dict[str, int]
    first_hops: dict[str, frozenset[str]]  # all neighbours on some shortest path (ECMP)
    order: list[str] = field(default_factory=list)  # order nodes were settled (for tracing)


def dijkstra(graph: Graph, source: str) -> SPF:
    dist = {source: 0}
    first_hops: dict[str, set[str]] = {source: set()}
    settled: set[str] = set()
    order = []
    heap = [(0, source)]
    while heap:
        d, u = heapq.heappop(heap)
        if u in settled:
            continue
        settled.add(u)
        order.append(u)
        for v, cost in graph[u].items():
            nd = d + cost
            via = {v} if u == source else first_hops[u]
            if v not in dist or nd < dist[v]:
                dist[v] = nd
                first_hops[v] = set(via)
                heapq.heappush(heap, (nd, v))
            elif nd == dist[v] and v not in settled:
                first_hops[v] |= via
    return SPF(source, dist, {n: frozenset(h) for n, h in first_hops.items()}, order)


def all_pairs(graph: Graph) -> dict[str, SPF]:
    return {node: dijkstra(graph, node) for node in graph}
