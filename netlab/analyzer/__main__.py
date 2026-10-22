"""Command line: ``python -m netlab.analyzer capture.pcap [--json]``."""

from __future__ import annotations

import argparse
import json

from netlab.analyzer.analyze import analyze_file


def render(report: dict) -> str:
    lines = [f"{report['file']}: {report['packets']} packets over {report['duration_s']:.3f} s  "
             f"{report['protocols']}"]
    for f in report["tcp"]:
        lines.append(f"\nTCP {f['flow']}  ({f['duration_s']:.3f} s{', closed' if f['closed'] else ''}"
                     f"{', RESET' if f['reset'] else ''})")
        if "syn_to_synack_ms" in f:
            lines.append(f"  handshake: SYN→SYN/ACK {f['syn_to_synack_ms']} ms"
                         + (f", SYN/ACK→ACK {f['synack_to_ack_ms']} ms" if "synack_to_ack_ms" in f else ""))
        for label in ("a_to_b", "b_to_a"):
            d = f[label]
            if d["payload_bytes"]:
                lines.append(f"  {label}: {d['payload_bytes']} B in {d['data_packets']} pkts, "
                             f"{d['throughput_mbps']} Mbit/s, {d['retransmissions']} retransmissions, "
                             f"{d['dup_acks']} dup-ACKs (seen from the receiver side)")
        if "rtt_ms" in f:
            r = f["rtt_ms"]
            lines.append(f"  RTT: min {r['min']} / median {r['median']} / max {r['max']} ms ({r['samples']} samples)")
    d = report["dns"]
    if d["queries_answered"] or d["queries_unanswered"]:
        lines.append(f"\nDNS: {d['queries_answered']} answered, {d['queries_unanswered']} unanswered; latency {d['latency_ms']}")
        for q in d["lookups"][:10]:
            lines.append(f"  {q['name']:<24} {q['type']:<5} rcode {q['rcode']} {q['latency_ms']} ms from {q['server']}")
    if report["rip"]["packets"]:
        lines.append(f"\nRIP: {report['rip']['packets']}, {report['rip']['routes_advertised']} routes from {report['rip']['routers']}")
    if report["ospf"]["packets"]:
        lines.append(f"\nOSPF: {report['ospf']['packets']}, routers {report['ospf']['router_ids']}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pcap")
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args()
    report = analyze_file(args.pcap)
    print(json.dumps(report, indent=2) if args.json else render(report))


if __name__ == "__main__":
    main()
