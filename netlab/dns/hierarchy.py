"""The lab's DNS hierarchy: root → ``lab`` TLD → ``example.lab``."""

from __future__ import annotations

from dataclasses import dataclass

from netlab.dns import message as m
from netlab.dns.zone import AuthoritativeServer, Zone

WWW_IP = "10.20.0.10"
MAIL_IP = "10.20.0.11"
SHOP_IP = "10.20.0.12"


@dataclass(frozen=True)
class Addresses:
    root: str
    tld: str
    example: str


def build_zones(addr: Addresses, ttl: int = 300, negative_ttl: int = 30) -> dict[str, Zone]:
    root = Zone("", m.SoaData("a.root.lab", "admin.root.lab", minimum=negative_ttl))
    root.add("", m.NS, "a.root.lab", 86400).add("a.root.lab", m.A, addr.root, 86400)
    root.add("lab", m.NS, "ns.lab", 86400).add("ns.lab", m.A, addr.tld, 86400)  # delegation + glue

    tld = Zone("lab", m.SoaData("ns.lab", "admin.lab", minimum=negative_ttl))
    tld.add("lab", m.NS, "ns.lab", 86400).add("ns.lab", m.A, addr.tld, 86400)
    tld.add("example.lab", m.NS, "ns.example.lab", 86400).add("ns.example.lab", m.A, addr.example, 86400)

    ex = Zone("example.lab", m.SoaData("ns.example.lab", "admin.example.lab", minimum=negative_ttl))
    ex.add("example.lab", m.NS, "ns.example.lab", 86400).add("ns.example.lab", m.A, addr.example, 86400)
    ex.add("www.example.lab", m.A, WWW_IP, ttl)
    ex.add("mail.example.lab", m.A, MAIL_IP, ttl)
    ex.add("shop.example.lab", m.A, SHOP_IP, ttl)
    ex.add("alias.example.lab", m.CNAME, "www.example.lab", ttl)
    return {"root": root, "tld": tld, "example": ex}


def build_servers(addr: Addresses, **kw) -> dict[str, AuthoritativeServer]:
    return {name: AuthoritativeServer([zone]) for name, zone in build_zones(addr, **kw).items()}
