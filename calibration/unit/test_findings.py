"""The Finding schema (Phase 2) — validation + backlog transform, Tier 1.

A finding is the charter's unit of complaint: a named statistic + evidence, scoped
to a (vertical, dataset). These tests pin the validation (what the schema refuses)
and the backlog transform — no pytest run, no pipeline.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from calibration.findings import Finding, load_findings


def _valid(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "rel-f1-orphan-drivers",
        "kind": "miss",
        "title": "relationship_entropy misses the 20% orphan FK on drivers",
        "vertical": "finance",
        "dataset": "detection-v1",
        "target": "payments.invoice_id",
        "named_statistic": "orphan-rate",
        "evidence": "orphan-rate 0.20 on injected vs 0.00 clean; detector scored 0.0",
        "disposition": "DAT-ticket",
        "source": "detection-v1",
        "detector_id": "relationship_entropy",
    }
    base.update(over)
    return base


def test_valid_finding_round_trips_and_defaults() -> None:
    f = Finding.from_dict(_valid())
    assert f.status == "open" and f.graduated_to == ""
    item = f.to_backlog_item()
    assert item["kind"] == "finding" and item["status"] == "queued"
    assert item["vertical"] == "finance" and item["detector_id"] == "relationship_entropy"


def test_named_statistic_is_required() -> None:
    with pytest.raises(ValueError, match="named_statistic is required"):
        Finding.from_dict(_valid(named_statistic="  "))


def test_evidence_is_required() -> None:
    with pytest.raises(ValueError, match="evidence is required"):
        Finding.from_dict(_valid(evidence=""))


def test_detector_kind_requires_detector_id() -> None:
    with pytest.raises(ValueError, match="detector_id is required"):
        Finding.from_dict(_valid(detector_id=None))


def test_non_detector_kind_allows_missing_detector_id() -> None:
    f = Finding.from_dict(_valid(kind="wrong-metric", detector_id=None, target="total_revenue"))
    assert f.detector_id is None


def test_bad_kind_and_disposition_rejected() -> None:
    with pytest.raises(ValueError, match="kind"):
        Finding.from_dict(_valid(kind="smells-off"))
    with pytest.raises(ValueError, match="disposition"):
        Finding.from_dict(_valid(disposition="just-fix-it"))


def test_missing_and_unknown_keys_rejected() -> None:
    d = _valid()
    del d["vertical"]
    with pytest.raises(ValueError, match="missing keys.*vertical"):
        Finding.from_dict(d)
    with pytest.raises(ValueError, match="unknown keys.*severity"):
        Finding.from_dict(_valid(severity="high"))


def test_graduated_finding_reports_graduated_in_backlog() -> None:
    f = Finding.from_dict(_valid(status="graduated", graduated_to="inject_orphan_fk :: test_x"))
    assert f.to_backlog_item()["status"] == "graduated"


def test_load_findings_reads_the_findings_list(tmp_path: Path) -> None:
    path = tmp_path / "findings.yaml"
    path.write_text(yaml.safe_dump({"strategy": "detection-v1", "findings": [_valid()]}))
    loaded = load_findings(path)
    assert len(loaded) == 1 and loaded[0].id == "rel-f1-orphan-drivers"


def test_load_findings_rejects_a_file_without_findings_list(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump({"strategy": "detection-v1"}))
    with pytest.raises(ValueError, match="no top-level `findings:` list"):
        load_findings(path)
