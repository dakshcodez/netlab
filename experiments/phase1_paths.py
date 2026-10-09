"""Predicted RIP vs OSPF paths and routing tables for a topology (simulation only).

    uv run python -m experiments.phase1_paths --topology trap
"""

from __future__ import annotations

import argparse

from netlab.common.results import RESULTS_DIR, Result
from netlab.routing.plot import draw_topology
from netlab.routing.tables import path, predict
from netlab.topology import library


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--topology", default="trap", choices=library.TOPOLOGIES)
    args = parser.parse_args()
    topo = library.get(args.topology)

    result = Result(phase="phase1", experiment=f"predicted_routes_{topo.name}", level="sim",
                    params={"topology": topo.name})
    paths = {}
    for protocol in ("rip", "ospf"):
        paths[protocol] = path(topo, "h1", "h2", protocol)
        bottleneck = min(topo.link_between(a, b).bw_mbps
                         for a, b in zip(paths[protocol], paths[protocol][1:]))
        result.summary[protocol] = {"path": paths[protocol], "bottleneck_mbps": bottleneck}
        print(f"{protocol.upper():<5} h1→h2: {' → '.join(paths[protocol])}  (bottleneck {bottleneck:g} Mb/s)")
        for router in topo.routers:
            for prefix, route in sorted(predict(topo, router, protocol).items()):
                result.add(protocol=protocol, router=router, prefix=prefix, metric=route.metric,
                           next_hops=" ".join(sorted(route.next_hops)))
    result.save()
    png = draw_topology(topo, paths, RESULTS_DIR / "phase1" / f"paths_{topo.name}.png")
    print(f"plot: {png}")


if __name__ == "__main__":
    main()
