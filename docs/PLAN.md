# NetLab — Phase Plan

Each phase maps to one review and one team member. All work lives on `main`.
Every topic is studied at three levels — **theory** (textbook formula), **simulation**
(our own Python implementation) and **reality** (real Linux networking inside a Mininet
testbed) — and the three are compared on the same plot.

| Phase | Guide | Review | Owner | Theme |
|---|---|---|---|---|
| 1 | [`docs/phase1`](phase1/README.md) | Review 1 | _member 1_ | Testbed foundation + network layer & routing |
| 2 | [`docs/phase2`](phase2/README.md) | Review 2 | _member 2_ | Reliable delivery: error detection + ARQ |
| 3 | [`docs/phase3`](phase3/README.md) | Review 3 | _member 3_ | DNS, TCP congestion control, analyzer, dashboard, **final integration** |

## Status

Everything is integrated on `main`.
"Run here" means verified on a development machine without root; "needs testbed" means the code is written
and its pure logic is unit-tested, but the experiment itself needs Mininet/FRR/iperf3 on the Ubuntu VM and
has **not been executed yet**.

| Item | State |
|---|---|
| 1.1 VLSM planner, 1.3 topology model, 1.5 routing simulator, 1.8 count-to-infinity | done, run here |
| 1.2 Packet Tracer lab | step-by-step guide done; the `.pkt` file has to be built in Packet Tracer |
| 1.4 Mininet testbed, 1.6 trap, 1.7 convergence, 1.9 validation | needs testbed |
| 2.1-2.4, 2.6 detection, injection, channel, theory | done, run here |
| 2.5, 2.7 ARQ and experiments | done; theory + simulation + real UDP sockets (loopback relay) run here |
| 2.8 ARQ on Mininet with netem | needs testbed (`experiments/phase2_arq_real.py`) |
| 3.1 DNS codec | done, run here |
| 3.2, 3.3 DNS hierarchy and latency | done; real UDP sockets on loopback run here; separate Mininet hosts + tcpdump need testbed |
| 3.4 security demo | defensive half only: weak vs hardened resolver settings and the guess-space comparison (no attack code) |
| 3.5, 3.6, 3.7 TCP experiments | simulator results run here; real Linux Reno/CUBIC/BBR, fairness, bufferbloat and the Reno overlay need testbed |
| 3.8 analyzer | done; validated against simulator ground truth |
| 3.9 dashboard | done |
| 3.10 final integration, report | `make all`; [`REPORT.md`](REPORT.md) |

## Workflow

Development happens on `main`; the former `phase1`/`phase2`/`phase3` branches were folded into it. Changes to `main` need approval from the repo owner (`.github/CODEOWNERS`), so use a short-lived
feature branch and a pull request for anything non-trivial.

Shared code in `netlab/common/` (results format, plot helpers) is used by every phase: keep its public
interface stable, and update the dashboard and report if you change the results format.

---

## Phase 1 — Testbed & Routing (Review 1)

**Goal:** a reproducible emulated network every phase reuses, and a measured comparison of
distance-vector (RIP) vs link-state (OSPF) routing.

### Deliverables
| # | Item | Level |
|---|---|---|
| 1.1 | **VLSM address planner** (`netlab/addressing`) — allocates subnets largest-first, used for both Packet Tracer and Mininet | sim |
| 1.2 | **Packet Tracer lab** — office topology with VLSM, DHCP, one VLAN, static routes, then RIP and OSPF (`docs/phase1/PACKET_TRACER.md` + `.pkt` file) | demo |
| 1.3 | **Topology model** (`netlab/topology`) — one description drives the simulator, Mininet and FRR configs | infra |
| 1.4 | **Mininet testbed** (`netlab/testbed`) — routers as Linux hosts, `tc netem` helpers, FRR config generation & daemon management | real |
| 1.5 | **Routing simulator** (`netlab/routing`) — Dijkstra link-state + Bellman-Ford distance-vector with split horizon / poison reverse | sim |
| 1.6 | **Experiment: trap topology** — a slow direct link vs a fast 3-hop path; RIP picks hops, OSPF picks bandwidth. Measured with iperf3 and traceroute | real |
| 1.7 | **Experiment: convergence** — fail a link (carrier loss vs silent loss) while pinging every 10 ms; measure outage per protocol | real |
| 1.8 | **Experiment: count-to-infinity** — DV simulator with/without split horizon & poison reverse; plot route cost per round | sim |
| 1.9 | **Validation** — simulator routing tables vs FRR's real tables for the same topology | sim vs real |

