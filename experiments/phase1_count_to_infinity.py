"""Count-to-infinity in distance-vector routing, and what split horizon / poison reverse fix.

Simulation only (runs anywhere):

    uv run python -m experiments.phase1_count_to_infinity
"""

from __future__ import annotations

import argparse

from netlab.common.results import RESULTS_DIR, Result
from netlab.routing.distance_vector import DistanceVector
from netlab.routing.plot import plot_count_to_infinity
from netlab.topology.library import COUNT_TO_INFINITY

MODES = {
    "plain": {},
    "split horizon": {"split_horizon": True},
    "poison reverse": {"poison_reverse": True},
}


def run_case(name: str, infinity: int, observer: str) -> tuple[Result, dict[str, list[int]]]:
    case = COUNT_TO_INFINITY[name]
    result = Result(phase="phase1", experiment=f"count_to_infinity_{name}", level="sim",
                    params={"graph": name, "fail": case["fail"], "dest": case["dest"],
                            "infinity": infinity, "observer": observer})
    histories = {}
    for label, opts in MODES.items():
        dv = DistanceVector(case["graph"], infinity=infinity, **opts)
        dv.run()
        dv.set_link(*case["fail"], None)
        costs = [dv.cost(observer, case["dest"])]
        while dv.step():
            costs.append(dv.cost(observer, case["dest"]))
        histories[label] = costs
        result.add(mode=label, rounds_to_converge=len(costs) - 1, final_cost=costs[-1],
                   peak_cost=max(costs))
    return result, histories


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--infinity", type=int, default=16)
    args = parser.parse_args()

    for name in COUNT_TO_INFINITY:
        result, histories = run_case(name, args.infinity, observer="A")
        result.save()
        png = plot_count_to_infinity(
            histories, args.infinity,
            f"Count-to-infinity: '{name}' graph, node A's cost to {COUNT_TO_INFINITY[name]['dest']}",
            RESULTS_DIR / "phase1" / f"count_to_infinity_{name}.png",
        )
        print(f"\n{name}:")
        for row in result.rows:
            print(f"  {row['mode']:<15} rounds={row['rounds_to_converge']:>3}  final cost={row['final_cost']}")
        print(f"  plot: {png}")


if __name__ == "__main__":
    main()
