"""Packet-level simulation of TCP congestion control over one drop-tail bottleneck.

Model: senders → FIFO queue (``buffer_pkts`` packets, ``rate_pps`` service rate) → one-way delay
``rtt/2`` → receivers, with an uncongested ``rtt/2`` return path. Window units are packets
(MSS). Loss recovery is SACK-based (as in Linux): 3 duplicate ACKs trigger fast retransmit / fast
recovery, the sender then retransmits every packet the receiver reports missing, and a
retransmission timer (RTO) backs everything up.
ACKs carry the receiver's count of distinct packets received (what SACK would tell a sender),
which BBR uses for delivery-rate samples.

Congestion controllers: ``reno`` (slow start + AIMD), ``cubic`` (RFC 8312 window curve) and a
simplified ``bbr`` (model-based: bottleneck-bandwidth and min-RTT estimates, pacing).
"""

from __future__ import annotations

import heapq
import itertools
import random
from collections import deque
from dataclasses import dataclass, field

MSS_BYTES = 1448
RWND = 1000  # receiver window in packets (~1.4 MB): bounds how far snd_nxt can run ahead of snd_una
INF = float("inf")


# --- congestion controllers -----------------------------------------------------------

class Controller:
    name = "base"
    sack = False  # True: the sender subtracts SACKed packets from its in-flight count

    def __init__(self) -> None:
        self.cwnd = 10.0  # initial window (RFC 6928)
        self.ssthresh = INF
        self.pacing_pps: float | None = None

    def on_ack(self, now: float, acked: int, rtt: float | None, rate: float | None, flow: "Flow") -> None: ...
    def on_loss(self, now: float, inflight: int) -> None: ...  # entering fast recovery
    def on_recovery_exit(self) -> None: ...
    def on_rto(self, now: float, inflight: int) -> None: ...


class Reno(Controller):
    name = "reno"
    sack = True  # Linux enables SACK by default; recovery retransmits exactly the missing packets

    def on_ack(self, now, acked, rtt, rate, flow) -> None:
        for _ in range(acked):
            if self.cwnd < self.ssthresh:
                self.cwnd += 1.0
            else:
                self.cwnd += 1.0 / self.cwnd

    def on_loss(self, now, inflight) -> None:
        self.ssthresh = max(inflight / 2, 2.0)
        self.cwnd = self.ssthresh

    def on_recovery_exit(self) -> None:
        self.cwnd = self.ssthresh

    def on_rto(self, now, inflight) -> None:
        self.ssthresh = max(inflight / 2, 2.0)
        self.cwnd = 1.0


class Cubic(Reno):
    name = "cubic"
    C, BETA = 0.4, 0.7

    def __init__(self) -> None:
        super().__init__()
        self.w_max = 0.0
        self.epoch: float | None = None
        self.k = 0.0

    def on_ack(self, now, acked, rtt, rate, flow) -> None:
        for _ in range(acked):
            if self.cwnd < self.ssthresh:
                self.cwnd += 1.0
                continue
            if self.epoch is None:
                self.epoch = now
                self.k = ((self.w_max - self.cwnd) / self.C) ** (1 / 3) if self.w_max > self.cwnd else 0.0
                if self.w_max < self.cwnd:
                    self.w_max = self.cwnd
            t = now - self.epoch + (rtt or 0.0)
            target = self.C * (t - self.k) ** 3 + self.w_max
            # TCP-friendly region: never grow slower than Reno would
            reno_est = self.w_max * self.BETA + 3 * (1 - self.BETA) / (1 + self.BETA) * (t / (rtt or 0.1))
            target = max(target, reno_est)
            self.cwnd += (target - self.cwnd) / self.cwnd if target > self.cwnd else 0.01 / self.cwnd

    def _reduce(self) -> None:
        self.w_max = self.cwnd
        self.epoch = None

    def on_loss(self, now, inflight) -> None:
        self._reduce()
        self.ssthresh = max(self.cwnd * self.BETA, 2.0)
        self.cwnd = self.ssthresh

    def on_rto(self, now, inflight) -> None:
        self._reduce()
        self.ssthresh = max(self.cwnd * self.BETA, 2.0)
        self.cwnd = 1.0


