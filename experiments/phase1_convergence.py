"""Convergence after a link failure on the active path, RIP vs OSPF, measured with a 10 ms ping.

Two failure modes:
  down    carrier loss: both interfaces go down, routers notice at once
  silent  link keeps carrier but drops everything: only protocol timers notice

Run on the testbed VM (the silent RIP case takes ~3.5 minutes with default timers):

    sudo PYTHONPATH=. python3 -m experiments.phase1_convergence
"""

from __future__ import annotations

import argparse
import time

from netlab.common.results import RESULTS_DIR, Result
from netlab.routing.plot import plot_convergence
from netlab.routing.tables import path
from netlab.testbed.frr import Timers
from netlab.testbed.measure import expected_outage, parse_ping
from netlab.testbed.net import Testbed
from netlab.topology import library

INTERVAL = 0.01
WARMUP = 3.0


def link_to_fail(topo, protocol: str) -> tuple[str, str]:
    """The last router-to-router link on the protocol's h1→h2 path."""
    hops = path(topo, "h1", "h2", protocol)
    routers = [h for h in hops if topo.nodes[h].is_router]
    return routers[-2], routers[-1]


def measure(tb: Testbed, protocol: str, mode: str, timers: Timers) -> dict:
    tb.start_routing(protocol, timers)
    tb.wait_converged()
    a, b = link_to_fail(tb.topo, protocol)
    lo, hi = expected_outage(protocol, mode, timers)
    duration = WARMUP + hi + 10

    h1 = tb.node("h1")
    ping = h1.popen(["ping", "-D", "-n", "-i", str(INTERVAL), "-w", str(int(duration)),
                     str(tb.topo.ip("h2"))], text=True)
    time.sleep(WARMUP)
    tb.fail_link(a, b, mode)
    output, _ = ping.communicate()
    outage = parse_ping(output, INTERVAL)

    tb.restore_link(a, b)
    tb.stop_routing()
    return {
        "protocol": protocol, "mode": mode, "failed_link": f"{a}-{b}",
        "outage_s": round(outage.outage_s, 3), "lost_pings": outage.lost,
        "expected_min_s": lo, "expected_max_s": hi,
        "within_theory": lo - 1 <= outage.outage_s <= hi + 1,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--protocols", nargs="+", default=["ospf", "rip"])
    parser.add_argument("--modes", nargs="+", default=["down", "silent"])
    parser.add_argument("--fast-timers", action="store_true",
                        help="RIP 5/30/20, OSPF hello 1 dead 4: same shape, much shorter run")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    timers = Timers(5, 30, 20, 1, 4) if args.fast_timers else Timers()
    topo = library.trap()
    name = "convergence_fast" if args.fast_timers else "convergence"
    result = Result(phase="phase1", experiment=name, level="real",
                    params={"topology": topo.name, "ping_interval_s": INTERVAL, "timers": vars(timers)})

    with Testbed(topo, verbose=args.verbose) as tb:
        for protocol in args.protocols:
            for mode in args.modes:
                row = measure(tb, protocol, mode, timers)
                result.add(**row)
                print(f"{protocol.upper():<5} {mode:<7} outage {row['outage_s']:>7.2f}s  "
                      f"theory {row['expected_min_s']:.0f}–{row['expected_max_s']:.0f}s  "
                      f"{'✓' if row['within_theory'] else '✗'}")

    print(f"saved {result.save()}")
    print(f"plot  {plot_convergence(result.rows, RESULTS_DIR / 'phase1' / f'{name}.png')}")


if __name__ == "__main__":
    main()
