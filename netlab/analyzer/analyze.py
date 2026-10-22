"""Turn a capture into numbers: TCP handshakes, RTT, retransmissions, dup-ACKs, throughput,
DNS latency, and RIP / OSPF control traffic."""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from netlab.analyzer import packets
from netlab.analyzer.packets import ACK, FIN, RST, SYN, Packet
from netlab.analyzer.pcap import read_pcap
from netlab.dns import message as dns

OSPF_TYPES = {1: "Hello", 2: "DB Description", 3: "LS Request", 4: "LS Update", 5: "LS Ack"}
RIP_COMMANDS = {1: "Request", 2: "Response"}


@dataclass
class Direction:
    """One direction of a TCP connection."""

    first_seq: int | None = None
    highest_end: int = 0  # relative sequence number after the last new byte seen
    data_packets: int = 0
    retransmissions: int = 0
    retransmitted_bytes: int = 0
    pure_acks: int = 0
    dup_acks: int = 0
    last_ack: int | None = None
    last_window: int | None = None
    first_ts: float | None = None
    last_ts: float | None = None
    pending: dict[int, tuple[float, bool]] = field(default_factory=dict)  # expected ack → (time, retransmitted)


@dataclass
class TcpFlow:
    a: tuple[str, int]  # the endpoint that sent the first packet we saw (or the SYN)
    b: tuple[str, int]
    dirs: dict[str, Direction] = field(default_factory=lambda: {"a": Direction(), "b": Direction()})
    syn_ts: float | None = None
    synack_ts: float | None = None
    handshake_ack_ts: float | None = None
    rtt_samples: list[tuple[float, float]] = field(default_factory=list)  # (time, rtt) for data a→b or b→a
    start: float = 0.0
    end: float = 0.0
    fin: bool = False
    rst: bool = False

    def key(self) -> str:
        return f"{self.a[0]}:{self.a[1]} → {self.b[0]}:{self.b[1]}"


def _tcp_flows(pkts: list[Packet]) -> list[TcpFlow]:
    flows: dict[frozenset, TcpFlow] = {}
    for p in pkts:
        if p.proto != 6:
            continue
        ends = ((p.src, p.sport), (p.dst, p.dport))
        k = frozenset(ends)
        flow = flows.get(k)
        if flow is None:
            flow = flows[k] = TcpFlow(a=ends[0], b=ends[1], start=p.ts)
        flow.end = p.ts
        side, other = ("a", "b") if ends[0] == flow.a else ("b", "a")
        d, rev = flow.dirs[side], flow.dirs[other]
        d.first_ts = p.ts if d.first_ts is None else d.first_ts
        d.last_ts = p.ts
        if p.flags & RST:
            flow.rst = True
        if p.flags & FIN:
            flow.fin = True
        if p.flags & SYN:
            if not p.flags & ACK:
                flow.syn_ts = p.ts
                if ends[0] != flow.a:  # the SYN came from the endpoint we labelled b: swap labels
                    flow.a, flow.b = flow.b, flow.a
                    flow.dirs["a"], flow.dirs["b"] = flow.dirs["b"], flow.dirs["a"]
                    side, d = "a", flow.dirs["a"]
            else:
                flow.synack_ts = p.ts
            d.first_seq = p.seq
            d.highest_end = 1  # the SYN consumes one sequence number
            continue
        if d.first_seq is None:
            d.first_seq = p.seq  # capture started mid-connection
        rel = (p.seq - d.first_seq) & 0xFFFFFFFF
        n = p.payload_len
        if n:
            d.data_packets += 1
            end = rel + n
            if rel < d.highest_end:  # bytes we have already seen: a retransmission
                d.retransmissions += 1
                d.retransmitted_bytes += min(n, d.highest_end - rel)
                if end in d.pending:
                    d.pending[end] = (d.pending[end][0], True)
            else:
                d.pending[end] = (p.ts, False)
            d.highest_end = max(d.highest_end, end)
        elif p.flags & ACK and not p.flags & (FIN | RST):
            d.pure_acks += 1
            if d.last_ack == p.ack and d.last_window == p.window and rev.highest_end > 1:
                d.dup_acks += 1
        if p.flags & ACK:
            if flow.synack_ts is not None and flow.handshake_ack_ts is None and side == "a" and not n:
                flow.handshake_ack_ts = p.ts
            d.last_ack, d.last_window = p.ack, p.window
            if rev.first_seq is not None:
                acked = (p.ack - rev.first_seq) & 0xFFFFFFFF
                for expected in sorted(e for e in rev.pending if e <= acked):
                    sent, retx = rev.pending.pop(expected)
                    if not retx:  # Karn: no RTT from retransmitted data
                        flow.rtt_samples.append((p.ts, p.ts - sent))
    return list(flows.values())