class Bbr(Controller):
    """BBRv1-style: STARTUP → DRAIN → PROBE_BW (gain cycle), with a 10-round max filter on the
    delivery rate and a min filter on RTT. Loss does not reduce the sending rate."""

    name = "bbr"
    sack = True
    STARTUP_GAIN = 2.885
    CYCLE = (1.25, 0.75, 1, 1, 1, 1, 1, 1)

    def __init__(self) -> None:
        super().__init__()
        self.btl_bw = 0.0  # packets/s
        self.bw_samples: deque[tuple[float, float]] = deque()
        self.min_rtt = INF
        self.state = "startup"
        self.full_bw = 0.0
        self.full_count = 0
        self.cycle_idx = 0
        self.cycle_start = 0.0
        self.last_round_bw_check = 0.0

    def _bdp(self) -> float:
        return self.btl_bw * self.min_rtt if self.min_rtt < INF else 10.0

    def on_ack(self, now, acked, rtt, rate, flow) -> None:
        if rtt is not None:
            self.min_rtt = min(self.min_rtt, rtt)
        if rate is not None:
            self.bw_samples.append((now, rate))
            horizon = 10 * (self.min_rtt if self.min_rtt < INF else 0.1)
            while self.bw_samples and self.bw_samples[0][0] < now - horizon:
                self.bw_samples.popleft()
            self.btl_bw = max(r for _, r in self.bw_samples)
        if self.btl_bw <= 0 or self.min_rtt == INF:
            self.cwnd += acked
            return
        if self.state == "startup":
            # leave startup once bandwidth stops growing by 25% for 3 consecutive rounds
            if now - self.last_round_bw_check >= self.min_rtt:
                self.last_round_bw_check = now
                if self.btl_bw >= self.full_bw * 1.25:
                    self.full_bw, self.full_count = self.btl_bw, 0
                else:
                    self.full_count += 1
                    if self.full_count >= 3:
                        self.state = "drain"
            gain = self.STARTUP_GAIN
        elif self.state == "drain":
            gain = 1 / self.STARTUP_GAIN
            if flow.inflight <= self._bdp():
                self.state, self.cycle_start = "probe_bw", now
        else:
            if now - self.cycle_start >= self.min_rtt:
                self.cycle_idx = (self.cycle_idx + 1) % len(self.CYCLE)
                self.cycle_start = now
            gain = self.CYCLE[self.cycle_idx]
        self.pacing_pps = gain * self.btl_bw
        cwnd_gain = self.STARTUP_GAIN if self.state == "startup" else 2.0
        self.cwnd = max(4.0, cwnd_gain * self._bdp())

    def on_loss(self, now, inflight) -> None:
        pass

    def on_recovery_exit(self) -> None:
        pass

    def on_rto(self, now, inflight) -> None:
        self.cwnd = max(4.0, self.cwnd / 2)


CONTROLLERS = {"reno": Reno, "cubic": Cubic, "bbr": Bbr}


# --- simulator ------------------------------------------------------------------------

@dataclass
class Flow:
    name: str
    cc: Controller
    start: float = 0.0
    snd_una: int = 0
    snd_nxt: int = 0
    dupacks: int = 0
    in_recovery: bool = False
    recover: int = 0
    srtt: float | None = None
    rttvar: float = 0.0
    rto: float = 1.0
    rto_gen: int = 0
    next_send: float = 0.0  # pacing
    send_pending: bool = False
    delivered: int = 0
    delivered_time: float = 0.0
    sent_info: dict = field(default_factory=dict)  # seq -> (send time, delivered, delivered_time, retransmitted)
    rcv_next: int = 0
    rcv_ooo: set = field(default_factory=set)
    retx_done: dict = field(default_factory=dict)  # hole -> time of its last retransmission (SACK flows)
    loss_mark: int = 0  # after an RTO: everything below this and un-SACKed is presumed lost
    sack_set: frozenset = frozenset()  # SACK blocks as of the last ACK (SACK flows)
    sacked: int = 0  # packets the receiver holds above the cumulative ACK point (sender's view)
    rcv_total: int = 0  # distinct packets that reached the receiver (what SACK would report)
    acked_total: int = 0
    retransmissions: int = 0
    timeouts: int = 0
    trace: list = field(default_factory=list)  # (t, cwnd, inflight, srtt)
    rtt_samples: list = field(default_factory=list)  # (t, rtt)
    ack_events: list = field(default_factory=list)  # (t, packets newly acknowledged)
    _last_trace: float = -1.0

    @property
    def inflight(self) -> int:
        """Packets believed to be in the network (RFC 6675 "pipe" for SACK flows: SACKed packets
        have left the network, un-SACKed holes below the highest SACK are presumed lost, and
        retransmissions of those holes are back in flight)."""
        base = self.snd_nxt - self.snd_una
        if not self.cc.sack:
            return base
        pipe = base - self.sacked
        if self.in_recovery and (self.sack_set or self.loss_mark):
            top = max(max(self.sack_set, default=0), self.loss_mark)
            lost = [q for q in range(self.snd_una, top) if q not in self.sack_set]
            pipe += sum(1 for q in lost if q in self.retx_done) - len(lost)
        return max(0, pipe)


