"""Distance-vector routing (what RIP does), simulated in synchronous rounds.

Each round every node sends its distance vector to each neighbour, then recomputes its
table purely from its link costs and the latest vectors it received (Bellman-Ford). This is
enough to reproduce count-to-infinity and to show what split horizon and poison reverse fix.
"""

from __future__ import annotations

from dataclasses import dataclass

Graph = dict[str, dict[str, int]]


@dataclass(frozen=True)
class Entry:
    cost: int
    next_hop: str | None  # None for the node itself or unreachable


class DistanceVector:
    def __init__(
        self,
        graph: Graph,
        infinity: int = 16,
        split_horizon: bool = False,
        poison_reverse: bool = False,
    ) -> None:
        self.links: Graph = {n: dict(nbrs) for n, nbrs in graph.items()}
        self.infinity = infinity
        self.split_horizon = split_horizon or poison_reverse
        self.poison_reverse = poison_reverse
        self.nodes = sorted(self.links)
        self.tables: dict[str, dict[str, Entry]] = {
            n: {d: Entry(0 if d == n else infinity, None) for d in self.nodes} for n in self.nodes
        }
        # inbox[n][m] = last vector node n received from neighbour m
        self.inbox: dict[str, dict[str, dict[str, int]]] = {n: {} for n in self.nodes}
        self.rounds = 0

    def set_link(self, a: str, b: str, cost: int | None) -> None:
        """Change a link's cost, or remove it with cost=None (link failure)."""
        if cost is None:
            self.links[a].pop(b, None)
            self.links[b].pop(a, None)
            self.inbox[a].pop(b, None)
            self.inbox[b].pop(a, None)
        else:
            self.links[a][b] = self.links[b][a] = cost

    def _advertise(self, sender: str, receiver: str) -> dict[str, int]:
        vector = {}
        for dest, entry in self.tables[sender].items():
            if entry.next_hop == receiver and self.split_horizon:
                if self.poison_reverse:
                    vector[dest] = self.infinity
                continue  # plain split horizon: don't mention the route at all
            vector[dest] = entry.cost
        return vector

    def step(self) -> bool:
        """Run one exchange + recompute round. Returns True if any table changed."""
        for sender in self.nodes:
            for receiver in self.links[sender]:
                self.inbox[receiver][sender] = self._advertise(sender, receiver)

        changed = False
        for node in self.nodes:
            new = {}
            for dest in self.nodes:
                if dest == node:
                    new[dest] = Entry(0, None)
                    continue
                best = Entry(self.infinity, None)
                for nbr, link_cost in sorted(self.links[node].items()):
                    advertised = self.inbox[node].get(nbr, {}).get(dest, self.infinity)
                    cost = min(link_cost + advertised, self.infinity)
                    if cost < best.cost:
                        best = Entry(cost, nbr)
                new[dest] = best
            if new != self.tables[node]:
                changed = True
            self.tables[node] = new
        self.rounds += 1
        return changed

    def run(self, max_rounds: int = 100) -> int:
        """Step until no table changes. Returns the number of rounds that changed something."""
        for i in range(max_rounds):
            if not self.step():
                return i
        raise RuntimeError(f"did not converge within {max_rounds} rounds")

    def cost(self, node: str, dest: str) -> int:
        return self.tables[node][dest].cost

    def next_hops(self, node: str, dest: str) -> frozenset[str]:
        """All neighbours offering the best cost (equal-cost alternatives included)."""
        best = self.cost(node, dest)
        if node == dest or best >= self.infinity:
            return frozenset()
        return frozenset(
            nbr for nbr, c in self.links[node].items()
            if c + self.inbox[node].get(nbr, {}).get(dest, self.infinity) == best
        )
