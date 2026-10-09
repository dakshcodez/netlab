"""Matplotlib figures for Phase 1."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from netlab.topology.model import Topology  # noqa: E402

PATH_COLORS = {"rip": "#d1495b", "ospf": "#00798c"}


def draw_topology(topo: Topology, paths: dict[str, list[str]], out: Path) -> Path:
    """Draw the topology with each protocol's chosen path overlaid."""
    fig, ax = plt.subplots(figsize=(8, 3.6))
    pos = {n: node.pos for n, node in topo.nodes.items()}
    for link in topo.links:
        (x1, y1), (x2, y2) = pos[link.a], pos[link.b]
        ax.plot([x1, x2], [y1, y2], color="#bbb", lw=1.5, zorder=1)
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.06, f"{link.bw_mbps:g} Mb/s",
                ha="center", fontsize=8, color="#666")
    for i, (protocol, hops) in enumerate(paths.items()):
        offset = (i - (len(paths) - 1) / 2) * 0.05
        for a, b in zip(hops, hops[1:]):
            (x1, y1), (x2, y2) = pos[a], pos[b]
            ax.plot([x1, x2], [y1 + offset, y2 + offset], color=PATH_COLORS.get(protocol),
                    lw=3, alpha=0.85, zorder=2, label=protocol.upper() if a == hops[0] else None)
    for name, node in topo.nodes.items():
        x, y = pos[name]
        ax.scatter([x], [y], s=650, zorder=3,
                   color="#2e4057" if node.is_router else "#edae49", edgecolor="white")
        ax.text(x, y, name, ha="center", va="center", color="white", fontsize=9, zorder=4)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=len(paths), frameon=False)
    ax.set_title(f"{topo.name}: path chosen by each protocol")
    ax.axis("off")
    ax.margins(0.12)
    return _save(fig, out)


def plot_count_to_infinity(histories: dict[str, list[int]], infinity: int, title: str, out: Path) -> Path:
    """histories: mode label -> route cost per round after the failure."""
    fig, ax = plt.subplots(figsize=(7, 4))
    styles = [("-", "o", 3.5), ("-", "s", 2.5), (":", "x", 1.5)]  # overlapping lines stay visible
    for (label, costs), (ls, marker, lw) in zip(histories.items(), styles):
        ax.plot(range(len(costs)), costs, ls=ls, lw=lw, marker=marker, ms=4, label=label)
    ax.axhline(infinity, color="#999", ls="--", lw=1)
    ax.text(0, infinity + 0.3, f"infinity = {infinity}", fontsize=8, color="#666")
    ax.set_xlabel("round after link failure")
    ax.set_ylabel("advertised cost to destination")
    ax.set_title(title)
    ax.legend(frameon=False)
    ax.grid(alpha=0.3)
    return _save(fig, out)


def plot_convergence(rows: list[dict], out: Path) -> Path:
    """Bar chart of measured outage per protocol/failure mode with theoretical range."""
    fig, ax = plt.subplots(figsize=(7, 4))
    labels = [f"{r['protocol'].upper()}\n{r['mode']}" for r in rows]
    measured = [r["outage_s"] for r in rows]
    ax.bar(labels, measured, color=[PATH_COLORS.get(r["protocol"]) for r in rows], alpha=0.85)
    for i, r in enumerate(rows):
        ax.plot([i, i], [r["expected_min_s"], r["expected_max_s"]], color="black", lw=2)
        ax.text(i, measured[i], f"{measured[i]:.1f}s", ha="center", va="bottom", fontsize=9)
    ax.set_ylabel("connectivity outage (s)")
    ax.set_title("Convergence after link failure (bar = measured, line = theory)")
    ax.grid(axis="y", alpha=0.3)
    return _save(fig, out)


def _save(fig, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out
