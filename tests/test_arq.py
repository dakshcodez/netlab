import pytest

from netlab.reliability import arq, theory
from netlab.reliability.channel import Channel
from netlab.reliability.sim import simulate, standard_setup

FRAME = arq.OVERHEAD + 100


def run(protocol, window=8, loss=0.0, a=5.0, n=300, seed=1, rev_loss=0.0, **fwd_kw):
    _, delay, timeout = standard_setup(a, FRAME)
    fwd = Channel(delay=delay, loss=loss, rate_bps=1e6, seed=seed, **fwd_kw)
    rev = Channel(delay=delay, loss=rev_loss, seed=seed + 1)
    return simulate(protocol, n, window, timeout, fwd, rev)


def test_frame_roundtrip_and_corruption_detected():
    f = arq.encode(arq.DATA, 7, b"hello")
    assert arq.decode(f) == (arq.DATA, 7, b"hello")
    bad = bytes([f[0] ^ 1]) + f[1:]
    assert arq.decode(bad) is None
    assert arq.decode(b"abc") is None


@pytest.mark.parametrize("protocol", arq.PROTOCOLS)
@pytest.mark.parametrize("loss", [0.0, 0.1, 0.3])
def test_delivers_everything_in_order(protocol, loss):
    r = run(protocol, loss=loss, rev_loss=loss, n=120)
    assert r.finished and r.delivered == 120 and r.wrong_payloads == 0


@pytest.mark.parametrize("protocol", arq.PROTOCOLS)
def test_survives_corruption_duplication_and_reordering(protocol):
    r = run(protocol, loss=0.05, n=120, corrupt=0.1, corrupt_bits=3, duplicate=0.1,
            reorder=0.2, reorder_delay=0.05)
    assert r.finished and r.delivered == 120 and r.wrong_payloads == 0


def test_lossless_efficiency_matches_theory():
    a = 5.0
    sw = run("sw", a=a, n=200)
    assert sw.efficiency == pytest.approx(theory.eff_stop_and_wait(a), rel=0.05)
    gbn = run("gbn", a=a, window=8, n=400)
    assert gbn.efficiency == pytest.approx(8 / (1 + 2 * a), rel=0.05)
    full = run("sr", a=a, window=20, n=600)  # window above 1+2a keeps the pipe full
    assert full.efficiency > 0.9


def test_window_of_one_makes_all_protocols_equal_to_stop_and_wait():
    base = run("sw", n=100).efficiency
    for protocol in ("gbn", "sr"):
        assert run(protocol, window=1, n=100).efficiency == pytest.approx(base, rel=0.05)


def test_selective_repeat_beats_go_back_n_under_loss():
    gbn = run("gbn", window=16, loss=0.1, n=2000)
    sr = run("sr", window=16, loss=0.1, n=2000)
    assert sr.efficiency > gbn.efficiency
    assert sr.retransmissions < gbn.retransmissions


def test_go_back_n_hurt_by_reordering_more_than_selective_repeat():
    kw = dict(window=16, n=1000, reorder=0.2, reorder_delay=3e-3)
    gbn, sr = run("gbn", **kw), run("sr", **kw)
    assert gbn.discarded_out_of_order > 0
    assert sr.efficiency > gbn.efficiency


@pytest.mark.parametrize("protocol,window", [("sw", 1), ("gbn", 4), ("gbn", 16), ("sr", 4), ("sr", 32)])
def test_simulation_tracks_theory_under_loss(protocol, window):
    # SR needs a window of about 2(1+2a) to hide a loss: the window cannot slide until the
    # retransmission is ACKed, which is a timeout plus a round trip after the first copy.
    a, p = 5.0, 0.05
    r = run(protocol, window=window, loss=p, a=a, n=4000, seed=7)
    assert r.efficiency == pytest.approx(theory.efficiency(protocol, a, p, window), rel=0.15)


def test_theory_limits():
    assert theory.eff_selective_repeat(5, 0.1, 100) == pytest.approx(0.9)
    assert theory.eff_go_back_n(5, 0.0, 100) == 1.0
    assert theory.eff_stop_and_wait(5) == pytest.approx(1 / 11)


@pytest.mark.parametrize("protocol", arq.PROTOCOLS)
def test_real_udp_loopback_delivers_with_loss(protocol):
    from netlab.reliability.udp import run_loopback

    frame = arq.OVERHEAD + 200
    rate = 8e6  # 0.2 ms per frame
    tx = frame * 8 / rate
    delay = 5 * tx
    run = run_loopback(protocol, 60, 8, 2 * delay + 5e-3, rate, delay, loss=0.1, payload_size=200)
    assert run.finished and run.delivered == 60 and run.wrong_payloads == 0
