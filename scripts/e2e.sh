#!/usr/bin/env bash
# End-to-end check from a clean clone: install, unit tests, every experiment that needs no root,
# the command-line tools as separate processes, and the dashboard over HTTP.
# Usage: scripts/e2e.sh [git-url-or-path]   (default: this repository's HEAD)
set -euo pipefail

SRC="${1:-$(git rev-parse --show-toplevel)}"
WORK="$(mktemp -d)"
trap 'kill ${PIDS:-} 2>/dev/null || true; rm -rf "$WORK"' EXIT
PIDS=""
pass() { echo "  ok   $*"; }
fail() { echo "  FAIL $*"; exit 1; }
step() { echo; echo "== $*"; }

step "clone and install"
git clone -q "$SRC" "$WORK/repo" && cd "$WORK/repo"
uv sync -q --extra dashboard && pass "uv sync"

step "unit tests"
uv run --extra dashboard pytest -q | tail -2 && pass "pytest"

step "experiments (make sim)"
make -s sim > "$WORK/sim.log" 2>&1 || { tail -30 "$WORK/sim.log"; fail "make sim"; }
pass "make sim"
for f in results/phase1/paths_trap.png results/phase1/count_to_infinity_line.png \
         results/phase2/detection_burst.png results/phase2/arq_efficiency.png results/phase2/arq_window.png \
         results/phase2/arq_timeout.png results/phase2/arq_reorder.png \
         results/phase3/dns_latency.png results/phase3/tcp_cwnd.png results/phase3/tcp_fairness.png \
         results/phase3/tcp_bufferbloat_rtt.png results/phase3/tcp_loss.png \
         results/phase3/dns_hardening.json results/phase3/analyzer_validation.json; do
  [ -s "$f" ] && pass "$f" || fail "missing $f"
done
uv run python - <<'PY'
import json
from netlab.common.results import list_results, load
assert len(list_results()) >= 15, list_results()
# real UDP ARQ results are present and consistent with theory at zero loss
rows = load("phase2", "arq_efficiency").rows
real = {(r["protocol"], r["loss"]): r["efficiency"] for r in rows if r["level"] == "real"}
theory = {(r["protocol"], r["loss"]): r["efficiency"] for r in rows if r["level"] == "theory"}
assert abs(real[("sw", 0.0)] - theory[("sw", 0.0)]) < 0.02, (real, theory)
dns = {s["step"]: s["median_ms"] for s in load("phase3", "dns_latency").summary["steps"]}
assert dns["cold: www.example.lab"] > 5 * dns["warm: www.example.lab again"], dns
for r in load("phase3", "analyzer_validation").rows:
    assert r["sim_retransmissions"] == r["analyzer_retransmissions"], r
print("  ok   result values")
PY

step "command-line tools as separate processes"
# analyzer on a pcap file
uv run python - <<'PY'
from netlab.analyzer import packets as pk
from netlab.analyzer.pcap import write_pcap
c, s = "10.0.0.2", "10.0.0.14"
write_pcap("e2e.pcap", [(0.0, pk.tcp_frame(c, s, 4000, 5201, 1, 0, pk.SYN)),
                        (0.04, pk.tcp_frame(s, c, 5201, 4000, 9, 2, pk.SYN | pk.ACK)),
                        (0.04, pk.tcp_frame(c, s, 4000, 5201, 2, 10, pk.ACK))])
PY
uv run python -m netlab.analyzer e2e.pcap | grep -q "SYN→SYN/ACK 40.0 ms" && pass "analyzer CLI" || fail "analyzer CLI"

# DNS: root, TLD, example and resolver as four real processes, queried by the client CLI
P=5877
uv run python -m netlab.dns.server auth --zone root --root-ip 127.0.1.1 --tld-ip 127.0.1.2 --example-ip 127.0.1.3 --bind 127.0.1.1 --port $P > "$WORK/root.log" 2>&1 & PIDS="$PIDS $!"
uv run python -m netlab.dns.server auth --zone tld --root-ip 127.0.1.1 --tld-ip 127.0.1.2 --example-ip 127.0.1.3 --bind 127.0.1.2 --port $P > "$WORK/tld.log" 2>&1 & PIDS="$PIDS $!"
uv run python -m netlab.dns.server auth --zone example --root-ip 127.0.1.1 --tld-ip 127.0.1.2 --example-ip 127.0.1.3 --bind 127.0.1.3 --port $P > "$WORK/ex.log" 2>&1 & PIDS="$PIDS $!"
uv run python -m netlab.dns.server resolver --root 127.0.1.1 --bind 127.0.1.9 --port $P --upstream-port $P > "$WORK/res.log" 2>&1 & PIDS="$PIDS $!"
sleep 4
OUT=$(uv run python -m netlab.dns.client www.example.lab --server 127.0.1.9 --port $P --repeat 2)
echo "$OUT" | grep -q '10.20.0.10' && pass "DNS via 4 processes: $OUT" || { cat "$WORK"/*.log; fail "DNS resolution: $OUT"; }
uv run python -m netlab.dns.client alias.example.lab --server 127.0.1.9 --port $P | grep -q '10.20.0.10' && pass "CNAME chain" || fail "CNAME"
uv run python -m netlab.dns.client ghost.example.lab --server 127.0.1.9 --port $P | grep -q '"rcode": 3' && pass "NXDOMAIN" || fail "NXDOMAIN"
kill $PIDS 2>/dev/null || true; PIDS=""

# ARQ: receiver and sender as two real processes over UDP
for proto in sw gbn sr; do
  uv run python -m netlab.reliability.udp recv --port 9311 --protocol $proto --n 40 --window 8 --payload 200 --idle 8 > "$WORK/rx.json" & RX=$!
  sleep 1.5
  uv run python -m netlab.reliability.udp send --peer 127.0.0.1:9311 --protocol $proto --n 40 --window 8 --payload 200 --rate-mbit 8 --timeout 0.02 > "$WORK/tx.json"
  wait $RX
  grep -q '"delivered": 40' "$WORK/rx.json" && grep -q '"finished": true' "$WORK/tx.json" && pass "ARQ $proto: 40/40 delivered over UDP processes" || { cat "$WORK/rx.json" "$WORK/tx.json"; fail "ARQ $proto"; }
done

step "dashboard over HTTP"
uv run --extra dashboard streamlit run dashboard/app.py --server.headless true --server.port 8599 --browser.gatherUsageStats false > "$WORK/dash.log" 2>&1 & PIDS="$!"
for i in $(seq 1 30); do curl -sf http://localhost:8599/_stcore/health >/dev/null && break; sleep 1; done
[ "$(curl -sf http://localhost:8599/_stcore/health)" = "ok" ] && pass "streamlit health endpoint" || { cat "$WORK/dash.log"; fail "dashboard did not start"; }
curl -sf http://localhost:8599/ | grep -qi "streamlit" && pass "dashboard serves its page" || fail "dashboard page"

echo; echo "E2E PASSED"
