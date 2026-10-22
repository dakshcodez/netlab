# Phase 3: DNS, TCP, Analyzer & Dashboard

Owner: _member 3_ · Full plan: [`../PLAN.md`](../PLAN.md) · Findings: [`../REPORT.md`](../REPORT.md)

## What's here

| Path | What it is |
|---|---|
| `netlab/dns/message.py` | DNS wire format (RFC 1035): header, question, A/NS/CNAME/SOA, name compression with loop-safe decoding |
| `netlab/dns/zone.py` | Authoritative server logic: answers, referrals with glue, NXDOMAIN/NODATA with SOA |
| `netlab/dns/resolver.py` | Recursive resolver: iterative walk, TTL cache, negative caching (RFC 2308), bailiwick checks, ID/port policies |
| `netlab/dns/server.py`, `client.py`, `local.py`, `hierarchy.py` | UDP servers, timing client, the whole root → `lab` → `example.lab` hierarchy on one machine or on testbed hosts |
| `netlab/dns/hardening.py` | Search-space arithmetic for resolver hardening |
| `netlab/tcp/sim.py` | Packet-level simulator: Reno, CUBIC and a simplified BBR over a drop-tail bottleneck |
| `netlab/tcp/trace.py` | `ss -ti` parser for real Linux cwnd traces |
| `netlab/analyzer/` | pcap reader, frame decoder and analyzer (`python -m netlab.analyzer file.pcap`) |
| `netlab/dashboard/`, `dashboard/app.py` | Streamlit dashboard |

## Experiments

| Script | Where | Deliverable |
|---|---|---|
| `experiments/phase3_dns_latency.py` | loopback by default (real UDP sockets, emulated distance); `--testbed` for Mininet hosts + tcpdump capture | 3.2, 3.3 |
| `experiments/phase3_dns_hardening.py` | anywhere | 3.4 (defence side: predictable vs random IDs and ports) |
| `experiments/phase3_tcp.py` | simulation; `--testbed` for iperf3 + `ss -ti` + netem on the dumbbell | 3.5, 3.6, 3.7 |
| `experiments/phase3_analyzer_demo.py` | anywhere | 3.8: analyzer output checked against simulator ground truth |
| `dashboard/app.py` | anywhere (testbed page needs root) | 3.9 |

```bash
make sim-phase3
make testbed-phase3            # on the testbed VM
make dashboard                 # http://localhost:8501
```

## Notes

- **3.4 security demo:** the project delivers the defensive half. The resolver can be run with weak settings
  (`--weak`: sequential transaction IDs, one fixed source port) or hardened settings (random ID, random
  source port per query), and `phase3_dns_hardening` quantifies how much an off-path party would have to guess
  in each (0, 16 and about 32 bits). No attack or packet-forging code is included in the repository.
- **TCP simulator vs reality:** Reno and CUBIC follow textbook window dynamics with SACK-based loss recovery (as Linux does).
  The BBR model is deliberately simple (no ProbeRTT, no loss/ECN response), so BBR-vs-loss-based fairness numbers
  from the simulator should be read as qualitative. The testbed run (`--testbed`) is the authority for BBR.
- **Analyzer scope:** classic pcap (not pcapng; convert with `editcap -F pcap`), IPv4, Ethernet / Linux cooked / raw IP.
