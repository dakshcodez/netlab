# Setup

There are two environments:

- **Dev machine (any Linux/macOS):** simulators, protocol code, unit tests, plotting.
- **Testbed VM (Ubuntu 24.04):** Mininet, FRR, netem, iperf3, Wireshark. Everything that
  touches real networking runs here, as root.

## Dev machine

```bash
uv sync            # creates .venv with dev dependencies
uv run pytest      # run unit tests
```

## Testbed VM (Ubuntu 24.04)

Use a VM (VirtualBox, virt-manager/QEMU, or UTM on macOS) with ≥2 CPUs and 4 GB RAM.

```bash
sudo apt update
sudo apt install -y mininet openvswitch-switch frr frr-pythontools \
    iperf3 traceroute tcpdump wireshark tshark python3-matplotlib git
sudo systemctl disable --now frr      # we start FRR daemons per Mininet node ourselves
sudo usermod -aG wireshark "$USER"    # capture without root (log out/in afterwards)

git clone https://github.com/dakshcodez/netlab.git
cd netlab
sudo mn --test pingall                # sanity check Mininet
```

Testbed experiments run with the system Python as root, with the repo on `PYTHONPATH`:

```bash
sudo PYTHONPATH=. python3 -m experiments.<name> --help
```

Results land in `results/<phase>/` and are owned by root; `sudo chown -R $USER results`
if you want to edit them.
