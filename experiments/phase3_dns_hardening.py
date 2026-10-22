"""Resolver hardening: unpredictable IDs and source ports versus a predictable resolver.

Measures real properties of our resolver implementation (no attack traffic): how predictable
its transaction IDs and source ports are on the wire, and the size of the space an off-path
party would have to guess.

    uv run python -m experiments.phase3_dns_hardening
"""

from __future__ import annotations

import statistics

from netlab.common.results import Result
from netlab.dns import hardening
from netlab.dns.resolver import SequentialTxid, random_txid


def observed_ids(source, n: int = 2000) -> list[int]:
    return [source() for _ in range(n)]


def predictability(ids: list[int]) -> float:
    """Fraction of IDs equal to previous ID + 1: 1.0 means perfectly guessable."""
    return statistics.mean((b - a) % 65536 == 1 for a, b in zip(ids, ids[1:]))


def main() -> None:
    result = Result(phase="phase3", experiment="dns_hardening", level="sim",
                    params={"samples": 2000})
    seq, rnd = observed_ids(SequentialTxid(100)), observed_ids(random_txid)
    print(f"IDs that are previous+1: sequential {predictability(seq):.3f}, random {predictability(rnd):.4f}")
    for name, sequential, fixed_port in hardening.CONFIGS:
        space = hardening.search_space(sequential, fixed_port)
        bits = hardening.entropy_bits(sequential, fixed_port)
        result.add(config=name, guess_space=space, entropy_bits=round(bits, 1),
                   txid_predictability=round(predictability(seq if sequential else rnd), 4))
        print(f"{name:<34} guess space {space:>14,}  ({bits:4.1f} bits)")
    print(f"saved {result.save()}")


if __name__ == "__main__":
    main()
