from netlab.common.results import Result, list_results, load


def test_roundtrip(tmp_path):
    r = Result(phase="phase0", experiment="demo", params={"loss": 0.1}, level="sim")
    r.add(x=1, y=2.5)
    r.add(x=2, y=3.5, note="extra column")
    r.save(tmp_path)

    loaded = load("phase0", "demo", tmp_path)
    assert loaded.params == {"loss": 0.1}
    assert loaded.rows[1]["note"] == "extra column"
    assert (tmp_path / "phase0" / "demo.csv").read_text().startswith("x,y,note")
    assert list_results(tmp_path) == [("phase0", "demo")]
