"""Validate the routing simulator against FRR: for every router and prefix, compare the
predicted metric and next hops with what RIP/OSPF actually installed.

Run on the testbed VM:

    sudo PYTHONPATH=. python3 -m experiments.phase1_validate --topology mesh
"""

from __future__ import annotations

import argparse

from netlab.common.results import Result
from netlab.routing.tables import predict
from netlab.testbed.net import Testbed
from netlab.topology import library


def compare(protocol: str, predicted, real: dict | None) -> tuple[bool, str]:
    if real is None:
        return False, "missing in FRR"
    if real["metric"] != predicted.metric:
        return False, f"metric {real['metric']} != {predicted.metric}"
    if protocol == "ospf" and real["next_hops"] != set(predicted.next_hops):
        return False, "next hops differ"
    # RIP installs a single route; on a tie any of the equal-cost next hops is correct
    if protocol == "rip" and not real["next_hops"] <= set(predicted.next_hops):
        return False, "next hop not among equal-cost options"
    return True, ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--topology", default="mesh", choices=library.TOPOLOGIES)
    parser.add_argument("--protocols", nargs="+", default=["rip", "ospf"])
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    topo = library.get(args.topology)
    result = Result(phase="phase1", experiment=f"validate_{topo.name}", level="real",
                    params={"topology": topo.name})

    with Testbed(topo, verbose=args.verbose) as tb:
        for protocol in args.protocols:
            tb.start_routing(protocol)
            tb.wait_converged()
            total = matched = 0
            for router in topo.routers:
                real = tb.routes(router)
                for prefix, route in sorted(predict(topo, router, protocol).items()):
                    ok, why = compare(protocol, route, real.get(prefix))
                    total += 1
                    matched += ok
                    r = real.get(prefix, {})
                    result.add(protocol=protocol, router=router, prefix=prefix,
                               predicted_metric=route.metric, real_metric=r.get("metric"),
                               predicted_next_hops=" ".join(sorted(route.next_hops)),
                               real_next_hops=" ".join(sorted(r.get("next_hops", []))),
                               match=ok, reason=why)
                    if not ok:
                        print(f"  ✗ {protocol} {router} {prefix}: {why}")
            result.summary[protocol] = {"routes": total, "matched": matched}
            print(f"{protocol.upper():<5} {matched}/{total} routes match the simulator")
            tb.stop_routing()

    print(f"saved {result.save()}")


if __name__ == "__main__":
    main()