def _tcp_summary(flow: TcpFlow) -> dict:
    out: dict = {"flow": flow.key(), "duration_s": round(flow.end - flow.start, 6),
                 "closed": flow.fin, "reset": flow.rst}
    if flow.syn_ts is not None and flow.synack_ts is not None:
        out["syn_to_synack_ms"] = round((flow.synack_ts - flow.syn_ts) * 1000, 3)
    if flow.synack_ts is not None and flow.handshake_ack_ts is not None:
        out["synack_to_ack_ms"] = round((flow.handshake_ack_ts - flow.synack_ts) * 1000, 3)
    for name, d in flow.dirs.items():
        label = "a_to_b" if name == "a" else "b_to_a"
        nbytes = max(0, d.highest_end - 1) if d.first_seq is not None else 0
        span = (d.last_ts - d.first_ts) if d.first_ts is not None and d.last_ts is not None else 0
        out[label] = {"payload_bytes": nbytes, "data_packets": d.data_packets,
                      "retransmissions": d.retransmissions, "retransmitted_bytes": d.retransmitted_bytes,
                      "dup_acks": d.dup_acks,
                      "throughput_mbps": round(nbytes * 8 / span / 1e6, 4) if span > 0 and nbytes else 0.0}
    if flow.rtt_samples:
        rtts = [r for _, r in flow.rtt_samples]
        out["rtt_ms"] = {"samples": len(rtts), "min": round(min(rtts) * 1000, 3),
                         "median": round(statistics.median(rtts) * 1000, 3),
                         "max": round(max(rtts) * 1000, 3)}
    return out


def _dns(pkts: list[Packet]) -> dict:
    queries: dict[tuple, tuple[float, str, int]] = {}
    answered, latencies = [], []
    for p in pkts:
        if p.proto != 17 or 53 not in (p.sport, p.dport) or not p.payload:
            continue
        try:
            msg = dns.Message.decode(p.payload)
        except dns.DnsError:
            continue
        if not msg.questions:
            continue
        q = msg.questions[0]
        if not msg.is_response:
            queries[(p.src, p.sport, p.dst, msg.id)] = (p.ts, q.name, q.qtype)
        else:
            sent = queries.pop((p.dst, p.dport, p.src, msg.id), None)
            if sent is not None:
                ms = (p.ts - sent[0]) * 1000
                latencies.append(ms)
                answered.append({"name": q.name, "type": dns.TYPE_NAMES.get(q.qtype, q.qtype),
                                 "server": p.src, "rcode": msg.rcode, "answers": len(msg.answers),
                                 "latency_ms": round(ms, 3)})
    return {"queries_answered": len(answered), "queries_unanswered": len(queries),
            "latency_ms": {"min": round(min(latencies), 3), "median": round(statistics.median(latencies), 3),
                           "max": round(max(latencies), 3)} if latencies else None,
            "lookups": answered}


def _rip(pkts: list[Packet]) -> dict:
    cmds, routes, senders = Counter(), 0, set()
    for p in pkts:
        if p.proto == 17 and p.dport == 520 and p.sport == 520 and len(p.payload) >= 4:
            cmd = p.payload[0]
            cmds[RIP_COMMANDS.get(cmd, str(cmd))] += 1
            senders.add(p.src)
            if cmd == 2:
                routes += (len(p.payload) - 4) // 20
    return {"packets": dict(cmds), "routes_advertised": routes, "routers": sorted(senders)}


def _ospf(pkts: list[Packet]) -> dict:
    types, routers = Counter(), set()
    for p in pkts:
        if p.proto == 89 and len(p.payload) >= 12:
            types[OSPF_TYPES.get(p.payload[1], str(p.payload[1]))] += 1
            routers.add(".".join(str(b) for b in p.payload[4:8]))
    return {"packets": dict(types), "router_ids": sorted(routers)}


def analyze_packets(pkts: list[Packet]) -> dict:
    flows = _tcp_flows(pkts)
    return {
        "packets": len(pkts),
        "duration_s": round(pkts[-1].ts - pkts[0].ts, 6) if pkts else 0.0,
        "protocols": dict(Counter({1: "ICMP", 6: "TCP", 17: "UDP", 89: "OSPF"}.get(p.proto, str(p.proto)) for p in pkts)),
        "tcp": [_tcp_summary(f) for f in flows],
        "dns": _dns(pkts),
        "rip": _rip(pkts),
        "ospf": _ospf(pkts),
    }


def analyze_file(path: str | Path) -> dict:
    pkts = [p for raw in read_pcap(path) if (p := packets.decode(raw)) is not None]
    pkts.sort(key=lambda p: p.ts)
    report = analyze_packets(pkts)
    report["file"] = str(path)
    return report


def tcp_rtt_series(path: str | Path) -> dict[str, list[tuple[float, float]]]:
    """(time, rtt seconds) samples per flow, for plotting."""
    pkts = sorted((p for raw in read_pcap(path) if (p := packets.decode(raw))), key=lambda p: p.ts)
    return {f.key(): f.rtt_samples for f in _tcp_flows(pkts)}
