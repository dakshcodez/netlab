"""DNS lookup latency: cold (walk root → TLD → authoritative) vs warm (cached), plus partial
hits (delegations cached) and negative caching.

On one machine (real UDP sockets on 127.0.1.x, server replies delayed to emulate distance):

    uv run python -m experiments.phase3_dns_latency

On the Mininet testbed (real hosts, netem delay, optional tcpdump capture for the analyzer):

    sudo PYTHONPATH=. python3 -m experiments.phase3_dns_latency --testbed
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from netlab.common.plot import save  # noqa: E402
from netlab.common.results import RESULTS_DIR, Result  # noqa: E402
from netlab.dns import client, message as m  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
STEPS = [
    ("cold: www.example.lab", "www.example.lab", "walks root → TLD → authoritative (3 upstream queries)"),
    ("warm: www.example.lab again", "www.example.lab", "answer cached"),
    ("sibling: mail.example.lab", "mail.example.lab", "delegations cached → only the authoritative server"),
    ("NXDOMAIN: ghost.example.lab", "ghost.example.lab", "one upstream query, result negatively cached"),
    ("NXDOMAIN again", "ghost.example.lab", "negative cache hit"),
]


def run_steps(lookup, flush, repeats: int) -> list[dict]:
    """Run the step list ``repeats`` times (flush() empties the resolver cache before each round)."""
    rows = []
    for rep in range(repeats):
        flush()
        for label, name, note in STEPS:
            msg, secs = lookup(name)
            rows.append({"repeat": rep, "step": label, "rtt_ms": secs * 1000, "rcode": msg.rcode if msg else -1,
                         "note": note})
    return rows


def summarize(rows: list[dict]) -> list[dict]:
    out = []
    for label, _, note in STEPS:
        vals = [r["rtt_ms"] for r in rows if r["step"] == label]
        out.append({"step": label, "median_ms": round(statistics.median(vals), 2),
                    "min_ms": round(min(vals), 2), "max_ms": round(max(vals), 2), "note": note})
    return out


def plot(summary: list[dict], hop_rtt_ms: float, out: Path, subtitle: str) -> Path:
    fig, ax = plt.subplots(figsize=(8, 4))
    labels = [s["step"].replace(": ", ":\n") for s in summary]
    bars = ax.bar(labels, [s["median_ms"] for s in summary],
                  color=["#d1495b", "#00798c", "#edae49", "#d1495b", "#00798c"])
    for b, s in zip(bars, summary):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height(), f"{s['median_ms']:.1f}", ha="center", va="bottom", fontsize=9)
    ax.axhline(hop_rtt_ms, color="#999", ls="--", lw=1)
    ax.text(len(labels) - 0.5, hop_rtt_ms, f" 1 hop = {hop_rtt_ms:g} ms", va="bottom", ha="right", fontsize=8, color="#666")
    ax.set_ylabel("lookup time at client (ms, median)")
    ax.set_title(f"DNS lookup latency: cold vs cached ({subtitle})")
    ax.tick_params(axis="x", labelsize=7)
    ax.grid(axis="y", alpha=0.3)
    return save(fig, out)


def loopback(args) -> tuple[Result, float]:
    from netlab.dns.local import local_hierarchy

    result = Result(phase="phase3", experiment="dns_latency", level="real",
                    params={"mode": "loopback sockets, emulated delay", "hop_rtt_ms": args.hop_rtt_ms,
                            "client_rtt_ms": args.client_rtt_ms, "repeats": args.repeats})
    with local_hierarchy(port=5453, hop_rtt_ms=args.hop_rtt_ms, client_rtt_ms=args.client_rtt_ms) as (resolver, ip, port):
        rows = run_steps(lambda n: client.lookup(ip, n, port=port), resolver.cache.clear, args.repeats)
    result.rows = rows
    return result, args.hop_rtt_ms


def testbed(args) -> tuple[Result, float]:
    from netlab.testbed.net import Testbed
    from netlab.topology import library

    topo = library.dns_lab(args.link_delay_ms)
    hop_rtt = 4 * args.link_delay_ms
    result = Result(phase="phase3", experiment="dns_latency", level="real",
                    params={"mode": "mininet", "link_delay_ms": args.link_delay_ms, "hop_rtt_ms": hop_rtt,
                            "repeats": args.repeats})
    with Testbed(topo) as tb:
        ip = {n: str(topo.ip(n)) for n in topo.hosts}
        base = f"cd {REPO} && PYTHONPATH=. python3 -m netlab.dns.server"
        addrs = f"--root-ip {ip['root']} --tld-ip {ip['tld']} --example-ip {ip['auth']}"
        procs = [
            tb.node("root").popen(["sh", "-c", f"{base} auth --zone root {addrs} --bind {ip['root']}"]),
            tb.node("tld").popen(["sh", "-c", f"{base} auth --zone tld {addrs} --bind {ip['tld']}"]),
            tb.node("auth").popen(["sh", "-c", f"{base} auth --zone example {addrs} --bind {ip['auth']}"]),
            tb.node("resolver").popen(["sh", "-c", f"{base} resolver --root {ip['root']} --bind {ip['resolver']}"]),
        ]
        time.sleep(2)
        capture = None
        pcap = RESULTS_DIR / "phase3" / "dns_latency.pcap"
        pcap.parent.mkdir(parents=True, exist_ok=True)
        if shutil.which("tcpdump"):
            intf = topo.interfaces["resolver"][0].name
            capture = tb.node("resolver").popen(["tcpdump", "-i", intf, "-U", "-w", str(pcap), "udp", "port", "53"])
            time.sleep(1)

        def lookup(name):
            out = tb.node("client").cmd(f"cd {REPO} && PYTHONPATH=. python3 -m netlab.dns.client {name} --server {ip['resolver']}")
            data = json.loads(out[out.index("["):])[0]
            return (m.Message(flags=data["rcode"]) if data["rcode"] is not None else None), data["rtt_ms"] / 1000

        def flush():  # restart the resolver for a guaranteed-cold cache
            procs[3].terminate()
            procs[3].wait()
            procs[3] = tb.node("resolver").popen(["sh", "-c", f"{base} resolver --root {ip['root']} --bind {ip['resolver']}"])
            time.sleep(1.5)

        result.rows = run_steps(lookup, flush, args.repeats)
        if capture:
            capture.terminate()
            result.params["pcap"] = str(pcap)
        for p in procs:
            p.terminate()
    return result, hop_rtt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--testbed", action="store_true")
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--hop-rtt-ms", type=float, default=20.0, help="loopback mode: RTT to each server")
    parser.add_argument("--client-rtt-ms", type=float, default=2.0, help="loopback mode: RTT client ↔ resolver")
    parser.add_argument("--link-delay-ms", type=float, default=5.0, help="testbed mode: delay per link, per direction")
    args = parser.parse_args()
    if args.testbed and os.geteuid() != 0:
        raise SystemExit("--testbed needs root: sudo PYTHONPATH=. python3 -m experiments.phase3_dns_latency --testbed")
    result, hop_rtt = (testbed if args.testbed else loopback)(args)
    result.summary = {"steps": summarize(result.rows)}
    for s in result.summary["steps"]:
        print(f"{s['step']:<30} median {s['median_ms']:>7.2f} ms   ({s['note']})")
    plot(result.summary["steps"], hop_rtt, RESULTS_DIR / "phase3" / "dns_latency.png",
         "mininet" if args.testbed else "loopback sockets, emulated delay")
    print(f"saved {result.save()}")


if __name__ == "__main__":
    main()
