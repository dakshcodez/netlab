"""Variable Length Subnet Masking (VLSM) planner.

Allocates the largest subnets first so every block stays aligned to its own size, which is
the standard manual VLSM procedure. Used to produce the Packet Tracer addressing plan and to
address the Mininet testbed.

CLI::

    python -m netlab.addressing.vlsm 172.16.0.0/23 Eng=100 Sales=50 Admin=20 HQ-BR=2
"""

from __future__ import annotations

import argparse
import ipaddress
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Allocation:
    name: str
    hosts_needed: int
    network: ipaddress.IPv4Network

    @property
    def usable(self) -> int:
        return self.network.num_addresses - 2

    @property
    def first(self) -> ipaddress.IPv4Address:
        return self.network.network_address + 1

    @property
    def last(self) -> ipaddress.IPv4Address:
        return self.network.broadcast_address - 1

    @property
    def mask(self) -> ipaddress.IPv4Address:
        return self.network.netmask

    def host(self, n: int) -> ipaddress.IPv4Address:
        """The n-th usable address (1-based)."""
        if not 1 <= n <= self.usable:
            raise ValueError(f"{self.name}: host {n} out of range 1..{self.usable}")
        return self.network.network_address + n


def prefix_for(hosts: int) -> int:
    """Smallest prefix length whose subnet holds `hosts` usable addresses (min /30)."""
    needed = max(hosts, 2) + 2  # + network and broadcast addresses
    return 32 - math.ceil(math.log2(needed))


def plan(base: str, requirements: list[tuple[str, int]]) -> list[Allocation]:
    """Allocate subnets from `base`, largest first. Returns allocations in that order."""
    base_net = ipaddress.IPv4Network(base)
    ordered = sorted(requirements, key=lambda r: r[1], reverse=True)  # stable for ties
    cursor = int(base_net.network_address)
    allocations = []
    for name, hosts in ordered:
        prefix = prefix_for(hosts)
        size = 2 ** (32 - prefix)
        cursor = -(-cursor // size) * size  # align up (no-op when sorted, kept for safety)
        net = ipaddress.IPv4Network((cursor, prefix))
        if not net.subnet_of(base_net):
            raise ValueError(f"{base} is too small: ran out of space at {name!r} ({hosts} hosts)")
        allocations.append(Allocation(name, hosts, net))
        cursor += size
    return allocations


def format_table(allocations: list[Allocation]) -> str:
    header = ("Subnet", "Hosts", "Usable", "Network", "Mask", "First", "Last", "Broadcast")
    rows = [
        (a.name, str(a.hosts_needed), str(a.usable), str(a.network), str(a.mask),
         str(a.first), str(a.last), str(a.network.broadcast_address))
        for a in allocations
    ]
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header))]
    line = lambda r: "| " + " | ".join(c.ljust(w) for c, w in zip(r, widths)) + " |"
    sep = "|" + "|".join("-" * (w + 2) for w in widths) + "|"
    return "\n".join([line(header), sep, *map(line, rows)])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base", help="address block, e.g. 172.16.0.0/23")
    parser.add_argument("subnets", nargs="+", help="NAME=HOSTS pairs")
    args = parser.parse_args()
    reqs = [(name, int(hosts)) for name, hosts in (s.split("=", 1) for s in args.subnets)]
    print(format_table(plan(args.base, reqs)))


if __name__ == "__main__":
    main()
