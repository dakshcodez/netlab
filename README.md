# NetLab — Network Performance Analyzer & Simulator

A computer networks project that studies each layer at three levels:

1. **Theory:** the textbook model (e.g. Stop-and-Wait efficiency = 1/(1+2a))
2. **Simulation:** our own Python implementation
3. **Reality:** real Linux networking in a Mininet testbed (FRR routers, `tc netem`, iperf3, Wireshark)

…and plots them together so we can explain where the models match reality and where they don't.

| Phase | Covers | Guide |
|---|---|---|
| 1 | Testbed, VLSM addressing, Packet Tracer, RIP vs OSPF, DV/LS simulator | [`docs/phase1`](docs/phase1/README.md) |
| 2 | Error detection (checksum, CRC, Hamming), ARQ (SW, GBN, SR) | [`docs/phase2`](docs/phase2/README.md) |
| 3 | DNS hierarchy, TCP congestion control, pcap analyzer, dashboard | [`docs/phase3`](docs/phase3/README.md) |

All three phases are integrated on `main`. Findings: [`docs/REPORT.md`](docs/REPORT.md).

- **New to the project? Start here:** [`docs/NetLab_Project_Guide.pdf`](docs/NetLab_Project_Guide.pdf), a plain-language guide to every phase
- Full plan, deliverables, status and workflow: [`docs/PLAN.md`](docs/PLAN.md)
- Environment setup: [`docs/SETUP.md`](docs/SETUP.md)

## Quick start

```bash
uv sync --extra dashboard
make test            # unit tests
make sim             # every experiment that runs without root: simulations + real-socket loopback runs
make dashboard       # interactive dashboard at http://localhost:8501
make e2e             # clean-clone end-to-end check: install, tests, all experiments, CLIs, dashboard
make e2e-netns       # ARQ + DNS across a real veth link with netem, in network namespaces (no root)
make testbed         # real-network experiments (Ubuntu testbed VM, as root; see docs/SETUP.md)
```

## Layout

```
netlab/          Python package (one subpackage per area)
  common/        shared results format and plot helpers
  addressing/ topology/ routing/ testbed/       Phase 1: VLSM, topologies, routing simulator, Mininet + FRR
  reliability/   Phase 2: detection codes, channel model, ARQ (simulated and over real UDP), theory
  dns/ tcp/ analyzer/ dashboard/                Phase 3: DNS, TCP simulator, pcap analyzer, dashboard backend
dashboard/       Streamlit app
experiments/     one runnable script per experiment
docs/            plan, setup, report, per-phase guides
tests/           unit tests for pure-Python logic
results/         generated experiment output (git-ignored)
```