@dataclass
class SimResult:
    duration: float
    rate_pps: float
    rtt: float
    buffer_pkts: int
    flows: list[Flow]
    queue_trace: list[tuple[float, int]]
    drops: int

    def throughput_mbps(self, flow: Flow, t0: float = 0.0, t1: float | None = None) -> float:
        t1 = self.duration if t1 is None else t1
        pkts = sum(n for t, n in flow.ack_events if t0 <= t < t1)
        return pkts * MSS_BYTES * 8 / (t1 - t0) / 1e6

    def mean_rtt_ms(self, flow: Flow, t0: float = 0.0) -> float:
        s = [r for t, r in flow.rtt_samples if t >= t0]
        return 1000 * sum(s) / len(s) if s else 0.0


def jain(values: list[float]) -> float:
    """Jain's fairness index: 1/n (one flow hogs everything) … 1 (perfectly equal)."""
    if not values or sum(values) == 0:
        return 0.0
    return sum(values) ** 2 / (len(values) * sum(v * v for v in values))


def simulate(ccs: list[str], bandwidth_mbps: float = 10, rtt_ms: float = 40, buffer_pkts: int = 50,
             duration: float = 30, starts: list[float] | None = None, random_loss: float = 0.0,
             seed: int = 1, trace_every: float = 0.01, capture: list | None = None) -> SimResult:
    """``capture``, if given, receives ``(time, 'data'|'ack', flow_index, seq_or_ack)`` tuples as seen at the senders."""
    rng = random.Random(seed)
    rate = bandwidth_mbps * 1e6 / (MSS_BYTES * 8)  # packets per second
    service = 1 / rate
    half = rtt_ms / 2000
    flows = [Flow(f"{cc}-{i}", CONTROLLERS[cc](), (starts or [0.0] * len(ccs))[i]) for i, cc in enumerate(ccs)]
    events: list = []
    counter = itertools.count()
    queue: deque[float] = deque()  # departure times of packets currently in the queue
    queue_trace: list[tuple[float, int]] = []
    drops = 0

    def push(t: float, kind: str, *args) -> None:
        heapq.heappush(events, (t, next(counter), kind, args))

    def transmit(f: Flow, seq: int, now: float, retransmit: bool) -> None:
        nonlocal drops
        f.sent_info[seq] = (now, f.delivered, f.delivered_time, retransmit)
        if capture is not None:
            capture.append((now, "data", flows.index(f), seq))
        if retransmit:
            f.retransmissions += 1
        while queue and queue[0] <= now:
            queue.popleft()
        if len(queue) >= buffer_pkts or rng.random() < random_loss:
            drops += 1
            queue_trace.append((now, len(queue)))
            return
        dep = max(queue[-1] if queue else now, now) + service
        queue.append(dep)
        queue_trace.append((now, len(queue)))
        push(dep + half, "deliver", f, seq)

    def arm_rto(f: Flow, now: float) -> None:
        f.rto_gen += 1
        if f.snd_nxt > f.snd_una:
            push(now + f.rto, "rto", f, f.rto_gen)

    def find_holes(f: Flow, now: float) -> list[int]:
        """SACK flows: un-SACKed packets below the highest SACKed one that have not been
        retransmitted, or whose retransmission is overdue (lost again)."""
        if not f.sack_set and not f.loss_mark:
            return []
        stale = 1.5 * (f.srtt or 0.2)
        top = max(max(f.sack_set, default=0), f.loss_mark)
        return [q for q in range(f.snd_una, top)
                if q not in f.sack_set and now - f.retx_done.get(q, -INF) > stale]

    def try_send(f: Flow, now: float) -> None:
        if now < f.start:
            return
        pipe = f.inflight
        holes: deque[int] | None = None
        while pipe < int(f.cc.cwnd):
            if f.cc.sack and f.in_recovery:
                if holes is None:
                    holes = deque(find_holes(f, now))
                if holes:
                    q = holes.popleft()
                    f.retx_done[q] = now
                    transmit(f, q, now, True)
                    pipe += 1
                    continue
            if f.snd_nxt - f.snd_una >= RWND:
                return
            if f.cc.pacing_pps:
                if now < f.next_send:
                    if not f.send_pending:
                        f.send_pending = True
                        push(f.next_send, "send", f)
                    return
                f.next_send = now + 1 / f.cc.pacing_pps
            if f.snd_nxt == f.snd_una:
                arm_rto(f, now)
            transmit(f, f.snd_nxt, now, False)
            f.snd_nxt += 1
            pipe += 1

    for f in flows:
        push(f.start, "send", f)

    while events:
        now, _, kind, args = heapq.heappop(events)
        if now > duration:
            break
        if kind == "send":
            (f,) = args
            f.send_pending = False
            try_send(f, now)
        elif kind == "deliver":
            f, seq = args
            if seq >= f.rcv_next and seq not in f.rcv_ooo:
                f.rcv_total += 1
            if seq == f.rcv_next:
                f.rcv_next += 1
                while f.rcv_next in f.rcv_ooo:
                    f.rcv_ooo.discard(f.rcv_next)
                    f.rcv_next += 1
            elif seq > f.rcv_next:
                f.rcv_ooo.add(seq)
            push(now + half, "ack", f, f.rcv_next, seq, f.rcv_total, frozenset(f.rcv_ooo) if f.cc.sack else len(f.rcv_ooo))
        elif kind == "ack":
            f, ack, trigger, rcv_total, sack = args
            if capture is not None:
                capture.append((now, "ack", flows.index(f), ack))
            if f.cc.sack:
                f.sack_set, f.sacked = sack, len(sack)
            on_ack(f, ack, trigger, rcv_total, now, transmit, arm_rto, try_send)
        elif kind == "rto":
            f, gen = args
            if gen != f.rto_gen or f.snd_nxt <= f.snd_una:
                continue
            f.timeouts += 1
            f.cc.on_rto(now, f.inflight)
            f.dupacks = 0
            f.retx_done.clear()
            f.in_recovery = f.cc.sack  # SACK flows: every un-SACKed packet counts as lost and is resent
            f.recover = f.snd_nxt
            f.loss_mark = f.snd_nxt if f.cc.sack else 0
            if not f.cc.sack:
                f.snd_nxt = f.snd_una + 1  # go back: resend from the oldest unacked packet
            f.rto = min(f.rto * 2, 60)
            transmit(f, f.snd_una, now, True)
            arm_rto(f, now)
        for f in flows:
            if now - f._last_trace >= trace_every:
                f._last_trace = now
                f.trace.append((now, f.cc.cwnd, f.inflight, f.srtt or 0.0))
    return SimResult(duration, rate, rtt_ms / 1000, buffer_pkts, flows, queue_trace, drops)


