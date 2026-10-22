"""Build a Topology in Mininet and run real routing protocols on it.

Requires root, Mininet and FRR (see docs/SETUP.md). Routers are Linux hosts with IP
forwarding enabled; links are plain veth pairs shaped with netem (rate + delay), so there is
no OpenFlow controller or switch involved.

Usage::

    with Testbed(library.trap()) as tb:
        tb.start_routing("ospf")
        tb.wait_converged()
        print(tb.routes("r1"))
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

from netlab.routing.tables import predict
from netlab.testbed import frr, netem
from netlab.topology.model import Link, Topology

RUN_BASE = Path("/tmp/netlab")


def _mininet():
    try:
        from mininet.link import Link as MnLink
        from mininet.log import setLogLevel
        from mininet.net import Mininet
        from mininet.node import Node
    except ImportError as exc:
        raise SystemExit("Mininet is not installed; run this on the testbed VM (docs/SETUP.md)") from exc
    return Mininet, Node, MnLink, setLogLevel


def _json_in(text: str):
    """First JSON object in command output (Mininet output can carry stray text)."""
    start = text.find("{")
    if start < 0:
        return None
    return json.JSONDecoder().raw_decode(text[start:])[0]


def link_shape(link: Link) -> netem.Shape:
    return netem.Shape(rate_mbit=link.bw_mbps, delay_ms=link.delay_ms)


class Testbed:
    def __init__(self, topo: Topology, verbose: bool = False) -> None:
        self.topo = topo
        self.verbose = verbose
        self.net = None
        self.protocol: str | None = None
        self.run_base = RUN_BASE / topo.name

    # --- lifecycle --------------------------------------------------------------------

    def __enter__(self) -> "Testbed":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def start(self) -> None:
        Mininet, Node, MnLink, setLogLevel = _mininet()
        setLogLevel("info" if self.verbose else "warning")

        class LinuxRouter(Node):
            def config(self, **params):
                super().config(**params)
                self.cmd("sysctl -qw net.ipv4.ip_forward=1")
                self.cmd("sysctl -qw net.ipv4.conf.all.rp_filter=0")

            def terminate(self):
                self.cmd("sysctl -qw net.ipv4.ip_forward=0")
                super().terminate()

        net = Mininet(controller=None, link=MnLink, build=False)
        for name, node in self.topo.nodes.items():
            net.addHost(name, cls=LinuxRouter if node.is_router else None, ip=None)
        for link in self.topo.links:
            ia, ib = self.topo.interface(link.a, link), self.topo.interface(link.b, link)
            net.addLink(
                link.a, link.b,
                intfName1=ia.name, intfName2=ib.name,
                params1={"ip": str(ia.ip)}, params2={"ip": str(ib.ip)},
            )
        net.build()
        net.start()
        self.net = net

        for link in self.topo.links:
            self.shape_link(link.a, link.b, link_shape(link))
        for host in self.topo.hosts:
            net[host].cmd(f"ip route replace default via {self.topo.gateway(host)}")

    def stop(self) -> None:
        if self.net is None:
            return
        self.stop_routing()
        self.net.stop()
        self.net = None

    def node(self, name: str):
        return self.net[name]

    # --- links ------------------------------------------------------------------------

    def shape_link(self, a: str, b: str, shape: netem.Shape) -> None:
        """Apply the same netem shape to both directions of the a–b link."""
        link = self.topo.link_between(a, b)
        for end in (a, b):
            intf = self.topo.interface(end, link).name
            out = self.node(end).cmd(netem.apply_cmd(intf, shape))
            if out.strip():
                raise RuntimeError(f"tc failed on {intf}: {out.strip()}")

    def fail_link(self, a: str, b: str, mode: str = "down") -> None:
        """mode="down": carrier loss, both interfaces go down (routers notice immediately).
        mode="silent": interfaces stay up but drop everything (only protocol timers notice)."""
        link = self.topo.link_between(a, b)
        if mode == "down":
            self.net.configLinkStatus(a, b, "down")
        elif mode == "silent":
            for end in (a, b):
                intf = self.topo.interface(end, link).name
                node = self.node(end)
                node.cmd(f"iptables -I INPUT -i {intf} -j DROP")
                node.cmd(f"iptables -I OUTPUT -o {intf} -j DROP")
                node.cmd(f"iptables -I FORWARD -i {intf} -j DROP")
                node.cmd(f"iptables -I FORWARD -o {intf} -j DROP")
        else:
            raise ValueError(f"unknown failure mode {mode!r}")

    def restore_link(self, a: str, b: str) -> None:
        self.net.configLinkStatus(a, b, "up")
        for end in (a, b):
            self.node(end).cmd("iptables -F")
        link = self.topo.link_between(a, b)
        self.shape_link(a, b, link_shape(link))  # carrier down/up can drop the qdisc

    # --- routing ----------------------------------------------------------------------

    def start_routing(self, protocol: str, timers: frr.Timers = frr.Timers()) -> None:
        if not frr.FRR_BIN.exists():
            raise SystemExit(f"FRR not found at {frr.FRR_BIN}; see docs/SETUP.md")
        self.stop_routing()
        self.protocol = protocol
        for router in self.topo.routers:
            rundir = frr.run_dir(self.run_base, router)
            shutil.rmtree(rundir, ignore_errors=True)
            rundir.mkdir(parents=True)
            (rundir / "empty.conf").write_text("")
            conf = rundir / "frr.conf"
            conf.write_text(frr.render_config(self.topo, router, protocol, timers))
            node = self.node(router)
            for daemon in frr.daemons_for(protocol):
                out = node.cmd(frr.daemon_cmd(daemon, router, rundir))
                if "error" in out.lower():
                    raise RuntimeError(f"{router}: {daemon} failed to start: {out.strip()}")
            self._wait_for_vty(router, rundir, frr.daemons_for(protocol))
            out = node.cmd(frr.vtysh_cmd(router, rundir, infile=conf))
            if self.verbose and out.strip():
                print(f"[{router}] {out.strip()}")

    def _wait_for_vty(self, router: str, rundir: Path, daemons: list[str], timeout: float = 10) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if all((rundir / f"{d}.vty").exists() for d in daemons):
                return
            time.sleep(0.1)
        raise RuntimeError(f"{router}: FRR daemons did not come up; see logs in {rundir}")

    def stop_routing(self) -> None:
        if self.net is None:
            return
        for router in self.topo.routers:
            rundir = frr.run_dir(self.run_base, router)
            for pid_file in rundir.glob("*.pid"):
                self.node(router).cmd(f"kill $(cat {pid_file}) 2>/dev/null")
        self.protocol = None

    def vtysh(self, router: str, command: str) -> str:
        return self.node(router).cmd(frr.vtysh_cmd(router, frr.run_dir(self.run_base, router), command))

    def routes(self, router: str) -> dict[str, dict]:
        """Selected routes learned via the running protocol: prefix -> {metric, next_hops}."""
        table = _json_in(self.vtysh(router, "show ip route json")) or {}
        out = {}
        for prefix, entries in table.items():
            for e in entries:
                if e.get("selected") and e.get("protocol") == self.protocol:
                    hops = {nh["ip"] for nh in e.get("nexthops", []) if nh.get("active") and "ip" in nh}
                    out[prefix] = {"metric": e.get("metric"), "next_hops": hops}
        return out

    def wait_converged(self, timeout: float = 120, poll: float = 0.5) -> float:
        """Block until every router has a route to every predicted prefix. Returns seconds."""
        expected = {r: set(predict(self.topo, r, self.protocol)) for r in self.topo.routers}
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if all(expected[r] <= set(self.routes(r)) for r in self.topo.routers):
                return time.monotonic() - start
            time.sleep(poll)
        missing = {r: expected[r] - set(self.routes(r)) for r in self.topo.routers}
        raise TimeoutError(f"not converged after {timeout}s; missing: {missing}")

    # --- measurement helpers ----------------------------------------------------------

    def traceroute(self, src: str, dst: str) -> list[str]:
        out = self.node(src).cmd(f"traceroute -n -q 1 -w 1 {self.topo.ip(dst)}")
        return re.findall(r"^\s*\d+\s+(\d+\.\d+\.\d+\.\d+)", out, re.MULTILINE)

    def iperf(self, src: str, dst: str, seconds: int = 10) -> float:
        """TCP throughput src → dst in Mbit/s."""
        server = self.node(dst).popen(["iperf3", "-s", "-1"])
        time.sleep(0.5)
        try:
            out = self.node(src).cmd(f"iperf3 -c {self.topo.ip(dst)} -t {seconds} -J")
            report = _json_in(out)
            if report is None or "end" not in report:
                raise RuntimeError(f"iperf3 failed: {out.strip()[:200]}")
            return report["end"]["sum_received"]["bits_per_second"] / 1e6
        finally:
            server.terminate()
            server.wait()

    def owner_of(self, ip: str) -> str | None:
        for node, intfs in self.topo.interfaces.items():
            if any(str(i.ip.ip) == ip for i in intfs):
                return node
        return None
