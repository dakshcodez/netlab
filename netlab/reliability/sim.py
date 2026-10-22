"""Discrete-event simulation of an ARQ protocol over two ``Channel`` objects."""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass

from netlab.reliability import arq
from netlab.reliability.channel import Channel


@dataclass
class ArqRun:
    protocol: str
    n_packets: int
    delivered: int
    elapsed: float
    transmissions: int
    retransmissions: int
    timeouts: int
    discarded_out_of_order: int
    wrong_payloads: int
    finished: bool
    ideal_time: float  # time to send n_packets back to back with no loss

    @property
    def efficiency(self) -> float:
        """Fraction of the time the sender's link carried useful (first-copy) frames."""
        return self.ideal_time / self.elapsed if self.elapsed else 0.0


def simulate(protocol: str, n_packets: int, window: int, timeout: float, fwd: Channel, rev: Channel,
             payload_size: int = 100, max_time: float = 1e6) -> ArqRun:
    """Send ``n_packets`` frames sender → receiver and run until all are delivered in order.

    ``fwd`` carries data frames and should have a ``rate_bps`` so that frames take time to send.
    ``rev`` carries ACKs and normally has no rate.
    """
    events: list[tuple[float, int, str, bytes]] = []
    counter = itertools.count()
    now = 0.0

    def push(link: Channel, frame: bytes, to: str) -> float:
        finish, copies = link.send(frame, now)
        for arrival, copy in copies:
            heapq.heappush(events, (arrival, next(counter), to, copy))
        return finish

    sender = arq.make_sender(protocol, n_packets, window, timeout,
                             lambda f: push(fwd, f, "receiver"), payload_size)
    receiver = arq.make_receiver(protocol, n_packets, window,
                                 lambda f: push(rev, f, "sender"), payload_size)
    sender.start(now)
    finished_at = None

    while now < max_time:
        deadline = sender.next_deadline()
        if events and (deadline is None or events[0][0] <= deadline):
            now, _, to, frame = heapq.heappop(events)
            (receiver if to == "receiver" else sender).on_frame(frame, now)
        elif deadline is not None:
            now = max(now, deadline)
            sender.on_timer(now)
        else:
            break
        if sender.done and receiver.done:
            finished_at = now
            break

    frame_bytes = arq.OVERHEAD + payload_size
    ideal = n_packets * fwd.tx_time(frame_bytes)
    s = sender.stats
    return ArqRun(
        protocol=protocol, n_packets=n_packets, delivered=receiver.delivered,
        elapsed=finished_at if finished_at is not None else now, transmissions=s.transmissions,
        retransmissions=s.retransmissions, timeouts=s.timeouts,
        discarded_out_of_order=receiver.discarded_out_of_order,
        wrong_payloads=receiver.corrupt_or_wrong, finished=finished_at is not None, ideal_time=ideal,
    )


def standard_setup(a: float = 5.0, frame_bytes: int = 109, rate_bps: float = 1e6):
    """Channel parameters giving propagation/transmission ratio ``a`` for a given frame size.
    Returns (tx_time, one_way_delay, timeout) where timeout is exactly the ACK return time."""
    tx_time = frame_bytes * 8 / rate_bps
    delay = a * tx_time
    return tx_time, delay, 2 * delay + 1e-9
