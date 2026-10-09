"""Shared results format used by every phase.

Each experiment run is saved as ``results/<phase>/<experiment>.json`` containing the
parameters, a list of row dicts and optional summary metrics. The dashboard and report
read this format, so keep it stable and change it only on ``main``.
"""

from __future__ import annotations

import csv
import json
import platform
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"


@dataclass
class Result:
    phase: str
    experiment: str
    params: dict[str, Any] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    level: str = "sim"  # "theory" | "sim" | "real"
    created: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    host: str = field(default_factory=platform.node)

    def add(self, **row: Any) -> None:
        self.rows.append(row)

    def save(self, results_dir: Path | None = None) -> Path:
        """Write JSON (full record) and CSV (rows only). Returns the JSON path."""
        out_dir = (results_dir or RESULTS_DIR) / self.phase
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / f"{self.experiment}.json"
        json_path.write_text(json.dumps(asdict(self), indent=2, default=str))
        if self.rows:
            fieldnames = list(dict.fromkeys(k for row in self.rows for k in row))
            with open(out_dir / f"{self.experiment}.csv", "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self.rows)
        return json_path


def load(phase: str, experiment: str, results_dir: Path | None = None) -> Result:
    path = (results_dir or RESULTS_DIR) / phase / f"{experiment}.json"
    return Result(**json.loads(path.read_text()))


def list_results(results_dir: Path | None = None) -> list[tuple[str, str]]:
    """Return (phase, experiment) pairs for every saved result."""
    root = results_dir or RESULTS_DIR
    return sorted((p.parent.name, p.stem) for p in root.glob("*/*.json"))
