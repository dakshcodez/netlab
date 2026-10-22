"""Textbook efficiency (link utilisation) of the ARQ protocols.

Notation (Stallings): ``a = propagation delay / frame transmission time``, ``p`` = probability a
data frame is lost, ``N`` = window size, ``K = 1 + 2a`` = frames that fit in one round trip.
Assumptions: ACKs are never lost, and the timeout equals the time an ACK needs to come back, so
a lost frame costs exactly one round trip. The simulator and the real runs are configured to match.
"""

from __future__ import annotations


def a_param(prop_delay: float, tx_time: float) -> float:
    return prop_delay / tx_time


def eff_stop_and_wait(a: float, p: float = 0.0) -> float:
    return (1 - p) / (1 + 2 * a)


def eff_go_back_n(a: float, p: float, n: int) -> float:
    k = 1 + 2 * a
    if n >= k:
        return (1 - p) / (1 + 2 * a * p)
    return n * (1 - p) / (k * (1 - p + n * p))


def eff_selective_repeat(a: float, p: float, n: int) -> float:
    k = 1 + 2 * a
    return (1 - p) if n >= k else n * (1 - p) / k


def efficiency(protocol: str, a: float, p: float, n: int) -> float:
    if protocol == "sw":
        return eff_stop_and_wait(a, p)
    if protocol == "gbn":
        return eff_go_back_n(a, p, n)
    if protocol == "sr":
        return eff_selective_repeat(a, p, n)
    raise ValueError(protocol)
