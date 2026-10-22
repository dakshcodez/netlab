.PHONY: e2e test sim sim-phase1 sim-phase2 sim-phase3 testbed testbed-phase1 testbed-phase2 testbed-phase3 dashboard all clean

PY_ROOT = sudo PYTHONPATH=. python3

test:
	uv run --extra dashboard pytest -q

# Clean-clone end-to-end check (install, tests, every no-root experiment, CLIs, dashboard)
e2e:
	scripts/e2e.sh

# --- simulation and loopback experiments: run anywhere, no root --------------------------
sim: sim-phase1 sim-phase2 sim-phase3

sim-phase1:
	uv run python -m experiments.phase1_paths --topology trap
	uv run python -m experiments.phase1_paths --topology mesh
	uv run python -m experiments.phase1_count_to_infinity

sim-phase2:
	uv run python -m experiments.phase2_detection
	uv run python -m experiments.phase2_arq --real     # theory + simulation + real UDP on loopback

sim-phase3:
	uv run python -m experiments.phase3_dns_latency    # real UDP sockets on loopback
	uv run python -m experiments.phase3_dns_hardening
	uv run python -m experiments.phase3_tcp
	uv run python -m experiments.phase3_analyzer_demo

# --- real-network experiments: Ubuntu testbed VM with Mininet, FRR, iperf3 (see docs/SETUP.md) ---
testbed: testbed-phase1 testbed-phase2 testbed-phase3

testbed-phase1:
	$(PY_ROOT) -m experiments.phase1_trap
	$(PY_ROOT) -m experiments.phase1_validate --topology mesh
	$(PY_ROOT) -m experiments.phase1_convergence

testbed-phase2:
	$(PY_ROOT) -m experiments.phase2_arq_real

testbed-phase3:
	$(PY_ROOT) -m experiments.phase3_dns_latency --testbed
	$(PY_ROOT) -m experiments.phase3_tcp --testbed

# --- everything ---------------------------------------------------------------------------
dashboard:
	uv run --extra dashboard streamlit run dashboard/app.py

all: test sim testbed

clean:
	rm -rf results .pytest_cache
	-sudo mn -c
