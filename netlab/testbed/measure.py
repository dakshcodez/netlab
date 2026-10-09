"""Pure parsing/analysis helpers for testbed measurements (unit-testable without Mininet)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from netlab.testbed.frr import Timers

_PING_LINE = re.compile(r"^\[(\d+\.\d+)\].*icmp_seq=(\d+)", re.MULTILINE)


@dataclass(frozen=True)
class Outage:
    outage_s: float  # longest gap between consecutive replies, minus one interval
    lost: int  # replies missing over the whole run
    received: int
    gap_start: float | None  # timestamp of the last reply before the longest gap


def parse_ping(output: str, interval: float) -> Outage:
    """Parse `ping -D -i <interval>` output into the longest connectivity outage."""
    replies = [(float(t), int(seq)) for t, seq in _PING_LINE.findall(output)]
    if len(replies) < 2:
        return Outage(float("inf"), 0, len(replies), None)
    seqs = [s for _, s in replies]
    lost = (max(seqs) - min(seqs) + 1) - len(set(seqs))
    gap, start = max((b[0] - a[0], a[0]) for a, b in zip(replies, replies[1:]))
    return Outage(max(0.0, gap - interval), lost, len(replies), start)


def expected_outage(protocol: str, mode: str, timers: Timers = Timers()) -> tuple[float, float]:
    """Theoretical (min, max) outage in seconds after a link failure on the active path.

    - Carrier loss is detected immediately; recovery is bounded by SPF/triggered updates
      (OSPF) or by waiting for an alternative route to be advertised again (RIP).
    - A silent failure is only noticed when a timer expires: OSPF dead interval (minus up to
      one hello already elapsed), RIP route timeout plus up to one update period for a
      neighbour to re-advertise the alternative.
    """
    if mode == "down":
        if protocol == "ospf":
            return 0.0, 2.0
        return 0.0, float(timers.rip_update)
    if protocol == "ospf":
        return float(timers.ospf_dead - timers.ospf_hello), float(timers.ospf_dead + 2)
    return float(timers.rip_timeout - timers.rip_update), float(timers.rip_timeout + timers.rip_update)
