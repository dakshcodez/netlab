"""Parse ``ss -ti`` output (Linux TCP internals) into cwnd / RTT samples."""

from __future__ import annotations

import re

_KV = re.compile(r"(\w+):([\w./,-]+)")


def parse_ss(text: str) -> list[dict]:
    """Return one dict per connection block with numeric cwnd, ssthresh, rtt_ms, retrans etc.

    ``ss -tin`` prints a header line per connection followed by an indented line of
    ``key:value`` fields. Keys we use: ``cwnd``, ``ssthresh`` (absent until the first loss),
    ``rtt:<srtt>/<var>``, ``retrans:<now>/<total>``, ``bytes_acked``, ``delivery_rate``.
    """
    samples = []
    for line in text.splitlines():
        if "cwnd:" not in line:
            continue
        fields = dict(_KV.findall(line))
        sample: dict = {"cc": next((w for w in line.split() if w in ("reno", "cubic", "bbr", "bbr2", "vegas")), None),
                        "cwnd": int(fields["cwnd"])}
        if "ssthresh" in fields:
            sample["ssthresh"] = int(fields["ssthresh"])
        if "rtt" in fields:
            sample["rtt_ms"] = float(fields["rtt"].split("/")[0])
        if "retrans" in fields:
            sample["retrans_total"] = int(fields["retrans"].split("/")[-1])
        if "bytes_acked" in fields:
            sample["bytes_acked"] = int(fields["bytes_acked"])
        samples.append(sample)
    return samples


def parse_timed_log(text: str) -> list[dict]:
    """Parse a log made by ``while :; do date +%s.%N; ss -tin ...; sleep 0.1; done``: a bare
    timestamp line precedes each ss snapshot. Times are returned relative to the first sample."""
    out, t = [], None
    block: list[str] = []

    def flush() -> None:
        if t is not None and block:
            for s in parse_ss("\n".join(block)):
                out.append({"t": t, **s})

    for line in text.splitlines():
        if re.fullmatch(r"\d+\.\d+", line.strip()):
            flush()
            t, block = float(line.strip()), []
        else:
            block.append(line)
    flush()
    if out:
        t0 = out[0]["t"]
        for s in out:
            s["t"] = round(s["t"] - t0, 3)
    return out
