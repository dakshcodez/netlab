"""ARQ over real UDP between two Mininet hosts, with netem supplying delay and loss.

Run on the testbed VM:

    sudo PYTHONPATH=. python3 -m experiments.phase2_arq_real

Loss is applied to the data direction only (h1 → h2) so the run matches the theory's
"ACKs are never lost" assumption; delay is applied both ways. The sender paces itself at
``--rate-mbit`` (see netlab/reliability/udp.py), so netem does not need a rate limit.
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from netlab.common.plot import COLORS, line_plot
from netlab.common.results import RESULTS_DIR, Result
from netlab.reliability import arq, theory
from netlab.testbed import netem
from netlab.testbed.net import Testbed, _json_in
from netlab.topology import library

REPO = Path(__file__).resolve().parents[1]
PORT = 9000
LABELS = {"sw": "Stop-and-Wait", "gbn": "Go-Back-N", "sr": "Selective Repeat"}


def run_once(tb: Testbed, protocol: str, window: int, loss: float, a: float, n: int,
             rate_mbit: float, payload: int, timeout_factor: float) -> dict:
    frame_bytes = arq.OVERHEAD + payload
    tx_time = frame_bytes * 8 / (rate_mbit * 1e6)
    delay = a * tx_time
    link = tb.topo.link_between("h1", "h2")
    tb.node("h1").cmd(netem.apply_cmd(tb.topo.interface("h1", link).name,
                                      netem.Shape(delay_ms=delay * 1e3, loss_pct=loss * 100)))
    tb.node("h2").cmd(netem.apply_cmd(tb.topo.interface("h2", link).name,
                                      netem.Shape(delay_ms=delay * 1e3)))
    env = f"cd {REPO} && PYTHONPATH=. python3 -m netlab.reliability.udp"
    common = f"--protocol {protocol} --n {n} --window {window} --payload {payload}"
    server = tb.node("h2").popen(["sh", "-c", f"{env} recv --port {PORT} {common} --idle 5"])
    time.sleep(1.0)
    out = tb.node("h1").cmd(f"{env} send --peer {tb.topo.ip('h2')}:{PORT} {common} "
                            f"--rate-mbit {rate_mbit} --timeout {2 * delay * timeout_factor + 0.002}")
    server.wait(timeout=30)
    report = _json_in(out)
    if report is None:
        raise RuntimeError(f"sender produced no report: {out.strip()[:300]}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--packets", type=int, default=300)
    parser.add_argument("--a", type=float, default=5.0)
    parser.add_argument("--rate-mbit", type=float, default=4.0)
    parser.add_argument("--payload", type=int, default=1000)
    parser.add_argument("--losses", type=float, nargs="+", default=[0.0, 0.02, 0.05, 0.1, 0.2])
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("run as root (sudo PYTHONPATH=. python3 -m experiments.phase2_arq_real)")

    configs = [("sw", 1), ("gbn", 8), ("sr", 32)]
    result = Result(phase="phase2", experiment="arq_real", level="real",
                    params={"a": args.a, "rate_mbit": args.rate_mbit, "payload": args.payload,
                            "packets": args.packets, "windows": dict(configs)})
    series = []
    with Testbed(library.pair()) as tb:
        for proto, window in configs:
            effs = []
            for loss in args.losses:
                rep = run_once(tb, proto, window, loss, args.a, args.packets, args.rate_mbit,
                               args.payload, 1.0)
                theory_eff = theory.efficiency(proto, args.a, loss, window)
                result.add(protocol=proto, window=window, loss=loss, efficiency=rep["efficiency"],
                           theory=theory_eff, retransmissions=rep["retransmissions"],
                           timeouts=rep["timeouts"], elapsed_s=round(rep["elapsed"], 3),
                           finished=rep["finished"])
                effs.append(rep["efficiency"])
                print(f"{proto:<4} w={window:<3} loss={loss:<5} eff={rep['efficiency']:.3f} "
                      f"(theory {theory_eff:.3f})  retx={rep['retransmissions']}")
            series += [
                {"x": args.losses, "y": effs, "label": f"{LABELS[proto]} measured", "color": COLORS[proto],
                 "style": "real"},
                {"x": args.losses, "y": [theory.efficiency(proto, args.a, p, window) for p in args.losses],
                 "label": f"{LABELS[proto]} theory", "color": COLORS[proto], "style": "theory"},
            ]
    line_plot(series, RESULTS_DIR / "phase2" / "arq_real.png",
              f"ARQ over real UDP on Mininet + netem (a = {args.a:g})",
              "data-frame loss probability", "link efficiency", ylim=(0, 1.0))
    print(f"saved {result.save()}")


if __name__ == "__main__":
    main()
