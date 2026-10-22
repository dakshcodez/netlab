"""Small matplotlib helpers shared by the experiments (headless backend)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# One colour per protocol/scheme everywhere, so plots from different phases read alike.
COLORS = {
    "sw": "#7a7a7a", "gbn": "#d1495b", "sr": "#00798c",
    "parity": "#7a7a7a", "2d-parity": "#edae49", "checksum": "#d1495b", "crc32": "#00798c",
    "reno": "#d1495b", "cubic": "#00798c", "bbr": "#edae49",
}


def save(fig, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def line_plot(series: list[dict], out: Path, title: str, xlabel: str, ylabel: str,
              logy: bool = False, logx: bool = False, ylim: tuple[float, float] | None = None,
              figsize: tuple[float, float] = (7, 4.2)) -> Path:
    """series: dicts with ``x``, ``y`` and optional ``label``, ``color``, ``style`` ("theory" draws
    a dashed line, "sim" a solid line with small markers, "real" large unfilled markers only)."""
    fig, ax = plt.subplots(figsize=figsize)
    for s in series:
        style = s.get("style", "sim")
        kw = {
            "theory": dict(ls="--", lw=1.8, marker=None),
            "sim": dict(ls="-", lw=1.6, marker="o", ms=3.5, alpha=0.9),
            "real": dict(ls="none", marker="D", ms=7, mfc="none", mew=1.8),
        }[style]
        ax.plot(s["x"], s["y"], color=s.get("color"), label=s.get("label"), **kw)
    if logy:
        ax.set_yscale("log")
    if logx:
        ax.set_xscale("log")
    if ylim:
        ax.set_ylim(*ylim)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(alpha=0.3)
    if any(s.get("label") for s in series):
        ax.legend(frameon=False, fontsize=8, ncol=2)
    return save(fig, out)
