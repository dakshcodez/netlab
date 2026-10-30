# Test results

Generated 2026-10-29 on Linux 7.2.5-3-omarchy, Python 3.14.7.

## Unit tests (`make test`)

```
........................................................................ [ 76%]
......................                                                   [100%]
94 passed in 5.15s
```

## Network-namespace test (`make e2e-netns`)

```
PYTHON=/home/daksh/Projects/cn_proj/.venv/bin/python scripts/netns_e2e.sh
3 packets transmitted, 2 received, 33.3333% packet loss, time 404ms
rtt min/avg/max/mdev = 20.032/20.039/20.047/0.007 ms
  ok   link up, ping through netem
  ok   ARQ sw over veth+netem: 60/60 delivered, efficiency 0.080, retransmissions 6
  ok   ARQ gbn over veth+netem: 60/60 delivered, efficiency 0.868, retransmissions 0
  ok   ARQ sr over veth+netem: 60/60 delivered, efficiency 0.413, retransmissions 6
  ok   DNS across netns: [...]
NETNS E2E PASSED
```

## Proposed vs baseline Selective Repeat (`uv run python -m experiments.phase2_sr_window --real`)

Efficiency, mean ± SD over 10 runs, a = 5, baseline window 11, proposed window 22.

| Scenario | Level | Baseline | Proposed | Improvement |
|---|---|---|---|---|
| S1 (1% loss) | simulation | 0.909 ± 0.010 | 0.914 ± 0.008 | +0.6% |
| S2 (5% loss) | simulation | 0.717 ± 0.016 | 0.776 ± 0.009 | +8.2% |
| S3 (20% loss) | simulation | 0.478 ± 0.008 | 0.590 ± 0.005 | +23.5% |
| S1 (1% loss) | real UDP | 0.871 ± 0.049 | 0.872 ± 0.049 | +0.1% |
| S2 (5% loss) | real UDP | 0.702 ± 0.062 | 0.754 ± 0.061 | +7.4% |
| S3 (20% loss) | real UDP | 0.443 ± 0.039 | 0.552 ± 0.048 | +24.6% |

Raw data: `results/phase2/sr_window_novelty.json`, `sr_window_vs_a.json`, `sr_window_real.json`.

Not run: Mininet + FRR and iperf3 experiments (`make testbed`); see `docs/REPORT.md`.
