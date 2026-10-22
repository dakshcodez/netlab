"""Stop-and-Wait, Go-Back-N and Selective Repeat as transport-independent state machines.

A sender or receiver never touches a socket or a clock. The driver hands it frames and the
current time, and it returns frames to transmit through the ``tx`` callback. The same classes
run inside the discrete-event simulator (``sim.py``) over ``Channel`` and over real UDP
sockets (``udp.py``).

Frames are ``kind(1) | value(4) | payload | CRC-32(4)``. Corrupt frames fail the CRC and are
dropped silently, just like on a real link. Sequence numbers are 32-bit and never wrap, which
keeps the window logic readable; a real protocol would use modular arithmetic.

- DATA: ``value`` is the sequence number.
- ACK_CUM: ``value`` is the next sequence number the receiver expects (Go-Back-N, Stop-and-Wait).
- ACK_SEL: ``value`` is the single sequence number being acknowledged (Selective Repeat).
- FIN: sent a few times by the real-UDP sender when it is done, so the receiver can exit.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Callable

from netlab.reliability.detect import crc32

DATA, ACK_CUM, ACK_SEL, FIN = 0, 1, 2, 3
HEADER = struct.Struct(">BI")
OVERHEAD = HEADER.size + 4


def encode(kind: int, value: int, payload: bytes = b"") -> bytes:
    body = HEADER.pack(kind, value) + payload
    return body + crc32(body).to_bytes(4, "big")


def decode(frame: bytes) -> tuple[int, int, bytes] | None:
    """Return (kind, value, payload), or None if the frame is too short or fails its CRC."""
    if len(frame) < OVERHEAD:
        return None
    body, tag = frame[:-4], frame[-4:]
    if crc32(body) != int.from_bytes(tag, "big"):
        return None
    kind, value = HEADER.unpack_from(body)
    return kind, value, body[HEADER.size:]


def make_payload(seq: int, size: int) -> bytes:
    """Deterministic content so the receiver can check what was delivered."""
    seed = seq.to_bytes(4, "big")
    return (seed * (size // 4 + 1))[:size]


# A transmit callback sends one frame and returns the time its last bit left the sender.
Tx = Callable[[bytes], float]


@dataclass
class SenderStats:
    transmissions: int = 0
    retransmissions: int = 0
    timeouts: int = 0


class Sender:
    """Base class: sliding window of ``window`` unacknowledged frames.

    ``timeout`` is how long after a frame has been fully sent the sender waits for its ACK.
    """

    name = "base"

    def __init__(self, n_packets: int, window: int, timeout: float, tx: Tx, payload_size: int = 100) -> None:
        self.n = n_packets
        self.window = window
        self.timeout = timeout
        self.tx = tx
        self.payload_size = payload_size
        self.base = 0
        self.next_seq = 0
        self.sent_at: dict[int, float] = {}  # seq -> time its last transmission finished
        self.stats = SenderStats()

    @property
    def done(self) -> bool:
        return self.base >= self.n

    def _send(self, seq: int) -> None:
        retransmit = seq in self.sent_at
        finish = self.tx(encode(DATA, seq, make_payload(seq, self.payload_size)))
        self.sent_at[seq] = finish
        self.stats.transmissions += 1
        if retransmit:
            self.stats.retransmissions += 1

    def _fill_window(self) -> None:
        while self.next_seq < min(self.n, self.base + self.window):
            self._send(self.next_seq)
            self.next_seq += 1

    def start(self, now: float) -> None:
        self._fill_window()

    def on_frame(self, frame: bytes, now: float) -> None:
        raise NotImplementedError

    def next_deadline(self) -> float | None:
        raise NotImplementedError

    def on_timer(self, now: float) -> None:
        raise NotImplementedError


class GoBackNSender(Sender):
    name = "gbn"

    def on_frame(self, frame: bytes, now: float) -> None:
        parsed = decode(frame)
        if parsed is None or parsed[0] != ACK_CUM:
            return
        ack = min(parsed[1], self.next_seq)
        if ack > self.base:
            self.base = ack
            self._fill_window()

    def next_deadline(self) -> float | None:
        if self.base >= self.next_seq:
            return None
        return self.sent_at[self.base] + self.timeout

    def on_timer(self, now: float) -> None:
        deadline = self.next_deadline()
        if deadline is None or now < deadline:
            return
        self.stats.timeouts += 1
        for seq in range(self.base, self.next_seq):
            self._send(seq)


class StopAndWaitSender(GoBackNSender):
    """Go-Back-N with a window of one."""

    name = "sw"

    def __init__(self, n_packets: int, window: int, timeout: float, tx: Tx, payload_size: int = 100) -> None:
        super().__init__(n_packets, 1, timeout, tx, payload_size)


class SelectiveRepeatSender(Sender):
    name = "sr"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.acked: set[int] = set()

    def on_frame(self, frame: bytes, now: float) -> None:
        parsed = decode(frame)
        if parsed is None or parsed[0] != ACK_SEL:
            return
        seq = parsed[1]
        if self.base <= seq < self.next_seq:
            self.acked.add(seq)
            while self.base in self.acked:
                self.acked.discard(self.base)
                self.base += 1
            self._fill_window()

    def _pending(self) -> list[int]:
        return [s for s in range(self.base, self.next_seq) if s not in self.acked]

    def next_deadline(self) -> float | None:
        pending = self._pending()
        if not pending:
            return None
        return min(self.sent_at[s] for s in pending) + self.timeout

    def on_timer(self, now: float) -> None:
        for seq in self._pending():
            if self.sent_at[seq] + self.timeout <= now:
                self.stats.timeouts += 1
                self._send(seq)


class Receiver:
    """Cumulative-ACK receiver that discards out-of-order frames (Stop-and-Wait, Go-Back-N)."""

    def __init__(self, n_packets: int, tx: Tx, payload_size: int = 100) -> None:
        self.n = n_packets
        self.tx = tx
        self.payload_size = payload_size
        self.expected = 0
        self.delivered = 0
        self.corrupt_or_wrong = 0  # delivered payloads that did not match (should stay 0)
        self.discarded_out_of_order = 0

    @property
    def done(self) -> bool:
        return self.delivered >= self.n

    def _deliver(self, seq: int, payload: bytes) -> None:
        if payload != make_payload(seq, self.payload_size):
            self.corrupt_or_wrong += 1
        self.delivered += 1

    def on_frame(self, frame: bytes, now: float) -> None:
        parsed = decode(frame)
        if parsed is None or parsed[0] != DATA:
            return
        _, seq, payload = parsed
        if seq == self.expected:
            self._deliver(seq, payload)
            self.expected += 1
        elif seq > self.expected:
            self.discarded_out_of_order += 1
        self.tx(encode(ACK_CUM, self.expected))


class SelectiveRepeatReceiver(Receiver):
    """Buffers out-of-order frames inside its window and ACKs each frame individually."""

    def __init__(self, n_packets: int, tx: Tx, window: int, payload_size: int = 100) -> None:
        super().__init__(n_packets, tx, payload_size)
        self.window = window
        self.buffer: dict[int, bytes] = {}

    def on_frame(self, frame: bytes, now: float) -> None:
        parsed = decode(frame)
        if parsed is None or parsed[0] != DATA:
            return
        _, seq, payload = parsed
        if self.expected <= seq < self.expected + self.window:
            self.buffer.setdefault(seq, payload)
            while self.expected in self.buffer:
                self._deliver(self.expected, self.buffer.pop(self.expected))
                self.expected += 1
            self.tx(encode(ACK_SEL, seq))
        elif self.expected - self.window <= seq < self.expected:
            self.tx(encode(ACK_SEL, seq))  # our earlier ACK was lost; repeat it


PROTOCOLS = ("sw", "gbn", "sr")


def make_sender(protocol: str, n_packets: int, window: int, timeout: float, tx: Tx, payload_size: int = 100) -> Sender:
    cls = {"sw": StopAndWaitSender, "gbn": GoBackNSender, "sr": SelectiveRepeatSender}[protocol]
    return cls(n_packets, window, timeout, tx, payload_size)


def make_receiver(protocol: str, n_packets: int, window: int, tx: Tx, payload_size: int = 100) -> Receiver:
    if protocol == "sr":
        return SelectiveRepeatReceiver(n_packets, tx, window, payload_size)
    return Receiver(n_packets, tx, payload_size)
