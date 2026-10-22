"""Backend for the dashboard: small, fast runs of the simulations with user-chosen parameters.

Kept free of Streamlit so it can be unit-tested and reused from scripts.
"""

from __future__ import annotations

import importlib.util
import os
import random
import subprocess
import sys
from pathlib import Path

from netlab.common.results import RESULTS_DIR, list_results, load
from netlab.reliability import arq, detect, inject, theory
from netlab.reliability.channel import Channel
from netlab.reliability.sim import simulate as arq_simulate
from netlab.reliability.sim import standard_setup
from netlab.tcp.sim import MSS_BYTES, jain, simulate as tcp_simulate

REPO = Path(__file__).resolve().parents[2]
PAYLOAD = 100
FRAME = arq.OVERHEAD + PAYLOAD


# --- ARQ ------------------------------------------------------------------------------

def arq_vs_loss(protocols: list[str], a: float, window: int, losses: list[float], packets: int = 1500,
                reorder: float = 0.0, seeds: tuple[int, ...] = (1, 2)) -> dict[str, dict[str, list[float]]]:
    """Per protocol: simulated and theoretical efficiency at every loss rate."""
    tx_time, delay, timeout = standard_setup(a, FRAME)
    out: dict[str, dict[str, list[float]]] = {}
    for proto in protocols:
        w = 1 if proto == "sw" else window
        sim, th = [], []
        for p in losses:
            effs = []
            for s in seeds:
                run = arq_simulate(proto, packets, w, timeout,
                                   Channel(delay=delay, loss=p, reorder=reorder, reorder_delay=3 * tx_time,
                                           rate_bps=1e6, seed=s),
                                   Channel(delay=delay, seed=100 + s), PAYLOAD)
                effs.append(run.efficiency)
            sim.append(sum(effs) / len(effs))
            th.append(theory.efficiency(proto, a, p, w))
        out[proto] = {"sim": sim, "theory": th}
    return out


# --- error detection ------------------------------------------------------------------

def detection_vs_burst(lengths: list[int], trials: int = 3000, seed: int = 1) -> dict[str, list[float]]:
    rng = random.Random(seed)
    out: dict[str, list[float]] = {name: [] for name in detect.SCHEMES}
    for length in lengths:
        for name, scheme in detect.SCHEMES.items():
            missed = 0
            for _ in range(trials):
                data = rng.randbytes(64)
                frame = data + scheme.tag(data)
                bad = inject.burst_error(frame, length, rng)
                if scheme.verify(bad[:64], bad[64:]):
                    missed += 1
            out[name].append(missed / trials)
    return out


# --- TCP ------------------------------------------------------------------------------

def tcp_run(ccs: list[str], bandwidth_mbps: float, rtt_ms: float, buffer_pkts: int, random_loss: float,
            duration: float) -> dict:
    res = tcp_simulate(ccs, bandwidth_mbps, rtt_ms, buffer_pkts, duration, random_loss=random_loss)
    warm = min(5.0, duration / 4)
    shares = [res.throughput_mbps(f, warm, duration) for f in res.flows]
    return {
        "result": res,
        "table": [{"flow": f.name, "throughput_mbps": round(s, 2), "mean_rtt_ms": round(res.mean_rtt_ms(f, warm), 1),
                   "retransmissions": f.retransmissions, "timeouts": f.timeouts}
                  for f, s in zip(res.flows, shares)],
        "jain": jain(shares) if len(shares) > 1 else None,
        "bdp_pkts": bandwidth_mbps * 1e6 / (MSS_BYTES * 8) * rtt_ms / 1000,
    }


# --- DNS ------------------------------------------------------------------------------

_dns_port = [5600]


def dns_run(hop_rtt_ms: float, client_rtt_ms: float, ttl_s: int = 300) -> list[dict]:
    """Cold / warm / sibling lookups against the real UDP hierarchy on loopback."""
    from netlab.dns import client
    from netlab.dns.local import local_hierarchy

    _dns_port[0] += 1
    rows = []
    with local_hierarchy(port=_dns_port[0], hop_rtt_ms=hop_rtt_ms, client_rtt_ms=client_rtt_ms, ttl=ttl_s) as (res, ip, port):
        for label, name in [("cold: www.example.lab", "www.example.lab"), ("warm: www.example.lab", "www.example.lab"),
                            ("sibling: mail.example.lab", "mail.example.lab"),
                            ("NXDOMAIN (cold)", "ghost.example.lab"), ("NXDOMAIN (negatively cached)", "ghost.example.lab")]:
            _, secs = client.lookup(ip, name, port=port)
            rows.append({"lookup": label, "ms": round(secs * 1000, 1)})
    return rows


# --- saved results and testbed experiments ---------------------------------------------

def saved_results() -> list[tuple[str, str]]:
    return list_results()


def load_saved(phase: str, experiment: str):
    return load(phase, experiment)


def png_for(phase: str, experiment: str) -> list[Path]:
    folder = RESULTS_DIR / phase
    return sorted(folder.glob(f"{experiment}*.png")) if folder.exists() else []


TESTBED_EXPERIMENTS = {
    "Phase 1: trap topology (RIP vs OSPF)": ["experiments.phase1_trap"],
    "Phase 1: convergence after link failure": ["experiments.phase1_convergence", "--fast-timers"],
    "Phase 1: simulator vs FRR tables": ["experiments.phase1_validate", "--topology", "mesh"],
    "Phase 2: ARQ over real UDP (netem)": ["experiments.phase2_arq_real"],
    "Phase 3: DNS latency (hierarchy on hosts)": ["experiments.phase3_dns_latency", "--testbed"],
    "Phase 3: TCP congestion control (iperf3 + ss)": ["experiments.phase3_tcp", "--testbed"],
}


def testbed_available() -> tuple[bool, str]:
    if os.geteuid() != 0:
        return False, "start the dashboard as root (sudo) to run testbed experiments"
    if importlib.util.find_spec("mininet") is None:
        return False, "Mininet is not installed (see docs/SETUP.md)"
    return True, "ready"


def run_testbed(args: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    return subprocess.run(["python3", "-m", *args], cwd=REPO, env=env, capture_output=True, text=True, timeout=timeout)
