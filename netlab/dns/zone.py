"""Authoritative DNS data and answering logic (what a root, TLD or domain server does)."""

from __future__ import annotations

from collections import defaultdict

from netlab.dns import message as m
from netlab.dns.message import Message, Record, normalize


class Zone:
    """A zone's records. NS records at a name below the apex are delegations (zone cuts);
    A records below a cut act as glue."""

    def __init__(self, origin: str, soa: m.SoaData | None = None, soa_ttl: int = 3600) -> None:
        self.origin = normalize(origin)
        self.records: dict[tuple[str, int], list[Record]] = defaultdict(list)
        self.soa = soa or m.SoaData(f"ns.{self.origin or 'root'}", f"admin.{self.origin or 'root'}")
        self.records[(self.origin, m.SOA)].append(Record(self.origin, m.SOA, soa_ttl, self.soa))

    def add(self, name: str, rtype: int, data: object, ttl: int = 300) -> "Zone":
        name = normalize(name)
        if not m.in_zone(name, self.origin):
            raise ValueError(f"{name!r} is outside zone {self.origin!r}")
        value = normalize(str(data)) if rtype in (m.NS, m.CNAME) else data
        self.records[(name, rtype)].append(Record(name, rtype, ttl, value))
        return self

    def names(self) -> set[str]:
        return {name for name, _ in self.records}

    def cut_for(self, qname: str) -> str | None:
        """The delegation point at or above ``qname`` (below the apex), if any."""
        labels = qname.split(".") if qname else []
        origin_labels = len(self.origin.split(".")) if self.origin else 0
        for i in range(len(labels) - origin_labels - 1, -1, -1):  # apex-most candidate first
            candidate = ".".join(labels[i:])
            if candidate != self.origin and (candidate, m.NS) in self.records:
                return candidate
        return None


class AuthoritativeServer:
    """Answers queries from one or more zones. Never recurses."""

    def __init__(self, zones: list[Zone]) -> None:
        self.zones = zones
        self.queries_answered = 0

    def zone_for(self, qname: str) -> Zone | None:
        best = None
        for zone in self.zones:
            if m.in_zone(qname, zone.origin) and (best is None or len(zone.origin) > len(best.origin)):
                best = zone
        return best

    def handle(self, query: Message) -> Message:
        self.queries_answered += 1
        if len(query.questions) != 1 or query.flags & m.QR:
            return m.make_response(query, rcode=m.RCODE_FORMERR)
        q = query.questions[0]
        zone = self.zone_for(q.name)
        if zone is None:
            return m.make_response(query, rcode=m.RCODE_REFUSED)

        cut = zone.cut_for(q.name)
        if cut is not None:
            ns = zone.records[(cut, m.NS)]
            return m.make_response(query, authority=ns, additional=self._glue(zone, ns))

        answers: list[Record] = []
        name = q.name
        for _ in range(8):  # follow CNAMEs that stay inside this zone
            direct = zone.records.get((name, q.qtype))
            if direct:
                answers += direct
                break
            cname = zone.records.get((name, m.CNAME))
            if cname and q.qtype != m.CNAME:
                answers += cname
                name = str(cname[0].data)
                if not m.in_zone(name, zone.origin):
                    break
                continue
            break
        if answers:
            return m.make_response(query, answers=answers, authoritative=True)

        soa = zone.records[(zone.origin, m.SOA)]
        if name in zone.names():  # the name exists but has no record of this type
            return m.make_response(query, authority=soa, authoritative=True)
        return m.make_response(query, authority=soa, rcode=m.RCODE_NXDOMAIN, authoritative=True)

    @staticmethod
    def _glue(zone: Zone, ns_records: list[Record]) -> list[Record]:
        glue = []
        for ns in ns_records:
            glue += zone.records.get((str(ns.data), m.A), [])
        return glue