### Expected results
- Trap topology: RIP → ~1 Mbit/s via direct link; OSPF → ~100 Mbit/s via 3 hops.
- Convergence on carrier loss: both fast (interface-down triggers updates).
- Convergence on silent failure: OSPF ≈ dead interval (40 s default), RIP ≈ timeout (180 s default).
- Count-to-infinity: plain DV climbs to 16; poison reverse fixes the 2-node loop.

---

## Phase 2 — Reliable Delivery (Review 2)

**Goal:** implement error detection and ARQ from scratch and compare theory, simulation and
real UDP transfers over lossy testbed links.

### Deliverables
| # | Item | Level |
|---|---|---|
| 2.1 | **Error detection library** (`netlab/reliability/detect`) — parity, 2D parity, Internet checksum (RFC 1071), CRC-32 (table-driven, from scratch), Hamming(7,4) encode/decode/correct | sim |
| 2.2 | **Error injection** — random bit errors (BER), burst errors of length *b*, adversarial patterns (swapped 16-bit words) | sim |
| 2.3 | **Experiment: detection strength** — undetected-error rate per scheme vs burst length; show checksum's blind spots and CRC's burst guarantee | sim |
| 2.4 | **Channel model** — loss, corruption, delay, reordering, seeded RNG | sim |
| 2.5 | **ARQ protocols** — Stop-and-Wait, Go-Back-N, Selective Repeat; one implementation, two transports: simulated channel and real UDP sockets | sim + real |
| 2.6 | **Theory module** — efficiency formulas (`1/(1+2a)`, GBN and SR under loss *p*) | theory |
| 2.7 | **Experiments** — efficiency vs loss rate; GBN vs SR vs window size; timeout sensitivity; effect of reordering | all three |
| 2.8 | **Real mode on testbed** — ARQ over UDP between Mininet hosts with netem loss/delay (uses Phase 1 testbed) | real |

### Expected results
- Three-way plots where theory, simulation and real measurements agree closely, and
  an explanation of where they diverge (timer granularity, OS scheduling).
- SR beats GBN as loss × window grows; GBN suffers badly under reordering.

---

## Phase 3 — DNS, TCP, Analyzer & Final Integration (Review 3)

**Goal:** application- and transport-layer experiments, a pcap analyzer, an interactive
dashboard, and the final integrated project.

### Deliverables
| # | Item | Level |
|---|---|---|
| 3.1 | **DNS wire format codec** — header, question, A/NS/CNAME records, name compression | sim |
| 3.2 | **DNS hierarchy on testbed** — root → `.lab` TLD → authoritative servers on separate hosts + a recursive resolver with TTL caching and negative caching | real |
| 3.3 | **Experiment: DNS latency** — cold (4 hops) vs warm (cached) lookups, captured in Wireshark | real |
| 3.4 | **Security demo** — cache poisoning against a resolver with predictable transaction IDs, then the fix (random TXID + source port), entirely inside the isolated testbed | real |
| 3.5 | **TCP congestion control** — Reno vs CUBIC vs BBR over a netem bottleneck; cwnd traces via `ss -ti`; slow start, AIMD sawtooth, fast retransmit | real |
| 3.6 | **Fairness & bufferbloat** — two flows on one bottleneck (Jain's fairness index); latency under load with large buffers | real |
| 3.7 | **Reno model** — simple simulator overlaid on real Linux Reno cwnd traces | sim vs real |
| 3.8 | **Analyzer** (`netlab/analyzer`) — pcap → handshakes, RTT, retransmissions, dup-ACKs, throughput, DNS latency, RIP/OSPF packets | tool |
| 3.9 | **Dashboard** (Streamlit) — choose an experiment from any phase, set loss/delay/bandwidth, run, see live plots | integration |
| 3.10 | **Final integration** — merge phases 1–2, `make all` reproduces every plot, final report | integration |

The analyzer (3.8) and DNS codec (3.1) do not need the testbed and can start immediately.

---

## Stretch goals (any phase, only after must-haves)
- MAC layer: pure/slotted ALOHA and CSMA simulation vs `S = G·e^(-2G)`.
- OSPF multi-area; RIP timer tuning sweep.
- QUIC vs TCP under loss.

## Ground rules
- Every experiment writes results via `netlab.common.results` so the dashboard and report
  can read any phase's output.
- Every experiment is a script under `experiments/` that can be re-run unattended.
- Pure-Python logic gets unit tests (`pytest`); testbed experiments are run on the Ubuntu VM.
