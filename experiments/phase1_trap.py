"""Trap topology on the real testbed: does each protocol pick the path we predicted, and what
throughput does that path actually deliver?

Run on the testbed VM:

    sudo PYTHONPATH=. python3 -m experiments.phase1_trap
"""

from __future__ import annotations

import argparse

from netlab.common.results import Result
from netlab.routing.tables import path
from netlab.testbed.net import Testbed
from netlab.topology import library


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--protocols", nargs="+", default=["rip", "ospf"])
    parser.add_argument("--seconds", type=int, default=10, help="iperf3 duration")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    topo = library.trap()
    result = Result(phase="phase1", experiment="trap", level="real",
                    params={"topology": topo.name, "iperf_seconds": args.seconds})

    with Testbed(topo, verbose=args.verbose) as tb:
        for protocol in args.protocols:
            tb.start_routing(protocol)
            converged_s = tb.wait_converged()
            hops = tb.traceroute("h1", "h2")
            measured_path = ["h1", *(tb.owner_of(ip) for ip in hops)]
            predicted_path = path(topo, "h1", "h2", protocol)
            mbps = tb.iperf("h1", "h2", args.seconds)
            result.add(
                protocol=protocol,
                initial_convergence_s=round(converged_s, 2),
                predicted_path=" ".join(predicted_path),
                measured_path=" ".join(str(n) for n in measured_path),
                path_matches=measured_path == predicted_path,
                throughput_mbps=round(mbps, 2),
            )
            print(f"{protocol.upper():<5} path {' → '.join(map(str, measured_path))}  "
                  f"(predicted {'✓' if measured_path == predicted_path else '✗'})  {mbps:.2f} Mbit/s")
            tb.stop_routing()

    print(f"saved {result.save()}")


if __name__ == "__main__":
    main()
