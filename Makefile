.PHONY: test sim all clean

test:
	uv run pytest -q

# Simulation-only experiments (run anywhere)
sim:
	@echo "No simulation experiments on main yet; see phase branches."

# Everything, including testbed experiments (run on the Ubuntu VM as root)
all: sim

clean:
	rm -rf results .pytest_cache
