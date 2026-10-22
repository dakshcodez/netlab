# Phase 2: Reliable Delivery (error detection + ARQ)

Owner: _member 2_ · Full plan: [`../PLAN.md`](../PLAN.md) · Findings: [`../REPORT.md`](../REPORT.md)

## What's here

| Path | What it is |
|---|---|
| `netlab/reliability/detect.py` | Parity, 2-D parity, Internet checksum (RFC 1071), table-driven CRC-32, Hamming(7,4), all from scratch |
| `netlab/reliability/inject.py` | Random bit errors, bursts of length *b*, adversarial edits (swapped words, add/subtract) |
| `netlab/reliability/channel.py` | Seeded channel model: rate, delay, jitter, loss, corruption, duplication, reordering |
| `netlab/reliability/arq.py` | Stop-and-Wait, Go-Back-N and Selective Repeat as transport-independent state machines |
| `netlab/reliability/sim.py` | Discrete-event simulation of an ARQ protocol over two channels |
| `netlab/reliability/udp.py` | The *same* state machines over real UDP sockets in real time (plus a user-space relay for one-machine runs and a CLI for testbed hosts) |
| `netlab/reliability/theory.py` | Textbook efficiency formulas |

One implementation, two transports: `arq.py` never touches a clock or a socket, so the simulator and the
UDP runner exercise exactly the same protocol code.

## Experiments

| Script | Where | What it shows |
|---|---|---|
| `experiments/phase2_detection.py` | anywhere | Undetected-error rate vs burst length per scheme; adversarial edits; Hamming correction |
| `experiments/phase2_arq.py` | anywhere | Efficiency vs loss, vs window size, vs timeout, vs reordering. Theory + simulation, plus real UDP on loopback with `--real` |
| `experiments/phase2_arq_real.py` | testbed VM | ARQ between two Mininet hosts with `tc netem` delay and loss, against theory |

```bash
make sim-phase2                 # detection + ARQ (theory, simulation, real UDP via loopback)
make testbed-phase2             # on the testbed VM
```

## Model and its assumptions

`a = propagation delay / frame time` (so a round trip holds `1 + 2a` frames). Loss is applied to data frames only
and the timeout equals the ACK round-trip time, matching the textbook assumptions (Stallings). Run
`phase2_arq` with ACK loss to see the formulas become optimistic.

Where theory and measurement differ, and why (see `results/phase2/*.png`):

- **Selective Repeat needs a window of about 2(1+2a), not 1+2a.** The window cannot slide until the lost frame's
  retransmission is acknowledged, which is a timeout plus a round trip after the first copy. With a window of
  1+2a to 2(1+2a) SR stalls behind every loss and sits below the `1-p` line.
- **Real UDP is below simulation** by a few percent: timer granularity (`select` wakes up slightly late) and
  OS scheduling jitter. Larger frames make this smaller.
- **Go-Back-N under reordering** collapses even with zero loss: every early arrival is discarded and its
  ACK repeats, forcing a timeout and a window's worth of retransmissions. SR buffers the frame instead.
