"""Draw the architecture and flowchart figures used in the report and slides: uv run python scripts/make_figures.py"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon

OUT = Path(__file__).resolve().parents[1] / "docs" / "figures"
OUT.mkdir(parents=True, exist_ok=True)
INK, TEAL, GREY, AMBER = "#1f2933", "#007c89", "#e4e7eb", "#f5b942"


def box(ax, x, y, w, h, text, fc="white", ec=INK, fs=9, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", fc=fc, ec=ec, lw=1.2))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color=INK,
            fontweight="bold" if bold else "normal", wrap=True)


def arrow(ax, p, q, text=None):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=12, color=INK, lw=1.1))
    if text:
        ax.text((p[0] + q[0]) / 2 + 0.05, (p[1] + q[1]) / 2 + 0.07, text, fontsize=8, color=INK)


def architecture():
    fig, ax = plt.subplots(figsize=(10, 5.6))
    ax.set_xlim(0, 10); ax.set_ylim(0, 5.6); ax.axis("off")
    box(ax, 0.2, 4.6, 9.6, 0.7, "Streamlit dashboard  (dashboard/app.py)   sliders, Run button, plots, tables", GREY, bold=True)
    box(ax, 0.2, 3.5, 9.6, 0.7, "Runners  (netlab/dashboard/runners.py)   parameter-driven small runs, no UI code", GREY)
    arrow(ax, (5, 4.6), (5, 4.2)); arrow(ax, (5, 3.5), (5, 3.1))
    labels = [("Phase 1\nVLSM, topology,\nDV / link-state\nsimulator", 0.2), ("Phase 2\nCRC / checksum,\nARQ state machines,\nchannel model", 2.7),
              ("Phase 3\nDNS hierarchy,\nTCP Reno/CUBIC/BBR,\npcap analyzer", 5.2), ("Common\nResult(JSON/CSV),\nplot helpers", 7.7)]
    for t, x in labels:
        box(ax, x, 1.75, 2.1, 1.25, t, "white", TEAL if "Phase 2" in t else INK, fs=9)
    ax.text(0.2, 1.45, "Three levels of every experiment", fontsize=10, fontweight="bold", color=INK)
    for t, x, fc in [("Theory\n(textbook formula)", 0.2, "white"), ("Simulation\n(our Python, seeded)", 3.45, "white"),
                     ("Reality\n(UDP loopback, netns + veth\n+ netem, Mininet + FRR)", 6.7, "white")]:
        box(ax, x, 0.2, 3.1, 1.0, t, fc, INK, fs=8.5)
    arrow(ax, (3.3, 0.7), (3.45, 0.7)); arrow(ax, (6.55, 0.7), (6.7, 0.7))
    fig.savefig(OUT / "architecture.png", dpi=180, bbox_inches="tight"); plt.close(fig)


def topology():
    fig, ax = plt.subplots(figsize=(10, 2.6))
    ax.set_xlim(0, 10); ax.set_ylim(0, 2.6); ax.axis("off")
    box(ax, 0.2, 0.9, 2.2, 1.0, "ARQ sender\n(SW / GBN / SR)\nwindow N, timeout T", "white", TEAL, bold=True)
    box(ax, 7.6, 0.9, 2.2, 1.0, "ARQ receiver\nin-order delivery\nCRC-32 check", "white", TEAL, bold=True)
    arrow(ax, (2.4, 1.6), (7.6, 1.6)); arrow(ax, (7.6, 1.1), (2.4, 1.1))
    ax.text(5, 1.75, "forward channel: rate 1 Mbit/s, delay a x t_frame, loss p, reorder q", ha="center", fontsize=8.5)
    ax.text(5, 0.78, "reverse channel: ACKs, same delay, no loss", ha="center", fontsize=8.5)
    ax.text(5, 0.2, "link utilisation = ideal time / elapsed time;  a = propagation delay / frame time;  round trip = 1 + 2a frames",
            ha="center", fontsize=8.5, style="italic")
    fig.savefig(OUT / "sim_topology.png", dpi=180, bbox_inches="tight"); plt.close(fig)


def flowchart():
    fig, ax = plt.subplots(figsize=(7.5, 8.4))
    ax.set_xlim(0, 7.5); ax.set_ylim(0, 8.4); ax.axis("off")

    def dia(cx, cy, w, h, t):
        ax.add_patch(Polygon([(cx - w / 2, cy), (cx, cy + h / 2), (cx + w / 2, cy), (cx, cy - h / 2)], fc="#fff6e0", ec=INK, lw=1.2))
        ax.text(cx, cy, t, ha="center", va="center", fontsize=8.5)

    box(ax, 2.1, 7.7, 3.3, 0.6, "Start: link parameters (rate, delay, loss)", GREY, fs=9)
    box(ax, 2.1, 6.7, 3.3, 0.7, "a = delay / frame time\nK = 1 + 2a", "white", fs=9)
    box(ax, 1.7, 5.6, 4.1, 0.8, "PROPOSED RULE\nN = ceil( 2 x K )   (baseline: N = K)", "#d7f0f2", TEAL, bold=True, fs=9)
    box(ax, 2.1, 4.6, 3.3, 0.6, "Send new frames while in-flight < N", "white", fs=9)
    dia(3.75, 3.3, 3.2, 1.5, "Next event")
    box(ax, 0.1, 1.6, 2.6, 0.8, "ACK(seq) arrives:\nmark acked, slide base", "white", fs=8.5)
    box(ax, 4.8, 1.6, 2.6, 0.8, "Timer(seq) expires:\nretransmit only seq", "white", fs=8.5)
    dia(3.75, 0.8, 3.0, 1.2, "All frames\nacked?")
    arrow(ax, (3.75, 7.7), (3.75, 7.4)); arrow(ax, (3.75, 6.7), (3.75, 6.4)); arrow(ax, (3.75, 5.6), (3.75, 5.2))
    arrow(ax, (3.75, 4.6), (3.75, 4.05))
    arrow(ax, (2.15, 3.3), (1.4, 2.4)); arrow(ax, (5.35, 3.3), (6.1, 2.4))
    ax.text(1.0, 2.95, "ACK", fontsize=8.5); ax.text(6.0, 2.95, "timeout", fontsize=8.5)
    arrow(ax, (1.4, 1.6), (2.6, 0.9)); arrow(ax, (6.1, 1.6), (4.9, 0.9))
    ax.plot([5.25, 7.3, 7.3], [0.8, 0.8, 4.9], color=INK, lw=1.1)
    arrow(ax, (7.3, 4.9), (5.4, 4.9)); ax.text(5.5, 0.9, "no", fontsize=8.5)
    ax.text(3.0, 0.05, "yes: done, efficiency = ideal time / elapsed", fontsize=8.5)
    fig.savefig(OUT / "flowchart_sr_window.png", dpi=180, bbox_inches="tight"); plt.close(fig)


if __name__ == "__main__":
    architecture(); topology(); flowchart()
