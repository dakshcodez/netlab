"""ARQ experiments: theory vs simulation (vs real UDP sockets with ``--real``).

    uv run python -m experiments.phase2_arq                  # all four, simulation + theory
    uv run python -m experiments.phase2_arq --real           # add real UDP loopback points
    uv run python -m experiments.phase2_arq --only window

Experiments: ``efficiency`` (vs loss), ``window`` (GBN vs SR vs window size), ``timeout``
(sensitivity) and ``reorder`` (effect of packet reordering).
"""

from __future__ import annotations

import argparse
from statistics import mean

from netlab.common.plot import COLORS, line_plot
from netlab.common.results import RESULTS_DIR, Result
from netlab.reliability import arq, theory
from netlab.reliability.channel import Channel
from netlab.reliability.sim import simulate, standard_setup

PAYLOAD = 100
FRAME = arq.OVERHEAD + PAYLOAD
A = 5.0  # propagation delay / frame time → 1 + 2a = 11 frames per round trip
SEEDS = (1, 2, 3)
LABELS = {"sw": "Stop-and-Wait", "gbn": "Go-Back-N", "sr": "Selective Repeat"}

# Real-socket parameters: ~2 ms per frame so OS timer jitter (~0.1-1 ms) is a few percent.
REAL_PAYLOAD = 1000
REAL_RATE = 4e6
REAL_TX = (arq.OVERHEAD + REAL_PAYLOAD) * 8 / REAL_RATE
REAL_PACKETS = 150


def sim_eff(protocol: str, window: int, loss: float, n: int, a: float = A, timeout_factor: float = 1.0,
            **channel_kw) -> tuple[float, float, float]:
    """Mean (efficiency, retransmissions per packet, out-of-order discards per packet) over seeds."""
    _, delay, timeout = standard_setup(a, FRAME)
    runs = [simulate(protocol, n, window, timeout * timeout_factor,
                     Channel(delay=delay, loss=loss, rate_bps=1e6, seed=s, **channel_kw),
                     Channel(delay=delay, seed=100 + s), PAYLOAD) for s in SEEDS]
    assert all(r.finished and r.wrong_payloads == 0 for r in runs)
    return (mean(r.efficiency for r in runs), mean(r.retransmissions for r in runs) / n,
            mean(r.discarded_out_of_order for r in runs) / n)


def real_eff(protocol: str, window: int, loss: float, a: float = A, n: int = REAL_PACKETS,
             timeout_factor: float = 1.0, **kw) -> float:
    from netlab.reliability.udp import run_loopback

    delay = a * REAL_TX
    run = run_loopback(protocol, n, window, 2 * delay * timeout_factor + 1e-3, REAL_RATE, delay,
                       loss=loss, payload_size=REAL_PAYLOAD, **kw)
    assert run.finished and run.wrong_payloads == 0, run
    return run.efficiency


def exp_efficiency(real: bool, n: int) -> Result:
    result = Result(phase="phase2", experiment="arq_efficiency", level="sim",
                    params={"a": A, "windows": {"sw": 1, "gbn": 8, "sr": 32}, "packets": n,
                            "seeds": list(SEEDS), "real_packets": REAL_PACKETS if real else None})
    losses = [0.0, 0.01, 0.02, 0.05, 0.1, 0.15, 0.2, 0.3]
    real_losses = [0.0, 0.05, 0.1, 0.2]
    # SR with window 32 > 2(1+2a) hides losses; GBN with 8 < 1+2a is window-limited.
    series = []
    for proto, window in (("sw", 1), ("gbn", 8), ("sr", 32)):
        sim = [sim_eff(proto, window, p, n)[0] for p in losses]
        th = [theory.efficiency(proto, A, p, window) for p in losses]
        for p, s, t in zip(losses, sim, th):
            result.add(protocol=proto, window=window, loss=p, level="sim", efficiency=s)
            result.add(protocol=proto, window=window, loss=p, level="theory", efficiency=t)
        series += [{"x": losses, "y": sim, "label": f"{LABELS[proto]} sim", "color": COLORS[proto]},
                   {"x": losses, "y": th, "label": f"{LABELS[proto]} theory", "color": COLORS[proto], "style": "theory"}]
        if real:
            r = [real_eff(proto, window, p) for p in real_losses]
            for p, e in zip(real_losses, r):
                result.add(protocol=proto, window=window, loss=p, level="real", efficiency=e)
            series.append({"x": real_losses, "y": r, "label": f"{LABELS[proto]} real UDP",
                           "color": COLORS[proto], "style": "real"})
    line_plot(series, RESULTS_DIR / "phase2" / "arq_efficiency.png",
              f"ARQ efficiency vs loss (a = {A:g}, windows SW 1 / GBN 8 / SR 32)",
              "frame loss probability", "link efficiency", ylim=(0, 1.0))
    return result


