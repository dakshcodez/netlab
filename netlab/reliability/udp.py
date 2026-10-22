"""Run the ARQ state machines over real UDP sockets in real time.

Where the impairment comes from:

- on the Mininet testbed it is Linux ``tc netem`` on the links (``experiments/phase2_arq_real.py``);
- on one machine (``run_loopback``) a small user-space ``Relay`` sits between sender and
  receiver and applies the same ``Channel`` model the simulator uses, so real sockets and real
  clocks can be tested without root.

The sender paces itself: it spaces frames by the serialization time of a link with ``rate_bps``,
so queues never build up inside the kernel and the timeout means what the theory says.

Command line, for running on testbed hosts::

    python3 -m netlab.reliability.udp recv --port 9000 --protocol gbn --n 200 --window 8
    python3 -m netlab.reliability.udp send --peer 10.0.0.2:9000 --protocol gbn --n 200 \
        --window 8 --rate-mbit 4 --timeout 0.025
"""

from __future__ import annotations

import argparse
import heapq
import itertools
import json
import select
import socket
import threading
import time

from netlab.reliability import arq
from netlab.reliability.channel import Channel
from netlab.reliability.sim import ArqRun

SELECT_SLICE = 0.05


def _wait_readable(sock: socket.socket, timeout: float) -> bool:
    return bool(select.select([sock], [], [], max(0.0, timeout))[0])


def run_receiver(sock: socket.socket, protocol: str, n_packets: int, window: int,
                 payload_size: int, idle_timeout: float = 5.0) -> arq.Receiver:
    """Receive until the sender says FIN (after we have everything) or the link goes idle."""
    peer: list[tuple[str, int] | None] = [None]
    receiver = arq.make_receiver(protocol, n_packets, window,
                                 lambda f: (sock.sendto(f, peer[0]), time.monotonic())[1] if peer[0] else 0.0,
                                 payload_size)
    last_rx = time.monotonic()
    while time.monotonic() - last_rx < idle_timeout:
        if not _wait_readable(sock, SELECT_SLICE):
            continue
        frame, addr = sock.recvfrom(65535)
        last_rx = time.monotonic()
        parsed = arq.decode(frame)
        if parsed is None:
            continue
        peer[0] = addr
        if parsed[0] == arq.FIN:
            if receiver.done:
                break
            continue
        receiver.on_frame(frame, last_rx)
    return receiver


def run_sender(sock: socket.socket, peer: tuple[str, int], protocol: str, n_packets: int,
               window: int, timeout: float, payload_size: int, rate_bps: float,
               max_seconds: float = 120.0) -> ArqRun:
    frame_bytes = arq.OVERHEAD + payload_size
    ser = frame_bytes * 8 / rate_bps
    outbox: list[tuple[float, int, bytes]] = []
    counter = itertools.count()
    link_free = [0.0]

    def tx(frame: bytes) -> float:
        start = max(time.monotonic(), link_free[0])
        link_free[0] = start + ser
        heapq.heappush(outbox, (start, next(counter), frame))
        return link_free[0]  # the time the frame has fully left the (virtual) link

    sender = arq.make_sender(protocol, n_packets, window, timeout, tx, payload_size)
    t0 = time.monotonic()
    sender.start(t0)
    finished = False
    while time.monotonic() - t0 < max_seconds:
        now = time.monotonic()
        while outbox and outbox[0][0] <= now:
            sock.sendto(heapq.heappop(outbox)[2], peer)
        if sender.done and not outbox:
            finished = True
            break
        wake = [SELECT_SLICE]
        if outbox:
            wake.append(outbox[0][0] - now)
        deadline = sender.next_deadline()
        if deadline is not None:
            wake.append(deadline - now)
        if _wait_readable(sock, min(wake)):
            frame, _ = sock.recvfrom(65535)
            sender.on_frame(frame, time.monotonic())
        elif deadline is not None and time.monotonic() >= deadline:
            sender.on_timer(time.monotonic())
    elapsed = time.monotonic() - t0
    for _ in range(3):
        sock.sendto(arq.encode(arq.FIN, 0), peer)
    s = sender.stats
    return ArqRun(protocol=protocol, n_packets=n_packets, delivered=sender.base, elapsed=elapsed,
                  transmissions=s.transmissions, retransmissions=s.retransmissions, timeouts=s.timeouts,
                  discarded_out_of_order=0, wrong_payloads=0, finished=finished, ideal_time=n_packets * ser)


