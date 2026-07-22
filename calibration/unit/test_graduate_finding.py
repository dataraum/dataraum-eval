"""graduate_finding scaffold (Phase 2) — pure generators + guarded writes, Tier 1.

Exercises the deterministic scaffolding (slug, target parse, the three stubs) and the
eval-owned writes (oracle stub + backlog append) against tmp paths — no cross-repo
edits, no pipeline.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from calibration import graduate_finding as gf
from calibration.findings import Finding


def _finding(**over: object) -> Finding:
    base: dict[str, object] = {
        "id": "rel-f1-orphan-drivers",
        "kind": "miss",
        "title": "relationship_entropy misses the 20% orphan FK",
        "vertical": "finance",
        "dataset": "detection-v1",
        "target": "payments.invoice_id",
        "named_statistic": "orphan-rate",
        "evidence": "orphan-rate 0.20 injected vs 0.00 clean; detector scored 0.0",
        "disposition": "graduate",
        "source": "detection-v1",
        "detector_id": "relationship_entropy",
        "repro": "calibration/unit/test_rel_f1_orphan_drivers.py::test_x",
    }
    base.update(over)
    return Finding.from_dict(base)


def test_slug_and_target_parse() -> None:
    assert gf.slug("rel-f1-orphan-drivers") == "rel_f1_orphan_drivers"
    assert gf.parse_target("payments.invoice_id") == ("payments", "invoice_id")
    with pytest.raises(ValueError, match="not a table.column"):
        gf.parse_target("total_revenue")


def test_stubs_carry_the_finding_details() -> None:
    f = _finding()
    s = gf.slug(f.id)
    inj = gf.injector_stub(f, "payments", "invoice_id", s)
    assert f"def inject_{s}(" in inj and 'detector_id="relationship_entropy"' in inj
    strat = gf.strategy_entry(f, "payments", "invoice_id", s)
    assert f"injector: inject_{s}" in strat and "table: payments" in strat
    oracle = gf.oracle_stub(f, s)
    assert "@pytest.mark.skip" in oracle and f"def test_{s}_separates(" in oracle


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    unit, backlog = tmp_path / "unit", tmp_path / "backlog.yaml"
    unit.mkdir()
    backlog.write_text("items:\n  - id: EXISTING\n    kind: capability\n")
    report = gf.graduate(_finding(), dry_run=True, unit_dir=unit, backlog_path=backlog)
    assert "DRY-RUN" in report
    assert list(unit.iterdir()) == []
    assert "EXISTING" in backlog.read_text() and "orphan" not in backlog.read_text()


def test_write_creates_oracle_and_appends_backlog(tmp_path: Path) -> None:
    unit, backlog = tmp_path / "unit", tmp_path / "backlog.yaml"
    unit.mkdir()
    backlog.write_text("items:\n  - id: EXISTING\n    kind: capability\n")
    f = _finding()

    gf.graduate(f, dry_run=False, unit_dir=unit, backlog_path=backlog)

    oracle = unit / "test_rel_f1_orphan_drivers.py"
    assert oracle.exists() and "@pytest.mark.skip" in oracle.read_text()
    assert f.status == "graduated" and f.graduated_to.endswith("::test_rel_f1_orphan_drivers_separates")

    data = yaml.safe_load(backlog.read_text())
    ids = [i["id"] for i in data["items"]]
    assert ids == ["EXISTING", "rel-f1-orphan-drivers"]
    graduated = next(i for i in data["items"] if i["id"] == "rel-f1-orphan-drivers")
    assert graduated["status"] == "graduated" and graduated["kind"] == "finding"


def test_refuses_a_rumor(tmp_path: Path) -> None:
    unit, backlog = tmp_path / "unit", tmp_path / "backlog.yaml"
    unit.mkdir()
    backlog.write_text("items: []\n")
    with pytest.raises(ValueError, match="no repro"):
        gf.graduate(_finding(repro=""), dry_run=False, unit_dir=unit, backlog_path=backlog)


def test_refuses_to_clobber_an_existing_oracle(tmp_path: Path) -> None:
    unit, backlog = tmp_path / "unit", tmp_path / "backlog.yaml"
    unit.mkdir()
    backlog.write_text("items: []\n")
    (unit / "test_rel_f1_orphan_drivers.py").write_text("# already here\n")
    with pytest.raises(FileExistsError, match="refusing to clobber"):
        gf.graduate(_finding(), dry_run=False, unit_dir=unit, backlog_path=backlog)