def exp_window(real: bool, n: int) -> Result:
    p = 0.05
    result = Result(phase="phase2", experiment="arq_window", level="sim",
                    params={"a": A, "loss": p, "packets": n})
    windows = [1, 2, 4, 8, 11, 16, 24, 32, 48]
    real_windows = [2, 8, 16, 32]
    series = []
    for proto in ("gbn", "sr"):
        sim = [sim_eff(proto, w, p, n)[0] for w in windows]
        th = [theory.efficiency(proto, A, p, w) for w in windows]
        for w, s, t in zip(windows, sim, th):
            result.add(protocol=proto, window=w, level="sim", efficiency=s)
            result.add(protocol=proto, window=w, level="theory", efficiency=t)
        series += [{"x": windows, "y": sim, "label": f"{LABELS[proto]} sim", "color": COLORS[proto]},
                   {"x": windows, "y": th, "label": f"{LABELS[proto]} theory", "color": COLORS[proto], "style": "theory"}]
        if real:
            r = [real_eff(proto, w, p) for w in real_windows]
            for w, e in zip(real_windows, r):
                result.add(protocol=proto, window=w, level="real", efficiency=e)
            series.append({"x": real_windows, "y": r, "label": f"{LABELS[proto]} real UDP",
                           "color": COLORS[proto], "style": "real"})
    line_plot(series, RESULTS_DIR / "phase2" / "arq_window.png",
              f"Efficiency vs window size (loss {p:.0%}, a = {A:g}, 1+2a = {1 + 2 * A:g})",
              "window size (frames)", "link efficiency", ylim=(0, 1.0))
    return result


def exp_timeout(real: bool, n: int) -> Result:
    p, window = 0.05, 16
    result = Result(phase="phase2", experiment="arq_timeout", level="sim",
                    params={"a": A, "loss": p, "window": window, "packets": n,
                            "note": "timeout factor 1.0 = exactly one ACK round trip"})
    factors = [0.25, 0.5, 0.75, 0.9, 1.0, 1.25, 1.5, 2, 3, 4]
    series = []
    for proto in ("gbn", "sr"):
        sim, spurious = [], []
        for f in factors:
            eff, retx, _ = sim_eff(proto, window, p, n, timeout_factor=f)
            sim.append(eff)
            spurious.append(retx)
            result.add(protocol=proto, timeout_factor=f, efficiency=eff, retransmissions_per_packet=retx)
        series.append({"x": factors, "y": sim, "label": LABELS[proto], "color": COLORS[proto]})
        if real:
            rf = [0.5, 1.0, 2.0, 4.0]
            r = [real_eff(proto, window, p, timeout_factor=f) for f in rf]
            for f, e in zip(rf, r):
                result.add(protocol=proto, timeout_factor=f, level="real", efficiency=e)
            series.append({"x": rf, "y": r, "label": f"{LABELS[proto]} real UDP",
                           "color": COLORS[proto], "style": "real"})
    line_plot(series, RESULTS_DIR / "phase2" / "arq_timeout.png",
              f"Timeout sensitivity (window {window}, loss {p:.0%}); 1.0 = ACK round-trip time",
              "timeout / round-trip time", "link efficiency", logx=True, ylim=(0, 1.0))
    return result


def exp_reorder(real: bool, n: int) -> Result:
    window = 16
    result = Result(phase="phase2", experiment="arq_reorder", level="sim",
                    params={"a": A, "loss": 0.0, "window": window, "packets": n,
                            "reorder_delay_frames": 3, "note": "no loss at all: only reordering"})
    probs = [0.0, 0.02, 0.05, 0.1, 0.2, 0.3]
    _, _, _ = standard_setup(A, FRAME)
    tx_time = FRAME * 8 / 1e6
    series, discards = [], []
    for proto in ("gbn", "sr"):
        eff, disc = [], []
        for q in probs:
            e, retx, d = sim_eff(proto, window, 0.0, n, reorder=q, reorder_delay=3 * tx_time)
            eff.append(e)
            disc.append(d)
            result.add(protocol=proto, reorder_prob=q, level="sim", efficiency=e,
                       retransmissions_per_packet=retx, out_of_order_discards_per_packet=d)
        series.append({"x": probs, "y": eff, "label": LABELS[proto], "color": COLORS[proto]})
        if real:
            rq = [0.0, 0.1, 0.3]
            r = [real_eff(proto, window, 0.0, reorder=q, reorder_delay=3 * REAL_TX) for q in rq]
            for q, e in zip(rq, r):
                result.add(protocol=proto, reorder_prob=q, level="real", efficiency=e)
            series.append({"x": rq, "y": r, "label": f"{LABELS[proto]} real UDP",
                           "color": COLORS[proto], "style": "real"})
    line_plot(series, RESULTS_DIR / "phase2" / "arq_reorder.png",
              "Effect of reordering with zero loss (frames delayed by 3 frame-times)",
              "probability a frame is reordered", "link efficiency", ylim=(0, 1.0))
    return result


EXPERIMENTS = {"efficiency": exp_efficiency, "window": exp_window,
               "timeout": exp_timeout, "reorder": exp_reorder}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", choices=list(EXPERIMENTS))
    parser.add_argument("--real", action="store_true", help="also run real UDP loopback points (slower)")
    parser.add_argument("--packets", type=int, default=3000, help="packets per simulated run")
    args = parser.parse_args()
    for name, fn in EXPERIMENTS.items():
        if args.only and args.only != name:
            continue
        result = fn(args.real, args.packets)
        path = result.save()
        print(f"{name}: {len(result.rows)} rows → {path}")
        for row in result.rows[:0]:
            print(row)


if __name__ == "__main__":
    main()
