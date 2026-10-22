"""One topology description that drives the routing simulator, Mininet and FRR configs.

Addresses are assigned with the VLSM planner: router-router links get /30s, host-facing
links get a LAN sized by `Link.hosts`. On a host-facing link the router always takes the
first usable address (it is the hosts' default gateway).
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from functools import cached_property

from netlab.addressing import vlsm

OSPF_REFERENCE_MBPS = 1000.0


@dataclass(frozen=True)
class Node:
    name: str
    kind: str = "router"  # "router" | "host"
    pos: tuple[float, float] = (0.0, 0.0)  # for drawing only

    @property
    def is_router(self) -> bool:
        return self.kind == "router"


@dataclass(frozen=True)
class Link:
    a: str
    b: str
    bw_mbps: float = 100.0
    delay_ms: float = 1.0
    hosts: int = 2  # addresses needed on this segment (VLSM input)

    @property
    def name(self) -> str:
        return f"{self.a}-{self.b}"

    def other(self, node: str) -> str:
        return self.b if node == self.a else self.a

    def ospf_cost(self, reference_mbps: float = OSPF_REFERENCE_MBPS) -> int:
        """OSPF interface cost = reference bandwidth / link bandwidth (min 1)."""
        return max(1, round(reference_mbps / self.bw_mbps))


@dataclass(frozen=True)
class Interface:
    node: str
    name: str  # e.g. "r1-eth0" (matches the Mininet interface name)
    ip: ipaddress.IPv4Interface
    link: Link
    peer: str
    peer_ip: ipaddress.IPv4Address


@dataclass
class Topology:
    name: str
    nodes: dict[str, Node]
    links: list[Link]
    base: str = "10.0.0.0/16"
    description: str = ""
    _subnets: dict[str, vlsm.Allocation] = field(init=False, repr=False, default_factory=dict)

    def __post_init__(self) -> None:
        for link in self.links:
            for end in (link.a, link.b):
                if end not in self.nodes:
                    raise ValueError(f"link {link.name}: unknown node {end!r}")
        allocations = vlsm.plan(self.base, [(l.name, l.hosts) for l in self.links])
        self._subnets = {a.name: a for a in allocations}

    @property
    def routers(self) -> list[str]:
        return [n for n, node in self.nodes.items() if node.is_router]

    @property
    def hosts(self) -> list[str]:
        return [n for n, node in self.nodes.items() if not node.is_router]

    def subnet(self, link: Link) -> ipaddress.IPv4Network:
        return self._subnets[link.name].network

    def link_between(self, a: str, b: str) -> Link:
        for link in self.links:
            if {link.a, link.b} == {a, b}:
                return link
        raise KeyError(f"no link between {a} and {b}")

    def _address_order(self, link: Link) -> tuple[str, str]:
        """(first-usable owner, second-usable owner): routers before hosts."""
        if not self.nodes[link.a].is_router and self.nodes[link.b].is_router:
            return link.b, link.a
        return link.a, link.b

    @cached_property
    def interfaces(self) -> dict[str, list[Interface]]:
        """Interfaces per node, named <node>-eth<i> in link declaration order."""
        result: dict[str, list[Interface]] = {n: [] for n in self.nodes}
        for link in self.links:
            alloc = self._subnets[link.name]
            first, second = self._address_order(link)
            ips = {first: alloc.host(1), second: alloc.host(2)}
            for node in (link.a, link.b):
                peer = link.other(node)
                result[node].append(Interface(
                    node=node,
                    name=f"{node}-eth{len(result[node])}",
                    ip=ipaddress.IPv4Interface(f"{ips[node]}/{alloc.network.prefixlen}"),
                    link=link,
                    peer=peer,
                    peer_ip=ips[peer],
                ))
        return result

    def interface(self, node: str, link: Link) -> Interface:
        return next(i for i in self.interfaces[node] if i.link == link)

    def gateway(self, host: str) -> ipaddress.IPv4Address:
        (intf,) = self.interfaces[host]
        return intf.peer_ip

    def ip(self, node: str) -> ipaddress.IPv4Address:
        """Primary address of a node (its first interface)."""
        return self.interfaces[node][0].ip.ip

    def router_graph(self, metric: str = "ospf") -> dict[str, dict[str, int]]:
        """Adjacency map between routers only. metric: "hops" (RIP) or "ospf" (cost)."""
        graph: dict[str, dict[str, int]] = {r: {} for r in self.routers}
        for link in self.links:
            if self.nodes[link.a].is_router and self.nodes[link.b].is_router:
                cost = 1 if metric == "hops" else link.ospf_cost()
                graph[link.a][link.b] = cost
                graph[link.b][link.a] = cost
        return graph
