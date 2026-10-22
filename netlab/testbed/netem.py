"""Link impairment via Linux ``tc netem``.

A single netem qdisc per interface handles bandwidth (``rate``), delay, jitter, loss,
corruption, duplication and reordering, so every phase shapes links the same way. netem
acts on egress, so apply the same shape to both ends of a link for symmetric behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Shape:
    rate_mbit: float | None = None
    delay_ms: float = 0.0
    jitter_ms: float = 0.0
    loss_pct: float = 0.0
    corrupt_pct: float = 0.0
    duplicate_pct: float = 0.0
    reorder_pct: float = 0.0  # needs delay > 0 to have any effect
    limit_pkts: int | None = None  # queue length; large values cause bufferbloat

    def args(self) -> list[str]:
        out: list[str] = []
        if self.delay_ms or self.jitter_ms:
            out += ["delay", f"{self.delay_ms}ms"]
            if self.jitter_ms:
                out += [f"{self.jitter_ms}ms", "distribution", "normal"]
        for keyword, value in (
            ("loss", self.loss_pct),
            ("corrupt", self.corrupt_pct),
            ("duplicate", self.duplicate_pct),
            ("reorder", self.reorder_pct),
        ):
            if value:
                out += [keyword, f"{value}%"]
        if self.rate_mbit:
            out += ["rate", f"{self.rate_mbit}mbit"]
        if self.limit_pkts:
            out += ["limit", str(self.limit_pkts)]
        return out


def apply_cmd(intf: str, shape: Shape) -> str:
    return " ".join(["tc", "qdisc", "replace", "dev", intf, "root", "netem", *shape.args()])


def clear_cmd(intf: str) -> str:
    return f"tc qdisc del dev {intf} root"
