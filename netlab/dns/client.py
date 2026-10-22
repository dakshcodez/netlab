"""A minimal DNS stub client that times each lookup.

    python3 -m netlab.dns.client www.example.lab --server 10.0.0.9 --repeat 3
"""

from __future__ import annotations

import argparse
import json
import secrets
import select
import socket
import time

from netlab.dns import message as m


def lookup(server: str, name: str, qtype: int = m.A, port: int = 53, timeout: float = 3.0) -> tuple[m.Message | None, float]:
    """Send a recursive query. Returns (response or None, seconds)."""
    txid = secrets.randbelow(65536)
    wire = m.make_query(name, qtype, txid).encode()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        start = time.monotonic()
        sock.sendto(wire, (server, port))
        deadline = start + timeout
        while (left := deadline - time.monotonic()) > 0:
            if not select.select([sock], [], [], left)[0]:
                break
            data, addr = sock.recvfrom(4096)
            try:
                msg = m.Message.decode(data)
            except m.DnsError:
                continue
            if addr[0] == server and msg.id == txid:
                return msg, time.monotonic() - start
    return None, time.monotonic() - start


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name")
    parser.add_argument("--server", required=True)
    parser.add_argument("--port", type=int, default=53)
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    out = []
    for _ in range(args.repeat):
        msg, secs = lookup(args.server, args.name, port=args.port)
        out.append({"name": args.name, "rtt_ms": round(secs * 1000, 3),
                    "rcode": None if msg is None else msg.rcode,
                    "answers": [] if msg is None else [str(r.data) for r in msg.answers]})
    print(json.dumps(out))


if __name__ == "__main__":
    main()
