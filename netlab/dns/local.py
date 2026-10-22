"""The whole DNS hierarchy on one machine (127.0.1.x), for tests and the loopback experiments.

Each server replies ``one_way_ms * 2`` late so a query to it costs one round trip of emulated
network distance, the same effect netem delay has on the testbed.
"""

from __future__ import annotations

from contextlib import contextmanager

from netlab.dns.hierarchy import Addresses, build_servers
from netlab.dns.resolver import Resolver, SequentialTxid, UdpTransport, random_txid
from netlab.dns.server import UdpServer, recursive_handler

ADDR = Addresses(root="127.0.1.1", tld="127.0.1.2", example="127.0.1.3")
RESOLVER_IP = "127.0.1.9"


@contextmanager
def local_hierarchy(port: int = 5353, hop_rtt_ms: float = 0.0, client_rtt_ms: float = 0.0,
                    weak: bool = False, **zone_kw):
    """Yield (resolver, resolver_ip, port) with root, TLD, example and the resolver running."""
    servers = build_servers(ADDR, **zone_kw)
    started = [UdpServer(servers["root"].handle, ADDR.root, port, hop_rtt_ms, "root"),
               UdpServer(servers["tld"].handle, ADDR.tld, port, hop_rtt_ms, "tld"),
               UdpServer(servers["example"].handle, ADDR.example, port, hop_rtt_ms, "example")]
    transport = UdpTransport(port=port, timeout=2.0, fixed_source_port=44444 + port % 1000 if weak else None,
                             bind_ip="127.0.0.1")
    resolver = Resolver([ADDR.root], transport, txid=SequentialTxid() if weak else random_txid)
    started.append(UdpServer(recursive_handler(resolver), RESOLVER_IP, port, client_rtt_ms, "resolver"))
    for s in started:
        s.start()
    try:
        yield resolver, RESOLVER_IP, port
    finally:
        for s in started:
            s.stop()
