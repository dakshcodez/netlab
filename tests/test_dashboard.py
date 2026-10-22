from pathlib import Path

import pytest

from netlab.dashboard import runners


def test_arq_runner_theory_and_sim_agree_lossless():
    out = runners.arq_vs_loss(["sw", "gbn", "sr"], a=5, window=16, losses=[0.0], packets=300, seeds=(1,))
    assert out["sw"]["sim"][0] == pytest.approx(out["sw"]["theory"][0], rel=0.05)
    assert out["sr"]["sim"][0] > 0.9


def test_detection_runner_shape():
    out = runners.detection_vs_burst([1, 8], trials=200)
    assert set(out) == {"parity", "2d-parity", "checksum", "crc32"}
    assert out["crc32"] == [0.0, 0.0] and out["parity"][0] == 0.0


def test_tcp_runner_reports_fairness_for_two_flows():
    out = runners.tcp_run(["reno", "reno"], 10, 40, 60, 0.0, 20)
    assert len(out["table"]) == 2 and 0.5 <= out["jain"] <= 1.0


def test_dns_runner_cold_slower_than_warm():
    rows = {r["lookup"]: r["ms"] for r in runners.dns_run(15, 1)}
    assert rows["cold: www.example.lab"] > 2 * rows["warm: www.example.lab"]


def test_testbed_gate_without_root():
    ok, why = runners.testbed_available()
    assert isinstance(ok, bool) and why


def test_app_renders_every_page():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    for page in ("ARQ: efficiency vs loss", "TCP congestion control", "DNS cold vs cached",
                 "Error detection strength", "Testbed experiments", "Browse saved results"):
        at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "dashboard" / "app.py"), default_timeout=60)
        at.run()
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception, (page, at.exception)
