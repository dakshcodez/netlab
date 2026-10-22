"""NetLab dashboard.   Run:  uv run --extra dashboard streamlit run dashboard/app.py

Pick an experiment, set loss / delay / bandwidth / buffer, run it, see the plots. Simulation and
loopback experiments run right here; testbed experiments need the dashboard started as root on the
testbed VM. Anything already in ``results/`` can be browsed from any phase.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from netlab.common.plot import COLORS
from netlab.dashboard import runners as run

st.set_page_config(page_title="NetLab", layout="wide")
st.title("NetLab: Network Performance Analyzer & Simulator")

PAGES = ["ARQ: efficiency vs loss", "TCP congestion control", "DNS cold vs cached",
         "Error detection strength", "Testbed experiments", "Browse saved results"]
page = st.sidebar.radio("Experiment", PAGES)
st.sidebar.caption("Theory, simulation and real networking, on the same axes.")


def arq_page() -> None:
    st.subheader("Stop-and-Wait, Go-Back-N and Selective Repeat")
    c1, c2, c3 = st.columns(3)
    a = c1.slider("a = propagation delay / frame time", 0.5, 20.0, 5.0, 0.5,
                  help="round trip holds 1 + 2a frames")
    window = c2.slider("window size (GBN / SR)", 1, 64, 16)
    max_loss = c3.slider("max loss probability", 0.05, 0.5, 0.2, 0.05)
    reorder = st.slider("reordering probability", 0.0, 0.5, 0.0, 0.05)
    protos = st.multiselect("protocols", ["sw", "gbn", "sr"], ["sw", "gbn", "sr"])
    if st.button("Run", key="arq") and protos:
        losses = [round(max_loss * i / 6, 4) for i in range(7)]
        with st.spinner("simulating..."):
            data = run.arq_vs_loss(protos, a, window, losses, packets=1200, reorder=reorder)
        fig, ax = plt.subplots(figsize=(8, 4))
        for proto, d in data.items():
            ax.plot(losses, d["sim"], "-o", ms=4, color=COLORS[proto], label=f"{proto} simulated")
            if reorder == 0:
                ax.plot(losses, d["theory"], "--", color=COLORS[proto], label=f"{proto} theory")
        ax.set_xlabel("frame loss probability")
        ax.set_ylabel("link efficiency")
        ax.set_ylim(0, 1.02)
        ax.grid(alpha=0.3)
        ax.legend(frameon=False, ncol=2, fontsize=8)
        st.pyplot(fig)
        if reorder:
            st.caption("Theory curves assume in-order delivery, so they are hidden while reordering is on.")


def tcp_page() -> None:
    st.subheader("Reno vs CUBIC vs BBR on one bottleneck")
    c1, c2, c3, c4 = st.columns(4)
    bw = c1.slider("bandwidth (Mbit/s)", 1, 100, 10)
    rtt = c2.slider("round-trip time (ms)", 5, 200, 40)
    loss = c3.slider("random loss (%)", 0.0, 5.0, 0.0, 0.1) / 100
    duration = c4.slider("duration (s)", 10, 60, 30)
    bdp = int(bw * 1e6 / (1448 * 8) * rtt / 1000)
    buf = st.slider(f"buffer (packets); one bandwidth-delay product = {bdp}", 20, max(800, 4 * bdp), max(bdp, 20))
    ccs = st.multiselect("flows (one per entry; pick two for a fairness test)", ["reno", "cubic", "bbr"],
                         ["reno"], max_selections=3)
    if st.button("Run", key="tcp") and ccs:
        with st.spinner("simulating..."):
            out = run.tcp_run(ccs, bw, rtt, buf, loss, duration)
        res = out["result"]
        fig, ax = plt.subplots(figsize=(8, 3.6))
        for f in res.flows:
            cc = f.name.split("-")[0]
            ax.plot([t[0] for t in f.trace], [t[1] for t in f.trace], color=COLORS[cc], lw=1.2, label=f.name)
        ax.axhline(out["bdp_pkts"], color="#999", ls="--", lw=0.8)
        ax.set_xlabel("time (s)")
        ax.set_ylabel("cwnd (packets)")
        ax.set_ylim(0, 3 * max(out["bdp_pkts"], 10))
        ax.legend(frameon=False)
        ax.grid(alpha=0.3)
        st.pyplot(fig)
        st.dataframe(pd.DataFrame(out["table"]), hide_index=True)
        if out["jain"] is not None:
            st.metric("Jain's fairness index", f"{out['jain']:.3f}", help="1.0 = equal shares")


def dns_page() -> None:
    st.subheader("DNS hierarchy on real UDP sockets (loopback, emulated distance)")
    c1, c2 = st.columns(2)
    hop = c1.slider("round trip to each DNS server (ms)", 2, 100, 20)
    client = c2.slider("round trip client ↔ resolver (ms)", 0, 50, 2)
    if st.button("Run", key="dns"):
        with st.spinner("resolving..."):
            rows = run.dns_run(hop, client)
        df = pd.DataFrame(rows)
        st.bar_chart(df, x="lookup", y="ms")
        st.dataframe(df, hide_index=True)
        st.caption("Cold = root → TLD → authoritative (three upstream round trips); warm answers come from the cache.")


def detection_page() -> None:
    st.subheader("Which error-detection code misses which errors?")
    top = st.slider("longest burst (bits)", 4, 64, 40)
    trials = st.select_slider("trials per point", [500, 1000, 3000, 10000], 3000)
    if st.button("Run", key="det"):
        lengths = sorted({1, 2, 3, 4, 8, 16, 24, 32, 33, top})
        lengths = [n for n in lengths if n <= top]
        with st.spinner("injecting errors..."):
            data = run.detection_vs_burst(lengths, trials)
        df = pd.DataFrame(data, index=lengths)
        df.index.name = "burst length (bits)"
        st.line_chart(df)
        st.caption("Fraction of corrupted frames that still pass the check. Zero means none slipped through in this many trials.")


def testbed_page() -> None:
    st.subheader("Real networking: Mininet + FRR + netem")
    ok, why = run.testbed_available()
    choice = st.selectbox("experiment", list(run.TESTBED_EXPERIMENTS))
    st.code("sudo PYTHONPATH=. python3 -m " + " ".join(run.TESTBED_EXPERIMENTS[choice]))
    if not ok:
        st.warning(why)
    if st.button("Run on the testbed", disabled=not ok):
        with st.spinner("running... this can take several minutes"):
            proc = run.run_testbed(run.TESTBED_EXPERIMENTS[choice])
        st.code(proc.stdout[-6000:] or proc.stderr[-6000:])
        (st.success if proc.returncode == 0 else st.error)(f"exit code {proc.returncode}")


def browse_page() -> None:
    st.subheader("Saved results (any phase)")
    saved = run.saved_results()
    if not saved:
        st.info("Nothing in results/ yet. Run `make sim` or an experiment first.")
        return
    phase, exp = st.selectbox("result", saved, format_func=lambda x: f"{x[0]} / {x[1]}")
    r = run.load_saved(phase, exp)
    st.caption(f"level: {r.level} · host: {r.host} · created: {r.created}")
    for png in run.png_for(phase, exp):
        st.image(str(png))
    if r.rows:
        st.dataframe(pd.DataFrame(r.rows), hide_index=True)
    with st.expander("parameters and summary"):
        st.json({"params": r.params, "summary": {k: v for k, v in r.summary.items() if not str(k).startswith("trace_")}})


{"ARQ: efficiency vs loss": arq_page, "TCP congestion control": tcp_page, "DNS cold vs cached": dns_page,
 "Error detection strength": detection_page, "Testbed experiments": testbed_page,
 "Browse saved results": browse_page}[page]()
