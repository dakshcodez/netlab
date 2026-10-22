from netlab.dns import client, message as m
from netlab.dns.hierarchy import WWW_IP
from netlab.dns.local import local_hierarchy


def test_real_udp_cold_vs_warm_and_nxdomain():
    with local_hierarchy(port=5391, hop_rtt_ms=20) as (resolver, ip, port):
        cold_msg, cold = client.lookup(ip, "www.example.lab", port=port)
        warm_msg, warm = client.lookup(ip, "www.example.lab", port=port)
        assert cold_msg.rcode == 0 and [r.data for r in cold_msg.answers] == [WWW_IP]
        assert warm_msg.answers[0].data == WWW_IP
        assert cold > 0.055          # three upstream round trips of 20 ms
        assert warm < cold / 3       # served from the cache
        nx, _ = client.lookup(ip, "ghost.example.lab", port=port)
        assert nx.rcode == m.RCODE_NXDOMAIN and nx.flags & m.RA
        assert resolver.cache.hits >= 1
