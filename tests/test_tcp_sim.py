import pytest

from netlab.tcp.sim import MSS_BYTES, jain, simulate


def goodput(res, i=0):
    f = res.flows[i]
    return res.throughput_mbps(f, 5, res.duration)


@pytest.mark.parametrize("cc", ["reno", "cubic", "bbr"])
def test_single_flow_fills_the_pipe(cc):
    res = simulate([cc], bandwidth_mbps=10, rtt_ms=40, buffer_pkts=60, duration=30)
    assert goodput(res) > 6.5, cc
    assert res.flows[0].acked_total > 0


def test_reno_shows_slow_start_then_sawtooth():
    res = simulate(["reno"], bandwidth_mbps=10, rtt_ms=40, buffer_pkts=40, duration=30)
    f = res.flows[0]
    cwnd = [c for _, c, _, _ in f.trace]
    assert max(cwnd[:60]) > 30                 # exponential growth in the first second
    assert f.retransmissions > 0               # drop-tail overflow causes loss
    # multiplicative decrease: some sample is below 0.7x of an earlier peak
    peak = 0
    dropped = False
    for c in cwnd:
        peak = max(peak, c)
        if c < 0.7 * peak and peak > 20:
            dropped = True
            break
    assert dropped


def test_bufferbloat_big_buffer_inflates_rtt_for_loss_based_tcp():
    small = simulate(["reno"], buffer_pkts=20, duration=30)
    large = simulate(["reno"], buffer_pkts=400, duration=30)
    def mean_rtt(res):
        s = [r for _, r in res.flows[0].rtt_samples if r]
        return sum(s[len(s) // 2:]) / len(s[len(s) // 2:])
    assert mean_rtt(large) > 3 * mean_rtt(small)


def test_two_reno_flows_share_fairly():
    res = simulate(["reno", "reno"], buffer_pkts=60, duration=60)
    shares = [res.throughput_mbps(f, 10, 60) for f in res.flows]
    assert jain(shares) > 0.9
    assert sum(shares) > 8


def test_random_loss_hurts_loss_based_more_than_bbr():
    reno = simulate(["reno"], random_loss=0.01, duration=30)
    bbr = simulate(["bbr"], random_loss=0.01, duration=30)
    assert goodput(bbr) > 2 * goodput(reno)


def test_jain_index_bounds():
    assert jain([1, 1]) == pytest.approx(1.0)
    assert jain([1, 0]) == pytest.approx(0.5)
    assert jain([]) == 0.0
