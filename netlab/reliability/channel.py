"""A seeded, one-directional channel model: serialization delay, propagation delay, jitter,
loss, corruption, duplication and reordering.

``send`` returns when the sender finished putting the frame on the wire and the list of
(arrival_time, frame) copies that reach the far end (empty when the frame is lost). It never
sleeps or schedules anything itself, so the discrete-event simulator and the real-UDP relay
can both drive it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from netlab.reliability.inject import exactly_k_errors


@dataclass
class Channel:
    delay: float = 0.0  # one-way propagation delay, seconds
    jitter: float = 0.0  # extra uniform(0, jitter) delay per frame
    loss: float = 0.0  # probability a frame is dropped
    corrupt: float = 0.0  # probability a (surviving) frame has bits flipped
    corrupt_bits: int = 1
    duplicate: float = 0.0
    reorder: float = 0.0  # probability a frame is held back by ``reorder_delay``
    reorder_delay: float = 0.0
    rate_bps: float | None = None  # None = infinitely fast (no serialization delay)
    seed: int = 0
    rng: random.Random = field(init=False, repr=False)
    free_at: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)

    def tx_time(self, nbytes: int) -> float:
        return nbytes * 8 / self.rate_bps if self.rate_bps else 0.0

    def send(self, frame: bytes, now: float) -> tuple[float, list[tuple[float, bytes]]]:
        start = max(now, self.free_at)
        finish = start + self.tx_time(len(frame))
        self.free_at = finish
        if self.rng.random() < self.loss:
            return finish, []
        copies = [frame]
        if self.rng.random() < self.duplicate:
            copies.append(frame)
        out = []
        for copy in copies:
            if self.rng.random() < self.corrupt:
                copy = exactly_k_errors(copy, min(self.corrupt_bits, len(copy) * 8), self.rng)
            arrival = finish + self.delay + self.rng.random() * self.jitter
            if self.rng.random() < self.reorder:
                arrival += self.reorder_delay
            out.append((arrival, copy))
        return finish, out
