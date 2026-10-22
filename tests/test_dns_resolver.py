import pytest

from netlab.dns import message as m
from netlab.dns.hierarchy import Addresses, WWW_IP, build_servers
from netlab.dns.resolver import Resolver

ROOT, TLD, EX = "10.0.0.1", "10.0.0.2", "10.0.0.3"


class Net:
    """Direct in-memory transport that records which servers were asked."""

    def __init__(self, servers):
        self.servers = servers
        self.log = []

    def exchange(self, server, wire, accept, timeout):
        q = m.Message.decode(wire)
        self.log.append((server, q.questions[0].name))
        reply = self.servers[server].handle(q).encode()
        return reply if accept(reply) else None


@pytest.fixture
def world():
    servers = build_servers(Addresses(ROOT, TLD, EX), ttl=300, negative_ttl=30)
    net = Net({ROOT: servers["root"], TLD: servers["tld"], EX: servers["example"]})
    clock = [0.0]
    return Resolver([ROOT], net, clock=lambda: clock[0]), net, clock


def query(server, name, qtype=m.A):
    return server.handle(m.make_query(name, qtype, 1, recursion_desired=False))


def test_authoritative_answers_referrals_nxdomain_and_nodata():
    s = build_servers(Addresses(ROOT, TLD, EX))
    ans = query(s["example"], "www.example.lab")
    assert ans.authoritative and [r.data for r in ans.answers] == [WWW_IP]
    ref = query(s["root"], "www.example.lab")
    assert not ref.answers and ref.authority[0].name == "lab" and ref.additional[0].data == TLD
    assert not ref.authoritative
    nx = query(s["example"], "nope.example.lab")
    assert nx.rcode == m.RCODE_NXDOMAIN and nx.authority[0].rtype == m.SOA
    nodata = query(s["example"], "www.example.lab", m.NS)
    assert nodata.rcode == 0 and not nodata.answers and nodata.authority[0].rtype == m.SOA
    cname = query(s["example"], "alias.example.lab")
    assert [r.rtype for r in cname.answers] == [m.CNAME, m.A]
    assert query(s["example"], "www.other.org").rcode == m.RCODE_REFUSED


def test_cold_lookup_walks_root_tld_auth_then_warm_is_cached(world):
    r, net, clock = world
    cold = r.resolve("www.example.lab")
    assert cold.addresses() == [WWW_IP] and not cold.cached
    assert [s for s, _ in net.log] == [ROOT, TLD, EX]
    warm = r.resolve("www.example.lab")
    assert warm.addresses() == [WWW_IP] and warm.cached and len(net.log) == 3


def test_sibling_lookup_reuses_cached_delegations(world):
    r, net, _ = world
    r.resolve("www.example.lab")
    net.log.clear()
    assert r.resolve("mail.example.lab").addresses() == ["10.20.0.11"]
    assert [s for s, _ in net.log] == [EX]  # skips root and TLD


def test_ttl_expiry_forces_requery_and_ttl_counts_down(world):
    r, net, clock = world
    r.resolve("www.example.lab")
    clock[0] = 100
    ans = r.resolve("www.example.lab")
    assert ans.cached and ans.answers[0].ttl == 200
    clock[0] = 301
    net.log.clear()
    assert not r.resolve("www.example.lab").cached
    assert [s for s, _ in net.log] == [EX]  # delegations (TTL 86400) are still cached


def test_negative_caching_uses_soa_minimum(world):
    r, net, clock = world
    first = r.resolve("ghost.example.lab")
    assert first.rcode == m.RCODE_NXDOMAIN
    n = len(net.log)
    again = r.resolve("ghost.example.lab")
    assert again.rcode == m.RCODE_NXDOMAIN and again.cached and len(net.log) == n
    clock[0] = 31  # SOA minimum is 30 s
    assert not r.resolve("ghost.example.lab").cached


def test_cname_chain_resolved_and_nodata_cached(world):
    r, _, _ = world
    res = r.resolve("alias.example.lab")
    assert res.addresses() == [WWW_IP] and res.answers[0].rtype == m.CNAME
    assert r.resolve("alias.example.lab").cached
    nodata = r.resolve("www.example.lab", m.NS)
    assert nodata.rcode == 0 and not nodata.answers


def test_resolver_ignores_out_of_bailiwick_referral():
    class Liar:
        def handle(self, q):
            return m.make_response(q, authority=[m.Record("com", m.NS, 99, "ns.evil.com")],
                                   additional=[m.Record("ns.evil.com", m.A, 99, "6.6.6.6")])
    servers = build_servers(Addresses(ROOT, TLD, EX))
    net = Net({ROOT: servers["root"], TLD: Liar()})
    r = Resolver([ROOT], net)
    assert r.resolve("www.example.lab").rcode == m.RCODE_SERVFAIL
    assert r.cache.get("com", m.NS) is None
