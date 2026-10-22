"""Why resolvers randomize query identifiers: how much an off-path party has to guess.

A response is only accepted if its 16-bit transaction ID matches, and it reaches the right
source port. These helpers quantify the search space for each resolver configuration so the
report can compare them; there is no attack code here.
"""

from __future__ import annotations

import math

EPHEMERAL_PORTS = 65536 - 1024


def search_space(sequential_txid: bool, fixed_port: bool) -> int:
    txid = 1 if sequential_txid else 65536
    port = 1 if fixed_port else EPHEMERAL_PORTS
    return txid * port


def entropy_bits(sequential_txid: bool, fixed_port: bool) -> float:
    return math.log2(search_space(sequential_txid, fixed_port))


CONFIGS = [
    ("weak: sequential ID, fixed port", True, True),
    ("random ID, fixed port", False, True),
    ("random ID + random port", False, False),
]