def on_ack(f: Flow, ack: int, trigger: int, rcv_total: int, now: float, transmit, arm_rto, try_send) -> None:
    rate = None
    if rcv_total > f.delivered:
        f.delivered = rcv_total
        f.delivered_time = now
    info = f.sent_info.get(trigger)
    if info is not None and not info[3]:  # delivery-rate sample from the packet that triggered this ACK
        sent, deliv, deliv_time, _ = info
        interval = max(now - deliv_time, now - sent)  # ack-side or send-side interval, whichever is longer
        if interval > 0:
            rate = (f.delivered - deliv) / interval
    if ack > f.snd_una:
        newly = ack - f.snd_una
        rtt = None
        last = f.sent_info.get(ack - 1)
        if last is not None and not last[3]:  # Karn's rule: never time a retransmitted packet
            rtt = now - last[0]
            f.srtt = rtt if f.srtt is None else 0.875 * f.srtt + 0.125 * rtt
            f.rttvar = rtt / 2 if f.rttvar == 0 else 0.75 * f.rttvar + 0.25 * abs(f.srtt - rtt)
            f.rto = max(0.2, f.srtt + 4 * f.rttvar)
            f.rtt_samples.append((now, rtt))
        for s in range(f.snd_una, ack):
            f.sent_info.pop(s, None)
        f.acked_total += newly
        f.ack_events.append((now, newly))
        f.snd_una = ack
        f.dupacks = 0
        if f.in_recovery:
            if ack >= f.recover:
                f.in_recovery = False
                f.loss_mark = 0
                f.retx_done.clear()
                f.cc.on_recovery_exit()
            elif not f.cc.sack:  # partial ACK: the next hole is lost too
                transmit(f, f.snd_una, now, True)
        else:
            f.cc.on_ack(now, newly, rtt, rate, f)
        arm_rto(f, now)
    elif ack == f.snd_una and f.snd_nxt > f.snd_una:
        f.dupacks += 1
        if f.dupacks == 3 and not f.in_recovery:
            f.in_recovery, f.recover = True, f.snd_nxt
            f.retx_done = {f.snd_una: now}
            f.cc.on_loss(now, f.inflight)
            transmit(f, f.snd_una, now, True)
        if rate is not None and isinstance(f.cc, Bbr):
            f.cc.on_ack(now, 0, None, rate, f)
    try_send(f, now)
