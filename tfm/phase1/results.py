"""DAT-743 Phase 1: append-only results store.

One JSONL row per (probe, engine, config) measurement:
    {probe, engine, config: {...}, metrics: {...}, latency_s, note}
Rows are the scorecard's raw material (Phase 3 reads them back as a frame);
nothing here aggregates or ranks — that is the report's job.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

RESULTS_DIR = Path(__file__).resolve().parents[1] / "output" / "phase1"


def results_path(probe: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    return RESULTS_DIR / f"{probe}.jsonl"


def record(
    probe: str,
    engine: str,
    config: dict[str, Any],
    metrics: dict[str, Any],
    latency_s: float | None = None,
    note: str = "",
) -> None:
    row = {
        "probe": probe,
        "engine": engine,
        "config": config,
        "metrics": metrics,
        "latency_s": None if latency_s is None else round(latency_s, 3),
        "note": note,
    }
    with results_path(probe).open("a") as fh:
        fh.write(json.dumps(row, default=str) + "\n")
    label = ", ".join(f"{k}={_fmt(v)}" for k, v in metrics.items() if not isinstance(v, dict))
    lat = "" if latency_s is None else f" ({latency_s:.1f}s)"
    print(f"[{probe}] {engine} {config}: {label}{lat}")


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


@contextmanager
def timed() -> Iterator[dict[str, float]]:
    """with timed() as t: ...; t['s'] holds the elapsed wall-clock seconds."""
    box: dict[str, float] = {}
    t0 = time.perf_counter()
    try:
        yield box
    finally:
        box["s"] = time.perf_counter() - t0


def load(probe: str) -> pd.DataFrame:
    path = results_path(probe)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_json(path, lines=True)
