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


def _doc(seed: int, values: dict[str, float], grain: str = "column") -> dict[str, Any]:
    doc: dict[str, Any] = {"seed": seed, "column": {}, "table": {}, "relationship": {}}
    doc[grain] = values
    return doc


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


def test_below_floor_constant_is_flagged_but_not_recorded() -> None:
    docs = [_doc(s, {"t.c:null_ratio": 0.05}) for s in (46, 47)]
    doc, degenerate = build_from_docs(docs)
    assert doc["bands"]["column"] == {}
    # Recording semantics are unchanged: a below-floor key never enters the
    # bands artifact. But this value is also CONSTANT across seeds for a
    # non-exempt detector — exactly the join_path_determinism signature the
    # lint exists to catch — so it must now be flagged. Before the fix, the
    # floor's `continue` short-circuited the degeneracy check before it ran;
    # the fix decouples the two, so this case is flagged like any other.
    assert len(degenerate) == 1
    assert "t.c:null_ratio" in degenerate[0]


def test_constant_at_floor_boundary_is_flagged_and_not_recorded() -> None:
    # The join_path_determinism bug signature: a non-exempt detector emitting
    # exactly the floor value (0.1) on every relationship of every corpus.
    # max(values) <= _FLOOR is still true at the boundary, so it must not be
    # recorded — but it must be flagged, since the old `continue` swallowed
    # exactly this case.
    docs = [_doc(s, {"r1:join_path_determinism": 0.1}, grain="relationship") for s in (46, 47, 48)]
    doc, degenerate = build_from_docs(docs)
    assert doc["bands"]["relationship"] == {}
    assert len(degenerate) == 1
    assert "r1:join_path_determinism" in degenerate[0]
    assert "constant 0.1" in degenerate[0]


def test_varying_below_floor_values_not_flagged_not_recorded() -> None:
    docs = [
        _doc(46, {"t.c:null_ratio": 0.05}),
        _doc(47, {"t.c:null_ratio": 0.08}),
    ]
    doc, degenerate = build_from_docs(docs)
    assert doc["bands"]["column"] == {}
    assert degenerate == []


def test_constant_zero_is_the_clean_baseline_not_flagged() -> None:
    # A correct continuous detector reads exactly 0.0 on clean — no entropy to
    # find. That is the ideal clean band, NOT the join_path_determinism smell
    # (a constant NONZERO fallback). It must be neither recorded (0 <= _FLOOR)
    # NOR flagged (ruling 2026-07-22: correct is 0.0, not a floor value).
    docs = [_doc(s, {"t.c:cross_table_consistency": 0.0}) for s in (46, 47, 48)]
    doc, degenerate = build_from_docs(docs)
    assert doc["bands"]["column"] == {}
    assert degenerate == []


def test_seed_invariant_key_on_a_live_detector_not_flagged() -> None:
    # Degeneracy is a property of the DETECTOR, not a single key. null_ratio here
    # VARIES across keys (0.5 on one column, a constant 0.0833 on a fixed-dimension
    # column) — it is reading the data. The lone constant key is a seed-invariant
    # INPUT (a fixed dimension's null rate), not a wiring bug, so it must NOT be
    # flagged. A per-key lint false-flagged exactly this (DAT-853 validation).
    docs = [
        _doc(s, {"fact.col:null_ratio": 0.5, "dim.parent_id:null_ratio": 0.0833})
        for s in (46, 47, 48)
    ]
    _, degenerate = build_from_docs(docs)
    assert degenerate == []


def test_detector_stuck_at_one_nonzero_value_across_all_keys_is_flagged() -> None:
    # The join_path_determinism signature at full scale: the SAME nonzero value on
    # every key — the detector is not reading the data. Must flag (both keys named).
    docs = [
        _doc(s, {"r1:join_path_determinism": 0.1, "r2:join_path_determinism": 0.1}, grain="relationship")
        for s in (46, 47, 48)
    ]
    _, degenerate = build_from_docs(docs)
    assert len(degenerate) == 1
    assert "r1:join_path_determinism" in degenerate[0]
    assert "r2:join_path_determinism" in degenerate[0]
    assert "constant 0.1" in degenerate[0]
