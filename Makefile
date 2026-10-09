.PHONY: test sim testbed-phase1 all clean

PY_ROOT = sudo PYTHONPATH=. python3

test:
	uv run pytest -q

# Simulation-only experiments (run anywhere)
sim:
	uv run python -m experiments.phase1_paths --topology trap
	uv run python -m experiments.phase1_paths --topology mesh
	uv run python -m experiments.phase1_count_to_infinity

# Real-network experiments (run on the Ubuntu testbed VM)
testbed-phase1:
	$(PY_ROOT) -m experiments.phase1_trap
	$(PY_ROOT) -m experiments.phase1_validate --topology mesh
	$(PY_ROOT) -m experiments.phase1_convergence

all: sim testbed-phase1

clean:
	rm -rf results .pytest_cache
	-sudo mn -c
