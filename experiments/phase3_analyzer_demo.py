"""Validate the pcap analyzer against the TCP simulator's own ground truth.

The simulator logs every data packet and ACK as a sender-side capture; we write that out as a real
pcap file, run the analyzer on it and compare what it reports with what the simulator knows.
(For captures from the testbed, run ``python -m netlab.analyzer results/phase3/dns_latency.pcap``.)

    uv run python -m experiments.phase3_analyzer_demo
"""

from __future__ import annotations

import statistics

from netlab.analyzer import packets as pk
from netlab.analyzer.analyze import analyze_file
from netlab.analyzer.pcap import write_pcap
from netlab.common.results import RESULTS_DIR, Result
from netlab.tcp.sim import MSS_BYTES, simulate

CLIENT, SERVER = "10.0.0.2", "10.0.0.14"
BASE_TS = 1_700_000_000.0


def export(capture, rtt_s: float, path) -> None:
    isn_c, isn_s = 1000, 5000
    frames = [
        (BASE_TS - rtt_s, pk.tcp_frame(CLIENT, SERVER, 40000, 5201, isn_c, 0, pk.SYN)),
        (BASE_TS, pk.tcp_frame(SERVER, CLIENT, 5201, 40000, isn_s, isn_c + 1, pk.SYN | pk.ACK)),
        (BASE_TS, pk.tcp_frame(CLIENT, SERVER, 40000, 5201, isn_c + 1, isn_s + 1, pk.ACK)),
    ]
    for t, kind, _, n in capture:
        if kind == "data":
            frames.append((BASE_TS + t, pk.tcp_frame(CLIENT, SERVER, 40000, 5201, isn_c + 1 + n * MSS_BYTES,
                                                     isn_s + 1, pk.ACK, MSS_BYTES)))
        else:
            frames.append((BASE_TS + t, pk.tcp_frame(SERVER, CLIENT, 5201, 40000, isn_s + 1,
                                                     isn_c + 1 + n * MSS_BYTES, pk.ACK)))
    write_pcap(path, frames)


def main() -> None:
    result = Result(phase="phase3", experiment="analyzer_validation", level="sim",
                    params={"bandwidth_mbps": 10, "rtt_ms": 40, "buffer_pkts": 34})
    print(f"{'cc':<6} {'':<12} {'retrans':>8} {'RTT med ms':>11} {'Mbit/s':>8}")
    for cc in ("reno", "cubic", "bbr"):
        capture: list = []
        sim = simulate([cc], 10, 40, 34, 20, capture=capture)
        f = sim.flows[0]
        pcap = RESULTS_DIR / "phase3" / f"sim_{cc}.pcap"
        pcap.parent.mkdir(parents=True, exist_ok=True)
        export(capture, sim.rtt, pcap)
        flow = analyze_file(pcap)["tcp"][0]
        pcap.unlink()  # ~20 MB each; the analysis is what we keep
        truth = (f.retransmissions, statistics.median(r for _, r in f.rtt_samples) * 1000,
                 sum(n for _, n in f.ack_events) * MSS_BYTES * 8 / 20 / 1e6)
        seen = (flow["a_to_b"]["retransmissions"], flow["rtt_ms"]["median"], flow["a_to_b"]["throughput_mbps"])
        print(f"{cc:<6} {'simulator':<12} {truth[0]:>8} {truth[1]:>11.2f} {truth[2]:>8.2f}")
        print(f"{'':<6} {'analyzer':<12} {seen[0]:>8} {seen[1]:>11.2f} {seen[2]:>8.2f}")
        result.add(cc=cc, sim_retransmissions=truth[0], analyzer_retransmissions=seen[0],
                   sim_rtt_median_ms=round(truth[1], 2), analyzer_rtt_median_ms=seen[1],
                   sim_mbps=round(truth[2], 2), analyzer_mbps=seen[2],
                   analyzer_syn_to_synack_ms=flow["syn_to_synack_ms"])
    print(f"saved {result.save()}")


if __name__ == "__main__":
    main()
