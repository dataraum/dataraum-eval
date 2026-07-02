"""Tier-1 pin for the clean-bands degeneracy lint (DAT-602 round 1).

A CONTINUOUS statistic must vary across reseeded clean data — a zero-width band
over >= 2 seeds means the detector is not reading the data. Both round-1 bugs
were visible in clean_bands.yaml as exactly that signature while every test was
green: temporal_behavior 0.5127 x3 (mis-wired) and unit_entropy 1.0 x3 (the
DAT-647 false-block). The lint turns the signature from a blessed baseline into
a build failure; this pins it on synthetic sweep docs.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_clean_bands.py"
_spec = importlib.util.spec_from_file_location("build_clean_bands", _SCRIPT)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
build_from_docs = _mod.build_from_docs


def _doc(seed: int, column: dict[str, float]) -> dict[str, Any]:
    return {"seed": seed, "column": column, "table": {}, "relationship": {}}


def test_constant_continuous_band_is_flagged() -> None:
    docs = [_doc(s, {"t.c:temporal_behavior": 0.5127}) for s in (46, 47, 48)]
    doc, degenerate = build_from_docs(docs)
    assert doc["bands"]["column"]["t.c:temporal_behavior"] == {
        "min": 0.5127,
        "max": 0.5127,
        "seen": 3,
    }
    assert len(degenerate) == 1
    assert "t.c:temporal_behavior" in degenerate[0]


def test_discrete_by_design_detector_is_exempt() -> None:
    docs = [_doc(s, {"t.c:unit_source": 1.0}) for s in (46, 47)]
    _, degenerate = build_from_docs(docs)
    assert degenerate == []


def test_varying_band_is_not_flagged() -> None:
    docs = [
        _doc(46, {"t.c:benford": 0.2315}),
        _doc(47, {"t.c:benford": 0.3005}),
    ]
    doc, degenerate = build_from_docs(docs)
    assert doc["bands"]["column"]["t.c:benford"] == {"min": 0.2315, "max": 0.3005, "seen": 2}
    assert degenerate == []


def test_single_seed_key_is_not_flagged() -> None:
    # 'seen' < number of seeds: emitted once (LLM coverage varies) — one point
    # cannot witness degeneracy.
    docs = [_doc(46, {"t.c:business_meaning": 0.25}), _doc(47, {})]
    doc, degenerate = build_from_docs(docs)
    assert doc["bands"]["column"]["t.c:business_meaning"]["seen"] == 1
    assert degenerate == []


def test_below_floor_keys_record_nothing() -> None:
    docs = [_doc(s, {"t.c:null_ratio": 0.05}) for s in (46, 47)]
    doc, degenerate = build_from_docs(docs)
    assert doc["bands"]["column"] == {}
    assert degenerate == []
