"""Novelty experiment: Selective Repeat with the textbook window (1+2a) vs the RTT-aware window 2(1+2a).

    uv run python -m experiments.phase2_sr_window

Each scenario is repeated with ``--runs`` different channel seeds; mean and standard deviation are reported.
"""

from __future__ import annotations

import argparse
from statistics import mean, stdev

from netlab.common.plot import COLORS
from netlab.common.results import RESULTS_DIR, Result
from netlab.reliability import arq, theory
from netlab.reliability.channel import Channel
from netlab.reliability.sim import simulate, standard_setup

PAYLOAD = 100
FRAME = arq.OVERHEAD + PAYLOAD
SCENARIOS = {"S1 (low loss, 1%)": 0.01, "S2 (medium loss, 5%)": 0.05, "S3 (high loss, 20%)": 0.20}


def runs(window: int, loss: float, a: float, n: int, seeds: int) -> list[float]:
    _, delay, timeout = standard_setup(a, FRAME)
    out = []
    for s in range(1, seeds + 1):
        r = simulate("sr", n, window, timeout, Channel(delay=delay, loss=loss, rate_bps=1e6, seed=s),
                     Channel(delay=delay, seed=1000 + s), PAYLOAD)
        assert r.finished and r.wrong_payloads == 0
        out.append(r.efficiency)
    return out


def real_level(n_runs: int, n_packets: int = 150) -> None:
    """Same two windows over real UDP sockets (user-space delay/loss relay on loopback), 2 ms frames."""
    from netlab.reliability.udp import run_loopback

    tx = (arq.OVERHEAD + 1000) * 8 / 4e6
    a = 5.0
    out = Result(phase="phase2", experiment="sr_window_real", level="real",
                 params={"a": a, "packets": n_packets, "runs": n_runs, "payload_bytes": 1000, "rate_bps": 4e6})
    for name, p in SCENARIOS.items():
        row = {"scenario": name, "loss": p}
        for label, w in (("baseline", int(1 + 2 * a)), ("proposed", theory.recommended_sr_window(a))):
            effs = []
            for s in range(1, n_runs + 1):
                r = run_loopback("sr", n_packets, w, 2 * a * tx + 1e-3, 4e6, a * tx, loss=p, payload_size=1000, seed=s)
                assert r.finished and r.wrong_payloads == 0
                effs.append(r.efficiency)
            row[f"{label}_mean"], row[f"{label}_sd"] = mean(effs), stdev(effs)
        row["improvement_pct"] = (row["proposed_mean"] / row["baseline_mean"] - 1) * 100
        out.add(**row)
        print(f"real {name}: {row['baseline_mean']:.3f}±{row['baseline_sd']:.3f} -> "
              f"{row['proposed_mean']:.3f}±{row['proposed_sd']:.3f}  +{row['improvement_pct']:.1f}%")
    print(out.save())


def main() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--packets", type=int, default=3000)
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--real", action="store_true", help="also repeat the scenarios over real UDP sockets on loopback")
    args = ap.parse_args()
    a = 5.0
    base_w, new_w = int(1 + 2 * a), theory.recommended_sr_window(a)
    result = Result(phase="phase2", experiment="sr_window_novelty", level="sim",
                    params={"a": a, "baseline_window": base_w, "proposed_window": new_w,
                            "packets": args.packets, "runs": args.runs})
    labels, bm, bs, pm, ps = [], [], [], [], []
    for name, p in SCENARIOS.items():
        b, n = runs(base_w, p, a, args.packets, args.runs), runs(new_w, p, a, args.packets, args.runs)
        impr = (mean(n) / mean(b) - 1) * 100
        result.add(scenario=name, loss=p, baseline_mean=mean(b), baseline_sd=stdev(b), proposed_mean=mean(n),
                   proposed_sd=stdev(n), improvement_pct=impr, theory_ideal=1 - p)
        labels.append(name.split(" ")[0] + f"\nloss {p:.0%}")
        bm.append(mean(b)); bs.append(stdev(b)); pm.append(mean(n)); ps.append(stdev(n))
        print(f"{name}: baseline {mean(b):.3f}±{stdev(b):.3f}  proposed {mean(n):.3f}±{stdev(n):.3f}  +{impr:.1f}%")
    xs = range(len(labels))
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar([x - 0.2 for x in xs], bm, 0.4, yerr=bs, capsize=4, label=f"Baseline SR, window {base_w} (=1+2a)", color="#9aa5b1")
    ax.bar([x + 0.2 for x in xs], pm, 0.4, yerr=ps, capsize=4, label=f"Proposed SR, window {new_w} (=2(1+2a))", color=COLORS["sr"])
    ax.set_xticks(list(xs)); ax.set_xticklabels(labels); ax.set_ylabel("link efficiency"); ax.set_ylim(0, 1.05)
    ax.set_title(f"Selective Repeat: textbook vs RTT-aware window (a = {a:g}, {args.runs} runs)")
    ax.legend(loc="lower left", fontsize=8); fig.tight_layout()
    fig.savefig(RESULTS_DIR / "phase2" / "sr_window_novelty.png", dpi=150)
    print(result.save())

    # Sensitivity: does the 2(1+2a) rule keep helping as the round trip grows? (loss fixed at 5%)
    sweep = Result(phase="phase2", experiment="sr_window_vs_a", level="sim",
                   params={"loss": 0.05, "packets": args.packets, "runs": args.runs})
    for aa in (1.0, 5.0, 10.0, 20.0):
        bw, nw = int(1 + 2 * aa), theory.recommended_sr_window(aa)
        b, n = runs(bw, 0.05, aa, args.packets, args.runs), runs(nw, 0.05, aa, args.packets, args.runs)
        sweep.add(a=aa, baseline_window=bw, proposed_window=nw, baseline_mean=mean(b), baseline_sd=stdev(b),
                  proposed_mean=mean(n), proposed_sd=stdev(n), improvement_pct=(mean(n) / mean(b) - 1) * 100)
        print(f"a={aa:g}: w {bw}->{nw}  {mean(b):.3f}±{stdev(b):.3f} -> {mean(n):.3f}±{stdev(n):.3f}")
    print(sweep.save())
    if args.real:
        real_level(args.runs)


if __name__ == "__main__":
    main()
