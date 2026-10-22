"""FRRouting configuration and per-node daemon management for Mininet routers.

Each router gets its own run directory; daemons are started inside the router's network
namespace with explicit socket/pid paths so many FRR instances can coexist. Configuration is
pushed through ``vtysh -f`` so it works whether or not the installed FRR uses mgmtd.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from pathlib import Path

from netlab.topology.model import Topology

FRR_BIN = Path("/usr/lib/frr")
DAEMONS = {"rip": "ripd", "ospf": "ospfd"}


@dataclass(frozen=True)
class Timers:
    rip_update: int = 30
    rip_timeout: int = 180
    rip_garbage: int = 120
    ospf_hello: int = 10
    ospf_dead: int = 40


def router_id(topo: Topology, router: str) -> str:
    index = topo.routers.index(router) + 1
    return f"{index}.{index}.{index}.{index}"


def _passive(topo: Topology, router: str) -> list[str]:
    """Interfaces facing hosts: advertise their subnet but don't speak the protocol there."""
    return [i.name for i in topo.interfaces[router] if not topo.nodes[i.peer].is_router]


def render_config(topo: Topology, router: str, protocol: str, timers: Timers = Timers()) -> str:
    network = ipaddress.IPv4Network(topo.base)
    lines = [f"hostname {router}", "log stdout warnings", "!"]
    if protocol == "rip":
        lines += [
            "router rip",
            " version 2",
            f" network {network}",
            f" timers basic {timers.rip_update} {timers.rip_timeout} {timers.rip_garbage}",
            *(f" passive-interface {name}" for name in _passive(topo, router)),
            "!",
        ]
    elif protocol == "ospf":
        for intf in topo.interfaces[router]:
            lines += [
                f"interface {intf.name}",
                f" ip ospf cost {intf.link.ospf_cost()}",
                f" ip ospf hello-interval {timers.ospf_hello}",
                f" ip ospf dead-interval {timers.ospf_dead}",
            ]
            if topo.nodes[intf.peer].is_router:
                lines.append(" ip ospf network point-to-point")
            lines.append("!")
        lines += [
            "router ospf",
            f" ospf router-id {router_id(topo, router)}",
            f" network {network} area 0",
            *(f" passive-interface {name}" for name in _passive(topo, router)),
            "!",
        ]
    else:
        raise ValueError(f"unknown protocol {protocol!r}")
    return "\n".join(lines) + "\n"


def run_dir(base: Path, router: str) -> Path:
    return base / router


def daemon_cmd(daemon: str, router: str, rundir: Path) -> str:
    args = [
        str(FRR_BIN / daemon), "-d",
        "-N", router,
        "-u", "root", "-g", "root",
        "-f", str(rundir / "empty.conf"),
        "-i", str(rundir / f"{daemon}.pid"),
        "--vty_socket", str(rundir),
        "--log", f"file:{rundir / f'{daemon}.log'}",
    ]
    if daemon != "mgmtd":  # zebra listens on the zserv socket, protocol daemons connect to it
        args += ["-z", str(rundir / "zserv.api")]
    return " ".join(args)


def daemons_for(protocol: str) -> list[str]:
    extra = ["mgmtd"] if (FRR_BIN / "mgmtd").exists() else []  # FRR >= 9 needs mgmtd
    return [*extra, "zebra", DAEMONS[protocol]]


def vtysh_cmd(router: str, rundir: Path, command: str | None = None, infile: Path | None = None) -> str:
    base = f"vtysh -N {router} --vty_socket {rundir}"
    if infile is not None:
        return f"{base} -f {infile}"
    return f"{base} -c '{command}'"
