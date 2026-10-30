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

## Proposed mechanism: RTT-aware Selective Repeat window

Textbook Selective Repeat uses a window of `1 + 2a` frames (one round trip) and predicts efficiency `1 - p`. The simulator and
real UDP runs show it stays well below that under loss. We propose `N = 2(1 + 2a)` and compare it with the baseline over 10 seeds:

| Scenario | Baseline (mean ± SD) | Proposed (mean ± SD) | Improvement |
|---|---|---|---|
| S1, 1% loss | 0.909 ± 0.010 | 0.914 ± 0.008 | +0.6% |
| S2, 5% loss | 0.717 ± 0.016 | 0.776 ± 0.009 | +8.2% |
| S3, 20% loss | 0.478 ± 0.008 | 0.590 ± 0.005 | +23.5% |

Real UDP sockets give +0.1%, +7.4% and +24.6%. Reproduce with `uv run python -m experiments.phase2_sr_window --real`
(or live in the dashboard page "SR window: baseline vs proposed"). Limits: it does not reach the textbook `1 - p`, it gives
nothing on clean links, and it doubles the buffer. Details in the report.

## Project submission (Team 15, slot F1)

Team 15: Ishita Anant (24BCE0555), Aniket Bhayana (24BCE2989), Daksh Arora (24BCI0259). Course BCSE308P, Fall 2026-27.

| File | Content |
|---|---|
| `submission/F1_Team15_Report.pdf` (`.docx` also) | Project report (VTOP Assignment 8) |
| `submission/F1_Team15_PPT.pptx` | Presentation (VTOP Assignment 9) |
| `submission/F1_Team15_SourceCode.zip` | Complete source code |
| `submission/F1_Team15_Screenshots.zip`, `screenshots/` | Dashboard screenshots |
| `docs/phase1/PACKET_TRACER.md` | Step-by-step Packet Tracer lab (the `.pkt` file is added as `submission/F1_Team15_Simulation.pkt`) |
| `docs/TEST_RESULTS.md`, `results/` | Test output and every experiment's JSON / CSV / PNG |

### Software requirements

Linux or macOS, Python 3.10+ (tested on 3.14), [uv](https://docs.astral.sh/uv/). The real-network namespace test also needs `iproute2`
(`ip`, `tc`) and `unshare` with unprivileged user namespaces. The Mininet/FRR experiments need an Ubuntu VM (see `docs/SETUP.md`) and are optional.

### Installation and execution

```bash
git clone https://github.com/dakshcodez/netlab.git && cd netlab
uv sync --extra dashboard
make test            # expect: 94 passed
make sim             # all no-root experiments; writes results/<phase>/*.json|csv|png
uv run python -m experiments.phase2_sr_window --real      # baseline vs proposed (about 1 minute)
make e2e-netns       # expect: NETNS E2E PASSED
make dashboard       # http://localhost:8501, open "SR window: baseline vs proposed" and press Run
```

Expected results: the table above, `results/phase2/sr_window_novelty.png`, and the other plots described in `docs/REPORT.md`.

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
