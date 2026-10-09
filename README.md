# NetLab — Network Performance Analyzer & Simulator

A computer networks project that studies each layer at three levels:

1. **Theory:** the textbook model (e.g. Stop-and-Wait efficiency = 1/(1+2a))
2. **Simulation:** our own Python implementation
3. **Reality:** real Linux networking in a Mininet testbed (FRR routers, `tc netem`, iperf3, Wireshark)

…and plots them together so we can explain where the models match reality and where they don't.

| Phase | Branch | Covers |
|---|---|---|
| 1 | [`phase1`](../../tree/phase1) | Testbed, VLSM addressing, Packet Tracer, RIP vs OSPF, DV/LS simulator |
| 2 | [`phase2`](../../tree/phase2) | Error detection (checksum, CRC, Hamming), ARQ (SW, GBN, SR) |
| 3 | [`phase3`](../../tree/phase3) | DNS hierarchy, TCP congestion control, pcap analyzer, dashboard, **final version** |

- Full plan, deliverables and branch workflow: [`docs/PLAN.md`](docs/PLAN.md)
- Environment setup: [`docs/SETUP.md`](docs/SETUP.md)

## Quick start

```bash
uv sync
uv run pytest
```

## Layout

```
netlab/          Python package (one subpackage per area)
  common/        shared results format (change only on main)
experiments/     one runnable script per experiment
docs/            plan, setup, per-phase guides
tests/           unit tests for pure-Python logic
results/         generated experiment output (git-ignored)
```
