# NetLab: findings

Every topic is studied at three levels: **theory** (the textbook formula), **simulation** (our own Python) and
**reality** (real networking). This report states what each level shows, and says plainly which results
come from where, because not everything could be run in the same environment.

## What was and was not run

| Level | Where it ran | Items |
|---|---|---|
| Unit tests | development machine | 93 tests across all phases (`make test`) |
| Simulation, theory | development machine | routing (Phase 1), detection codes, ARQ, TCP congestion control, analyzer validation |
| Real sockets, one machine | development machine, loopback | ARQ over real UDP; DNS hierarchy over real UDP (server replies delayed to stand in for distance) |
| Real Linux networking | **not run yet** | Mininet + FRR (RIP/OSPF experiments), ARQ with netem, DNS on separate hosts with tcpdump, Linux Reno/CUBIC/BBR with iperf3 + `ss -ti` |

The testbed experiments are written, share their logic with tested code, and are wired into `make testbed`, but they
need root, Mininet, FRR and iperf3 on the Ubuntu VM (`docs/SETUP.md`), which the development machine did not
have. Their result files and plots do not exist yet. Nothing below claims a measurement from them.

## Phase 1: routing

- **Count-to-infinity** (`results/phase1/count_to_infinity_*.png`). A plain distance-vector protocol counts to the
  infinity value of 16 in 15 rounds on both test graphs. Split horizon and poison reverse cut the *line* graph to
  2 rounds but leave the *triangle* at 15, because a loop through three routers is invisible to them. This is why
  RIP caps infinity at 16 and why link-state protocols do not have the problem.
- **Predicted paths** on the trap topology: RIP (hop count) takes the 1 Mbit/s direct link, OSPF (cost = reference
  bandwidth / bandwidth) takes the 3-hop 100 Mbit/s path, a 100x throughput gap that the testbed run is meant to
  confirm with traceroute and iperf3.

## Phase 2: reliable delivery

### Error detection (`results/phase2/detection_burst.png`)

64-byte messages, 20,000 trials per point at the default setting:

| Error | Parity | 2-D parity | Internet checksum | CRC-32 |
|---|---|---|---|---|
| single bit | caught | caught | caught | caught |
| 2-bit burst | misses 98.6% | caught | caught | caught |
| bursts of 3 to 64 bits | misses about 49% | misses at most 0.09% | at most 1 in 20,000 | none seen |
| two swapped 16-bit words | misses 100% | misses 24% | **misses 100%** | none seen |
| add to one word, subtract from another | misses 53% | misses 7% | **misses 100%** | none seen |

Parity is a coin flip once the burst is longer than 2 bits. The Internet checksum is excellent against random
bursts, but it is a sum, so *any* change that preserves the sum, such as reordering words, is invisible to it.
CRC-32 is guaranteed to catch every burst up to 32 bits (verified by a unit test) and caught every adversarial
edit. Hamming(7,4) corrects every single-bit error, and every double error is "corrected" to the wrong value, so
it must be paired with a detection code.

### ARQ (`results/phase2/arq_*.png`)

Theory and simulation agree closely where the theory's assumptions hold (loss on data frames only, timeout equal to
the ACK round trip). With a = 5 (a round trip holds 11 frames):

| loss | SW sim / theory / real UDP | GBN (N=8) sim / theory / real | SR (N=32) sim / theory / real |
|---|---|---|---|
| 0% | 0.091 / 0.091 / 0.096 | 0.726 / 0.727 / 0.738 | 0.997 / 1.00 / 0.941 |
| 5% | 0.086 / 0.086 / 0.092 | 0.530 / 0.512 / 0.560 | 0.803 / 0.950 / 0.822 |
| 20% | 0.073 / 0.073 / 0.072 | 0.257 / 0.242 / 0.252 | 0.654 / 0.800 / 0.563 |

- **Stop-and-Wait** wastes the link at any loss rate (efficiency about 1/(1+2a)), and the match is near exact.
- **Go-Back-N** follows its formula within a few percent, and collapses as loss grows because each loss resends a
  window.
- **Selective Repeat** falls below its `1-p` ideal. The reason is not a bug: the window cannot slide until the lost
  frame's retransmission is acknowledged, a timeout plus a round trip after the first copy, so the window must
  be about twice the round-trip capacity (2(1+2a), 22 frames here) to hide losses. The textbook formula omits this.
- **Reordering with zero loss** (`arq_reorder.png`): at 10% reordering Go-Back-N falls to 0.39 efficiency while
  Selective Repeat holds 0.91, and at 30% it is 0.19 against 0.77. GBN discards every early arrival.
