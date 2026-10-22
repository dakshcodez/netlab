"""TCP congestion control: Reno vs CUBIC vs BBR, fairness, bufferbloat, and loss sensitivity.

Simulation (runs anywhere):

    uv run python -m experiments.phase3_tcp

Real Linux TCP on the Mininet testbed (iperf3 + ``ss -ti``; overlays the simulated Reno model on
the measured Reno cwnd, deliverable 3.7):

    sudo PYTHONPATH=. python3 -m experiments.phase3_tcp --testbed
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from netlab.common.plot import COLORS, line_plot, save  # noqa: E402
from netlab.common.results import RESULTS_DIR, Result  # noqa: E402
from netlab.tcp.sim import MSS_BYTES, jain, simulate  # noqa: E402

OUT = RESULTS_DIR / "phase3"
CCS = ["reno", "cubic", "bbr"]
BW, RTT = 10.0, 40.0
BDP = int(BW * 1e6 / (MSS_BYTES * 8) * RTT / 1000)  # packets in flight at line rate


def exp_cwnd(duration: float = 30) -> Result:
    result = Result(phase="phase3", experiment="tcp_cwnd", level="sim",
                    params={"bandwidth_mbps": BW, "rtt_ms": RTT, "buffer_pkts": BDP, "duration_s": duration})
    fig, axes = plt.subplots(len(CCS), 1, figsize=(8, 7), sharex=True)
    for ax, cc in zip(axes, CCS):
        res = simulate([cc], BW, RTT, BDP, duration)
        f = res.flows[0]
        t = [x[0] for x in f.trace]
        ax.plot(t, [x[1] for x in f.trace], color=COLORS[cc], lw=1.4, label="cwnd")
        ax.plot(t, [x[2] for x in f.trace], color="#888", lw=0.8, alpha=0.8, label="in flight")
        ax.axhline(BDP + BDP, color="#bbb", ls="--", lw=0.8)  # BDP + buffer: where drop-tail overflows
        ax.set_ylabel(f"{cc.upper()}\npackets")
        ax.set_ylim(0, 3 * BDP)
        ax.grid(alpha=0.3)
        mbps = res.throughput_mbps(f, 5, duration)
        result.add(cc=cc, throughput_mbps=round(mbps, 2), retransmissions=f.retransmissions,
                   timeouts=f.timeouts, mean_rtt_ms=round(res.mean_rtt_ms(f, 5), 1))
        ax.set_title(f"{cc.upper()}: {mbps:.1f} Mbit/s, {f.retransmissions} retransmissions", fontsize=9, loc="right")
    axes[0].legend(frameon=False, ncol=2, fontsize=8, loc="upper left")
    axes[-1].set_xlabel("time (s)")
    fig.suptitle(f"Congestion window over time ({BW:g} Mbit/s, RTT {RTT:g} ms, buffer = BDP = {BDP} pkts)")
    save(fig, OUT / "tcp_cwnd.png")
    return result


def exp_fairness(duration: float = 60) -> Result:
    result = Result(phase="phase3", experiment="tcp_fairness", level="sim",
                    params={"bandwidth_mbps": BW, "rtt_ms": RTT, "buffer_pkts": 2 * BDP, "duration_s": duration,
                            "measured_after_s": 10})
    pairs = [("reno", "reno"), ("cubic", "cubic"), ("bbr", "bbr"), ("cubic", "reno"), ("bbr", "cubic"), ("bbr", "reno")]
    fig, ax = plt.subplots(figsize=(8, 4))
    for i, (a, b) in enumerate(pairs):
        res = simulate([a, b], BW, RTT, 2 * BDP, duration)
        shares = [res.throughput_mbps(f, 10, duration) for f in res.flows]
        index = jain(shares)
        result.add(flow_a=a, flow_b=b, mbps_a=round(shares[0], 2), mbps_b=round(shares[1], 2),
                   jain_index=round(index, 3))
        ax.bar(i, shares[0], color=COLORS[a], edgecolor="white")
        ax.bar(i, shares[1], bottom=shares[0], color=COLORS[b], edgecolor="white", hatch="//")
        ax.text(i, shares[0] + shares[1] + 0.15, f"J={index:.2f}", ha="center", fontsize=8)
    ax.set_xticks(range(len(pairs)), [f"{a}\nvs {b}" for a, b in pairs], fontsize=8)
    ax.set_ylabel("throughput (Mbit/s), stacked: solid = first, hatched = second")
    ax.set_ylim(0, BW * 1.2)
    ax.set_title("Two flows on one bottleneck: shares and Jain's fairness index")
    ax.grid(axis="y", alpha=0.3)
    save(fig, OUT / "tcp_fairness.png")
    return result


def exp_bufferbloat(duration: float = 40) -> Result:
    result = Result(phase="phase3", experiment="tcp_bufferbloat", level="sim",
                    params={"bandwidth_mbps": BW, "rtt_ms": RTT, "duration_s": duration, "bdp_pkts": BDP})
    buffers = [10, 20, BDP, 100, 200, 400]
    rtt_series, tput_series = [], []
    for cc in CCS:
        rtts, tputs = [], []
        for buf in buffers:
            res = simulate([cc], BW, RTT, buf, duration)
            f = res.flows[0]
            rtts.append(res.mean_rtt_ms(f, 10))
            tputs.append(res.throughput_mbps(f, 10, duration))
            result.add(cc=cc, buffer_pkts=buf, mean_rtt_ms=round(rtts[-1], 1), throughput_mbps=round(tputs[-1], 2))
        rtt_series.append({"x": buffers, "y": rtts, "label": cc, "color": COLORS[cc]})
        tput_series.append({"x": buffers, "y": tputs, "label": cc, "color": COLORS[cc]})
    rtt_series.append({"x": buffers, "y": [RTT + b / (BW * 1e6 / (MSS_BYTES * 8)) * 1000 for b in buffers],
                       "label": "full queue (theory)", "color": "#999", "style": "theory"})
    line_plot(rtt_series, OUT / "tcp_bufferbloat_rtt.png",
              f"Latency under load vs buffer size (base RTT {RTT:g} ms)", "bottleneck buffer (packets)",
              "mean RTT (ms)", logx=True)
    line_plot(tput_series, OUT / "tcp_bufferbloat_throughput.png", "Throughput vs buffer size",
              "bottleneck buffer (packets)", "throughput (Mbit/s)", logx=True, ylim=(0, BW * 1.1))
    return result


def exp_loss(duration: float = 30) -> Result:
    result = Result(phase="phase3", experiment="tcp_loss", level="sim",
                    params={"bandwidth_mbps": BW, "rtt_ms": RTT, "buffer_pkts": BDP, "duration_s": duration})
    losses = [0.0, 0.0005, 0.001, 0.005, 0.01, 0.02, 0.05]
    series = []
    for cc in CCS:
        ys = []
        for p in losses:
            res = simulate([cc], BW, RTT, BDP, duration, random_loss=p)
            ys.append(res.throughput_mbps(res.flows[0], 5, duration))
            result.add(cc=cc, random_loss=p, throughput_mbps=round(ys[-1], 2))
        series.append({"x": losses, "y": ys, "label": cc, "color": COLORS[cc]})
    # Mathis et al.: rate ≈ (MSS/RTT) · 1.22/√p for Reno
    mathis = [min(BW, 1.22 * MSS_BYTES * 8 / (RTT / 1000) / (p ** 0.5) / 1e6) if p else BW for p in losses]
    series.append({"x": losses, "y": mathis, "label": "Reno, Mathis model", "color": COLORS["reno"], "style": "theory"})
    line_plot(series, OUT / "tcp_loss.png", "Throughput under random (non-congestion) loss",
              "random packet loss rate", "throughput (Mbit/s)", ylim=(0, BW * 1.1))
    return result


SIM_EXPERIMENTS = {"cwnd": exp_cwnd, "fairness": exp_fairness, "bufferbloat": exp_bufferbloat, "loss": exp_loss}


# --- real Linux TCP on the testbed ----------------------------------------------------

def _json(text: str):
    start = text.find("{")
    return json.JSONDecoder().raw_decode(text[start:])[0] if start >= 0 else None


def testbed(args) -> list[Result]:
    from netlab.tcp.trace import parse_timed_log
    from netlab.testbed import netem
    from netlab.testbed.net import Testbed
    from netlab.topology import library

    os.system("modprobe tcp_bbr 2>/dev/null; modprobe tcp_cubic 2>/dev/null")
    topo = library.dumbbell(bottleneck_mbps=BW, bottleneck_delay_ms=RTT / 2)
    results = []
    with Testbed(topo) as tb:
        tb.start_routing("ospf")
        tb.wait_converged()
        bott = topo.link_between("r1", "r2")

        def shape(buffer_pkts: int) -> None:
            fwd = netem.Shape(rate_mbit=BW, delay_ms=RTT / 2, limit_pkts=buffer_pkts)
            tb.node("r1").cmd(netem.apply_cmd(topo.interface("r1", bott).name, fwd))
            tb.node("r2").cmd(netem.apply_cmd(topo.interface("r2", bott).name, netem.Shape(delay_ms=RTT / 2)))

        def flow(src: str, dst: str, cc: str, seconds: int, log: str | None = None):
            """Start one iperf3 flow; returns a function that waits for it and gives (mbps, trace)."""
            tb.node(dst).cmd("pkill iperf3; sleep 0.2")
            port = 5201 + (src == "s2")
            server = tb.node(dst).popen(["iperf3", "-s", "-1", "-p", str(port)])
            time.sleep(0.5)
            sampler = None
            if log:
                sampler = tb.node(src).popen(["sh", "-c", f"while :; do date +%s.%N; ss -tin dst {topo.ip(dst)}; sleep 0.1; done > {log}"])
            client = tb.node(src).popen(["iperf3", "-c", str(topo.ip(dst)), "-p", str(port), "-t", str(seconds), "-C", cc, "-J"],
                                        stdout=-1)

            def finish():
                out = client.communicate()[0].decode()
                server.wait(timeout=10)
                if sampler:
                    sampler.terminate()
                report = _json(out)
                if report is None or "end" not in report:
                    raise RuntimeError(f"iperf3 failed: {out[:200]}")
                mbps = report["end"]["sum_received"]["bits_per_second"] / 1e6
                trace = parse_timed_log(open(log).read()) if log else []
                return mbps, trace
            return finish

        # 3.5: one flow per algorithm, cwnd from ss -ti
        shape(BDP)
        real = Result(phase="phase3", experiment="tcp_real_cwnd", level="real",
                      params={"bandwidth_mbps": BW, "rtt_ms": RTT, "buffer_pkts": BDP, "seconds": args.seconds})
        traces = {}
        for cc in CCS:
            mbps, trace = flow("s1", "d1", cc, args.seconds, log=f"/tmp/netlab_ss_{cc}.log")()
            traces[cc] = trace
            real.add(cc=cc, throughput_mbps=round(mbps, 2), samples=len(trace),
                     max_cwnd=max((s["cwnd"] for s in trace), default=None))
            real.summary[f"trace_{cc}"] = [{k: s[k] for k in ("t", "cwnd") if k in s} for s in trace]
            print(f"{cc:<6} {mbps:6.2f} Mbit/s  cwnd samples: {len(trace)}")
        results.append(real)
        plot_overlay(traces, args.seconds)

        # 3.6 fairness: two flows at once
        fair = Result(phase="phase3", experiment="tcp_real_fairness", level="real",
                      params={"bandwidth_mbps": BW, "rtt_ms": RTT, "buffer_pkts": 2 * BDP, "seconds": args.seconds})
        shape(2 * BDP)
        for a, b in [("reno", "reno"), ("cubic", "cubic"), ("cubic", "reno"), ("bbr", "cubic")]:
            fa, fb = flow("s1", "d1", a, args.seconds), flow("s2", "d2", b, args.seconds)
            (ma, _), (mb, _) = fa(), fb()
            fair.add(flow_a=a, flow_b=b, mbps_a=round(ma, 2), mbps_b=round(mb, 2), jain_index=round(jain([ma, mb]), 3))
            print(f"{a} vs {b}: {ma:.2f} / {mb:.2f} Mbit/s  Jain {jain([ma, mb]):.3f}")
        results.append(fair)

        # 3.6 bufferbloat: ping under load for several buffer sizes
        bloat = Result(phase="phase3", experiment="tcp_real_bufferbloat", level="real",
                       params={"bandwidth_mbps": BW, "rtt_ms": RTT, "seconds": args.seconds, "cc": "cubic"})
        for buf in (20, BDP, 400, 1000):
            shape(buf)
            load = flow("s1", "d1", "cubic", args.seconds)
            time.sleep(3)
            ping = tb.node("s2").cmd(f"ping -c {args.seconds - 6} -i 1 {topo.ip('d2')}")
            mbps, _ = load()
            m = re.search(r"= [\d.]+/([\d.]+)/", ping)
            bloat.add(buffer_pkts=buf, loaded_rtt_ms=float(m.group(1)) if m else None, throughput_mbps=round(mbps, 2))
            print(f"buffer {buf:>4}: loaded RTT {m.group(1) if m else '?'} ms, {mbps:.2f} Mbit/s")
        results.append(bloat)
    return results


def plot_overlay(traces: dict[str, list[dict]], seconds: int) -> None:
    """3.7: simulated Reno model on top of the measured Linux cwnds."""
    fig, axes = plt.subplots(len(traces), 1, figsize=(8, 7), sharex=True)
    for ax, (cc, trace) in zip(axes, traces.items()):
        ax.plot([s["t"] for s in trace], [s["cwnd"] for s in trace], color=COLORS[cc], lw=1.4, label=f"Linux {cc} (ss -ti)")
        model = simulate(["reno"], BW, RTT, BDP, seconds).flows[0]
        ax.plot([x[0] for x in model.trace], [x[1] for x in model.trace], color="#444", lw=1, ls="--", label="Reno simulator")
        ax.set_ylabel("cwnd (MSS)")
        ax.legend(frameon=False, fontsize=8, loc="upper right")
        ax.grid(alpha=0.3)
    axes[-1].set_xlabel("time (s)")
    fig.suptitle("Measured cwnd vs simulated Reno model")
    save(fig, OUT / "tcp_real_cwnd.png")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--testbed", action="store_true")
    parser.add_argument("--only", choices=list(SIM_EXPERIMENTS))
    parser.add_argument("--seconds", type=int, default=30, help="testbed: seconds per iperf3 run")
    args = parser.parse_args()
    if args.testbed:
        if os.geteuid() != 0:
            raise SystemExit("--testbed needs root: sudo PYTHONPATH=. python3 -m experiments.phase3_tcp --testbed")
        for r in testbed(args):
            print(f"saved {r.save()}")
        return
    for name, fn in SIM_EXPERIMENTS.items():
        if args.only and args.only != name:
            continue
        result = fn()
        print(f"{name}:")
        for row in result.rows[:12]:
            print("  ", row)
        print(f"  saved {result.save()}")


if __name__ == "__main__":
    main()