class Relay(threading.Thread):
    """User-space stand-in for netem: forwards datagrams between one sender and one receiver,
    applying a ``Channel`` per direction (loss, delay, jitter, reorder, ...)."""

    def __init__(self, sock: socket.socket, receiver_addr: tuple[str, int], fwd: Channel, rev: Channel) -> None:
        super().__init__(daemon=True)
        self.sock, self.receiver_addr, self.fwd, self.rev = sock, receiver_addr, fwd, rev
        self.sender_addr: tuple[str, int] | None = None
        self.stop = threading.Event()
        self.queue: list[tuple[float, int, tuple[str, int], bytes]] = []
        self.counter = itertools.count()

    def run(self) -> None:
        while not self.stop.is_set():
            now = time.monotonic()
            while self.queue and self.queue[0][0] <= now:
                _, _, dst, frame = heapq.heappop(self.queue)
                self.sock.sendto(frame, dst)
            wait = SELECT_SLICE if not self.queue else min(SELECT_SLICE, self.queue[0][0] - now)
            if not _wait_readable(self.sock, wait):
                continue
            frame, src = self.sock.recvfrom(65535)
            now = time.monotonic()
            if src == self.receiver_addr:
                channel, dst = self.rev, self.sender_addr
            else:
                self.sender_addr = src
                channel, dst = self.fwd, self.receiver_addr
            if dst is None:
                continue
            _, copies = channel.send(frame, now)
            for arrival, copy in copies:
                heapq.heappush(self.queue, (arrival, next(self.counter), dst, copy))


def run_loopback(protocol: str, n_packets: int, window: int, timeout: float, rate_bps: float,
                 delay: float, loss: float = 0.0, payload_size: int = 1000, reorder: float = 0.0,
                 reorder_delay: float = 0.0, seed: int = 1) -> ArqRun:
    """Sender → Relay → receiver on 127.0.0.1, all in this process (three threads/sockets)."""
    sockets = [socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for _ in range(3)]
    for s in sockets:
        s.bind(("127.0.0.1", 0))
    send_sock, relay_sock, recv_sock = sockets
    relay = Relay(relay_sock, recv_sock.getsockname(),
                  Channel(delay=delay, loss=loss, reorder=reorder, reorder_delay=reorder_delay, seed=seed),
                  Channel(delay=delay, seed=seed + 1))
    got: dict[str, arq.Receiver] = {}
    rx = threading.Thread(target=lambda: got.update(r=run_receiver(recv_sock, protocol, n_packets, window,
                                                                   payload_size, idle_timeout=3.0)))
    relay.start()
    rx.start()
    try:
        run = run_sender(send_sock, relay_sock.getsockname(), protocol, n_packets, window, timeout,
                         payload_size, rate_bps)
        rx.join(timeout=5)
    finally:
        relay.stop.set()
        relay.join(timeout=1)
        for s in sockets:
            s.close()
    receiver = got.get("r")
    if receiver is not None:
        run.delivered = receiver.delivered
        run.discarded_out_of_order = receiver.discarded_out_of_order
        run.wrong_payloads = receiver.corrupt_or_wrong
        run.finished = run.finished and receiver.done
    return run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="role", required=True)
    for role in ("recv", "send"):
        p = sub.add_parser(role)
        p.add_argument("--protocol", choices=arq.PROTOCOLS, required=True)
        p.add_argument("--n", type=int, default=200)
        p.add_argument("--window", type=int, default=8)
        p.add_argument("--payload", type=int, default=1000)
    sub.choices["recv"].add_argument("--port", type=int, default=9000)
    sub.choices["recv"].add_argument("--idle", type=float, default=10.0)
    sub.choices["send"].add_argument("--peer", required=True, help="host:port")
    sub.choices["send"].add_argument("--rate-mbit", type=float, default=4.0)
    sub.choices["send"].add_argument("--timeout", type=float, required=True)
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if args.role == "recv":
        sock.bind(("0.0.0.0", args.port))
        r = run_receiver(sock, args.protocol, args.n, args.window, args.payload, args.idle)
        print(json.dumps({"delivered": r.delivered, "wrong_payloads": r.corrupt_or_wrong,
                          "discarded_out_of_order": r.discarded_out_of_order}))
    else:
        host, port = args.peer.rsplit(":", 1)
        sock.bind(("0.0.0.0", 0))
        run = run_sender(sock, (host, int(port)), args.protocol, args.n, args.window, args.timeout,
                         args.payload, args.rate_mbit * 1e6)
        print(json.dumps({**run.__dict__, "efficiency": run.efficiency}))


if __name__ == "__main__":
    main()
