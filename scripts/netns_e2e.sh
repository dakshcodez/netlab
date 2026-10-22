#!/usr/bin/env bash
# Real-kernel network test without Mininet or root: two network namespaces joined by a veth pair
# with tc netem delay and loss, inside an unprivileged user namespace. Runs the ARQ protocols and
# a DNS lookup across that link as separate processes. Needs: ip, tc (iproute2), unshare.
# Usage: scripts/netns_e2e.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD"
export PY="${PYTHON:-python3}"

if ! unshare -Urnm true 2>/dev/null; then echo "unprivileged user namespaces are disabled; skipping"; exit 0; fi

exec unshare -Urnm bash -s <<'INNER'
set -euo pipefail
mkdir -p /run/netns 2>/dev/null || mount -t tmpfs tmpfs /run 2>/dev/null && mkdir -p /run/netns
ip netns add h1; ip netns add h2
ip link add v1 type veth peer name v2
ip link set v1 netns h1; ip link set v2 netns h2
ip -n h1 addr add 10.9.0.1/24 dev v1; ip -n h2 addr add 10.9.0.2/24 dev v2
ip -n h1 link set v1 up; ip -n h1 link set lo up; ip -n h2 link set v2 up; ip -n h2 link set lo up

# 20 ms one-way delay both ways, 5% loss on the data direction (h1 -> h2) only
ip netns exec h1 tc qdisc add dev v1 root netem delay 10ms loss 5%
ip netns exec h2 tc qdisc add dev v2 root netem delay 10ms
ip netns exec h1 ping -c 3 -i 0.2 -q 10.9.0.2 | tail -2
echo "  ok   link up, ping through netem"

fail=0
for proto in sw gbn sr; do
  ip netns exec h2 $PY -m netlab.reliability.udp recv --port 9400 --protocol $proto --n 60 --window 16 --payload 1000 --idle 10 > /tmp/rx.json &
  RX=$!; sleep 1
  ip netns exec h1 $PY -m netlab.reliability.udp send --peer 10.9.0.2:9400 --protocol $proto --n 60 --window 16 \
      --payload 1000 --rate-mbit 4 --timeout 0.045 > /tmp/tx.json
  wait $RX
  if grep -q '"delivered": 60' /tmp/rx.json && grep -q '"finished": true' /tmp/tx.json; then
    $PY - <<PY2
import json; r = json.load(open("/tmp/tx.json"))
print(f"  ok   ARQ $proto over veth+netem: 60/60 delivered, efficiency {r['efficiency']:.3f}, retransmissions {r['retransmissions']}")
PY2
  else echo "  FAIL ARQ $proto"; cat /tmp/rx.json /tmp/tx.json; fail=1; fi
done

# DNS hierarchy: servers in h2 on separate addresses, resolver in h2, client in h1 across the netem link
ip -n h2 addr add 10.9.0.11/24 dev v2; ip -n h2 addr add 10.9.0.12/24 dev v2; ip -n h2 addr add 10.9.0.13/24 dev v2
A="--root-ip 10.9.0.11 --tld-ip 10.9.0.12 --example-ip 10.9.0.13"
for z in "root 11" "tld 12" "example 13"; do set -- $z
  ip netns exec h2 $PY -m netlab.dns.server auth --zone $1 $A --bind 10.9.0.$2 --port 53 > /tmp/dns_$1.log 2>&1 &
done
ip netns exec h2 $PY -m netlab.dns.server resolver --root 10.9.0.11 --bind 10.9.0.2 --port 53 > /tmp/dns_res.log 2>&1 &
sleep 3
out=$(ip netns exec h1 $PY -m netlab.dns.client www.example.lab --server 10.9.0.2 --repeat 2)
echo "$out" | grep -q 10.20.0.10 && echo "  ok   DNS across netns: $out" || { echo "  FAIL DNS: $out"; cat /tmp/dns_*.log; fail=1; }
kill $(jobs -p) 2>/dev/null || true
[ $fail = 0 ] && echo "NETNS E2E PASSED" || { echo "NETNS E2E FAILED"; exit 1; }
INNER
