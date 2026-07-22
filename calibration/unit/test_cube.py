"""Tier-1: the cube declaration contract + planner minimality (DAT-860).

The enforcement half is the point: ``test_every_tier3_module_declares`` makes the
cube declaration a REQUIREMENT, not a convention — a new Tier-3 oracle module that
doesn't declare its (vertical, dataset, from_stage) fails the suite. This is the
first structurally-enforced seam the framework review (§2.3) asked for; the six
banked oracle drafts land against it born-declarative.
"""

from __future__ import annotations

import pytest

from calibration import cube
from calibration.cube import Cell, Needs


def test_every_tier3_module_declares() -> None:
    """The adoption ratchet: no undeclared Tier-3 oracle, ever."""
    assert cube.undeclared() == [], (
        "Tier-3 oracle modules without a cube declaration — add "
        "`pytestmark = cube.needs(vertical=..., dataset=..., from_stage=...)` "
        "(calibration/cube.py, DAT-860)"
    )


def test_stage_vocabulary_frozen() -> None:
    """The chain order IS the contract (depth computation + cache write path)."""
    assert cube.STAGES == ("raw", "add_source", "begin_session", "operating_model")


def test_needs_rejects_unknown_stage() -> None:
    with pytest.raises(ValueError, match="from_stage"):
        cube.needs(vertical="finance", dataset="*", from_stage="typing")


def test_needs_rejects_empty_dataset_tuple() -> None:
    with pytest.raises(ValueError, match="dataset"):
        cube.needs(vertical="finance", dataset=(), from_stage="raw")


def test_needs_binding_forms() -> None:
    """"*" binds anything; a str binds one; a tuple binds its members."""
    any_ds: Needs = cube.needs(
        vertical="finance", dataset="*", from_stage="raw"
    ).mark.kwargs["spec"]
    one: Needs = cube.needs(
        vertical="finance", dataset="detection-stockflow-v1", from_stage="raw"
    ).mark.kwargs["spec"]
    assert any_ds.binds("clean") and any_ds.binds("detection-v1")
    assert one.binds("detection-stockflow-v1") and not one.binds("clean")


def test_plan_minimality_baseline_pull_and_vertical_isolation() -> None:
    """Depth = deepest consumed stage; baselines pulled at the oracle's stage;
    dataset-specific and other-vertical oracles never bind."""
    reg = {
        "o_raw": Needs(vertical="finance", datasets=None, from_stage="raw"),
        "o_deep": Needs(
            vertical="finance", datasets=None, from_stage="operating_model",
            baseline=("clean",),
        ),
        "o_bound": Needs(vertical="finance", datasets=("d2",), from_stage="begin_session"),
        "o_other": Needs(vertical="motorsport", datasets=None, from_stage="raw"),
    }

    p = cube.plan(["d1"], reg=reg)
    assert {b.module for b in p.bindings} == {"o_raw", "o_deep"}
    assert p.depth == {"clean": "operating_model", "d1": "operating_model"}
    assert Cell("d1", "raw") in p.cells and Cell("clean", "operating_model") in p.cells
    assert p.pulled_baselines == ["clean"]

    p2 = cube.plan(["d2"], reg=reg)
    assert {b.module for b in p2.bindings} == {"o_raw", "o_deep", "o_bound"}
    assert p2.depth["d2"] == "operating_model"

    # A dataset nothing binds shows up with no depth entry (rendered as a warning).
    p3 = cube.plan(["d9"], reg={"o_bound": reg["o_bound"]})
    assert p3.bindings == [] and p3.depth == {}


def test_plan_baseline_self_reference_not_duplicated() -> None:
    """Grading `clean` itself must not pull `clean` in twice as its own baseline."""
    reg = {
        "o_deep": Needs(
            vertical="finance", datasets=None, from_stage="operating_model",
            baseline=("clean",),
        ),
    }
    p = cube.plan(["clean"], reg=reg)
    assert p.pulled_baselines == []
    assert p.cells == [Cell("clean", "operating_model")]


def test_plan_real_registry_smoke() -> None:
    """The real finance cube plans: stockflow binds only its own dataset,
    ground_truth needs no pipeline, and nothing is undeclared."""
    p = cube.plan(["detection-stockflow-v1"])
    assert p.undeclared == ()
    modules = {b.module for b in p.bindings}
    assert "test_stockflow_recall_teach_e2e" in modules
    assert "test_ground_truth" in modules
    by_module = {b.module: b.cell for b in p.bindings}
    assert by_module["test_ground_truth"].stage == "raw"
    assert by_module["test_stockflow_recall_teach_e2e"].stage == "begin_session"

    p2 = cube.plan(["detection-v1"])
    assert "test_stockflow_recall_teach_e2e" not in {b.module for b in p2.bindings}
    assert p2.pulled_baselines == ["clean"]
    assert "detection-v1" in p2.render()
