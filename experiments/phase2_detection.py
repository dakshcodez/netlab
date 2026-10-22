"""How strong is each error-detection scheme? Undetected-error rate vs burst length, for random
bit errors, and against adversarial edits; plus Hamming(7,4) correction.

Simulation only:

    uv run python -m experiments.phase2_detection
"""

from __future__ import annotations

import argparse
import random

from netlab.common.plot import COLORS, line_plot
from netlab.common.results import RESULTS_DIR, Result
from netlab.reliability import detect, inject

MESSAGE_BYTES = 64


def undetected_rate(scheme: detect.Scheme, corrupt, trials: int, rng: random.Random) -> float:
    """Fraction of corrupted (data, tag) frames that still verify. Errors hit data and tag alike."""
    missed = 0
    for _ in range(trials):
        data = rng.randbytes(MESSAGE_BYTES)
        tag = scheme.tag(data)
        frame = corrupt(data + tag, rng)
        if frame == data + tag:
            continue  # a no-op "error" is not an error
        if scheme.verify(frame[:MESSAGE_BYTES], frame[MESSAGE_BYTES:]):
            missed += 1
    return missed / trials


def hamming_study(trials: int, rng: random.Random) -> list[dict]:
    rows = []
    for k in (0, 1, 2, 3):
        corrected = wrong = 0
        for _ in range(trials):
            nibble = rng.randrange(16)
            word = detect.hamming74_encode(nibble)
            for pos in rng.sample(range(7), k):
                word ^= 1 << pos
            got, _ = detect.hamming74_decode(word)
            if got == nibble:
                corrected += 1
            else:
                wrong += 1
        rows.append({"bit_errors": k, "decoded_correctly": corrected / trials, "decoded_wrong": wrong / trials})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trials", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    rng = random.Random(args.seed)

    result = Result(phase="phase2", experiment="detection", level="sim",
                    params={"message_bytes": MESSAGE_BYTES, "trials": args.trials, "seed": args.seed})
    lengths = [1, 2, 3, 4, 5, 8, 12, 16, 24, 32, 33, 40, 48, 64]
    series: dict[str, list[float]] = {name: [] for name in detect.SCHEMES}
    for length in lengths:
        for name, scheme in detect.SCHEMES.items():
            rate = undetected_rate(scheme, lambda f, r, n=length: inject.burst_error(f, n, r), args.trials, rng)
            series[name].append(rate)
            result.add(kind="burst", burst_bits=length, scheme=name, undetected_rate=rate)

    floor = 1 / args.trials  # log plot cannot show zero: plot "none seen" at half a trial
    line_plot(
        [{"x": lengths, "y": [max(v, floor / 2) for v in series[n]], "label": n, "color": COLORS[n]}
         for n in series],
        RESULTS_DIR / "phase2" / "detection_burst.png",
        f"Undetected burst errors ({args.trials} trials per point; bottom = none seen)",
        "burst length (bits)", "undetected fraction", logy=True)

    bers = [1e-3, 1e-2, 5e-2]
    for ber in bers:
        for name, scheme in detect.SCHEMES.items():
            rate = undetected_rate(scheme, lambda f, r, b=ber: inject.random_bit_errors(f, b, r), args.trials, rng)
            result.add(kind="random", ber=ber, scheme=name, undetected_rate=rate)

    # adversarial: swapped 16-bit words / add-and-subtract
    for label, edit in (("swap two words", lambda d, r: inject.swap_words(d, 1, 5)),
                        ("add/subtract between words", lambda d, r: inject.add_and_subtract(d, 2, 7))):
        for name, scheme in detect.SCHEMES.items():
            tally = 0
            for _ in range(2000):
                data = rng.randbytes(MESSAGE_BYTES)
                edited = edit(data, rng)
                if edited != data and scheme.verify(edited, scheme.tag(data)):
                    tally += 1
            result.add(kind="adversarial", edit=label, scheme=name, undetected_rate=tally / 2000)

    result.summary = {"hamming74": hamming_study(args.trials, rng)}
    path = result.save()

    print("burst length →", *[f"{n:>6}" for n in lengths])
    for name, vals in series.items():
        print(f"{name:<10}", *[f"{v:6.3f}" if v else "     0" for v in vals])
    print("\nadversarial edits (fraction undetected):")
    for row in (r for r in result.rows if r["kind"] == "adversarial"):
        print(f"  {row['edit']:<28} {row['scheme']:<10} {row['undetected_rate']:.3f}")
    print("\nHamming(7,4):", *[f"{r['bit_errors']} err → ok {r['decoded_correctly']:.2f}" for r in result.summary["hamming74"]])
    print(f"saved {path}")


if __name__ == "__main__":
    main()
