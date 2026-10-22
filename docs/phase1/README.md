# Phase 1: Testbed & Routing (Review 1)

Owner: _member 1_ · Branch: `phase1` · Full plan: [`../PLAN.md`](../PLAN.md)

## What's here

| Path | What it is |
|---|---|
| `netlab/addressing/vlsm.py` | VLSM planner (largest first, aligned blocks) + CLI |
| `netlab/topology/` | Topology model (nodes, links, auto-addressing, OSPF costs) + named topologies |
| `netlab/routing/link_state.py` | Dijkstra with equal-cost next hops and a settle-order trace |
| `netlab/routing/distance_vector.py` | Synchronous Bellman-Ford DV with split horizon / poison reverse |
| `netlab/routing/tables.py` | Predicts the RIP/OSPF routing table of every router |
| `netlab/testbed/net.py` | Builds a topology in Mininet, runs FRR, fails links, measures |
| `netlab/testbed/frr.py` | FRR config generation and per-node daemon commands |
| `netlab/testbed/netem.py` | `tc netem` link shaping (shared with Phases 2–3) |
| `netlab/testbed/measure.py` | Ping outage parser, theoretical convergence bounds |
| `docs/phase1/PACKET_TRACER.md` | Step-by-step Packet Tracer lab |

## Experiments

| Script | Where | What it shows |
|---|---|---|
| `experiments/phase1_paths.py` | anywhere | Predicted RIP vs OSPF paths and tables, topology figure |
| `experiments/phase1_count_to_infinity.py` | anywhere | DV count-to-infinity; split horizon fixes the line graph but not the triangle |
| `experiments/phase1_trap.py` | testbed VM | Real path (traceroute) and throughput (iperf3) per protocol vs prediction |
| `experiments/phase1_convergence.py` | testbed VM | Outage after link failure: carrier loss vs silent failure, vs theory |
| `experiments/phase1_validate.py` | testbed VM | Simulator tables vs FRR tables, route by route |

```bash
# anywhere
make sim

# testbed VM
make testbed-phase1                       # all three real experiments
sudo PYTHONPATH=. python3 -m experiments.phase1_convergence --fast-timers   # quick run (~1 min)
```

Results are written to `results/phase1/` as JSON + CSV + PNG.

## Expected results

| Experiment | Expected |
|---|---|
| Trap | RIP: h1→r1→r4→h2 at ≈1 Mbit/s. OSPF: h1→r1→r2→r3→r4→h2 at ≈95 Mbit/s |
| Convergence (carrier loss) | OSPF ≲ 1 s. RIP up to ~30 s (waits for a neighbour's periodic update with the alternative route) |
| Convergence (silent) | OSPF ≈ 30–40 s (dead interval). RIP ≈ 150–210 s (route timeout + update period) |
| Count-to-infinity | Line: plain 15 rounds, split horizon 2. Triangle: 15 rounds even with split horizon / poison reverse |
| Validation | 100% of routes match (RIP ties: FRR picks one of the equal-cost next hops) |

## Key points for the review
1. **One topology description** drives the simulator, Mininet and the FRR configs, so the
   predictions and the real network are guaranteed to describe the same network.
2. **The metric decides the path:** hop count vs bandwidth cost. The trap topology makes the
   difference measurable as a ~100× throughput gap.
3. **Failure detection dominates convergence:** with carrier loss both protocols are fast.
   When the failure is silent, protocol timers decide, which is why OSPF's 40 s dead
   interval beats RIP's 180 s timeout (and why BFD exists in practice).
4. **Split horizon isn't a complete fix:** it breaks two-node loops, but loops through three
   or more routers still count to infinity. That's why RIP caps infinity at 16 and why
   link-state protocols avoid the problem entirely.

## Status / TODO for the owner
- [ ] Build the Packet Tracer lab and commit `docs/phase1/netlab.pkt` + screenshots
- [ ] Set up the Ubuntu VM ([`../SETUP.md`](../SETUP.md)) and run the three testbed experiments
- [ ] Check the results match the table above; investigate any mismatch
- [ ] Capture RIP and OSPF packets in Wireshark on a router interface for the report
- [ ] Optional: Dijkstra step-by-step animation from `SPF.order`