- **Timeouts** (`arq_timeout.png`): shorter than the round trip, the sender retransmits frames that were not lost
  (efficiency drops sharply below 1.0x); longer, every real loss idles the link for longer.
- **Real UDP** (loopback relay, 2 ms frames) tracks simulation within a few percent. The differences come from
  timer granularity and OS scheduling, and the single noisy real run per point means the SR values wander by up to 0.1.

## Phase 3: DNS, TCP, analyzer

### DNS (`results/phase3/dns_latency.png`)

The hierarchy (root, `lab` TLD, `example.lab`) runs on real UDP sockets with each server 20 ms away and the resolver 2 ms from
the client. Median over 10 repeats:

| Lookup | Time | What happened |
|---|---|---|
| cold `www.example.lab` | 64 ms | client to resolver, then root, TLD and authoritative: 3 x 20 ms + 2 ms |
| same name again | 2.5 ms | answer cached |
| sibling `mail.example.lab` | 23 ms | delegations cached, only the authoritative server asked |
| NXDOMAIN, cold | 23 ms | one upstream query |
| NXDOMAIN again | 2.4 ms | negative cache (SOA minimum TTL) |

The cold lookup is 26x slower than a cached one, and the numbers match the hop arithmetic. Packet-capture analysis of
the same flow needs the testbed run (`tcpdump` on the resolver, then `python -m netlab.analyzer`).

**Resolver hardening** (deliverable 3.4, defensive half only). The resolver can run with sequential
transaction IDs and a fixed source port, or with random IDs and a fresh random source port per query.
An off-path party must guess 1 value (0 bits), 65,536 (16 bits) or about 4.2 billion (32 bits) respectively. The
repository deliberately contains no forged-packet or poisoning code.

### TCP congestion control (`results/phase3/tcp_*.png`, simulation)

10 Mbit/s bottleneck, 40 ms round trip, buffer = one bandwidth-delay product (34 packets), SACK-based recovery.

- **Window shape:** Reno and CUBIC show slow start, the AIMD sawtooth and fast retransmit; CUBIC's cubic growth
  flattens near the previous maximum. Both fill the link (about 10 Mbit/s) at the cost of a standing queue: mean RTT
  61 ms and 70 ms against a 40 ms floor. BBR also reaches 10 Mbit/s at 42.5 ms, because it paces at the estimated
  bottleneck rate instead of filling the buffer.
- **Bufferbloat:** with a loss-based sender, RTT grows with the buffer (Reno 44 ms with 10 packets, 61 ms at one BDP,
  219 ms with 400); BBR stays at about 42 ms from 34 packets up. Throughput is unchanged, so the extra buffer
  buys latency and no speed.
- **Random loss** (1%): Reno 2.9 and CUBIC 3.2 Mbit/s, close to the Mathis model `1.22 MSS/(RTT sqrt(p))`; BBR 9.97 Mbit/s,
  because it does not treat loss as congestion.
- **Fairness (Jain's index, 2 flows):** Reno vs Reno 1.00, BBR vs BBR 0.99, CUBIC vs CUBIC 0.92. Mixed pairs are
  unequal: CUBIC takes about 78% against Reno (0.76).
  **Caveat:** in this simulator BBR is nearly starved by loss-based flows (0.4 of 10 Mbit/s, index 0.54). The BBR model is
  simplified (no ProbeRTT, no loss response, simplified filters), real BBRv1 gets a larger share, and this
  particular result should not be quoted as a finding about BBR. The testbed run (`make testbed-phase3`) measures the real thing.

### Analyzer (`netlab/analyzer`, `results/phase3/analyzer_validation.json`)

The TCP simulator's sender-side capture was written out as a real pcap file and analyzed. The analyzer's
retransmission counts match the simulator's exactly (78, 166 and 68 for Reno, CUBIC and BBR), median RTT is within
1.2 ms and throughput within 0.02 Mbit/s. It also decodes DNS (query/response latency matching, unanswered queries) and
RIP/OSPF packet counts, covered by unit tests on hand-built frames. It has not yet seen a capture from the testbed.

## Limitations and open items

1. Run the testbed experiments (`make testbed`) on the Ubuntu VM and add their plots here; until then the "reality" level
   rests on loopback sockets for Phases 2 and 3 and on nothing for Phase 1.
2. The Packet Tracer `.pkt` file is not committed (guide only).
3. The BBR model is simplified (see above); do not use its fairness numbers.
4. Loopback "real" ARQ and DNS runs emulate distance in user space; they exercise real sockets and clocks, not a real link.
5. The TCP simulator uses a single drop-tail queue with an uncongested return path; no delayed ACKs, ECN or pacing for loss-based flows.
