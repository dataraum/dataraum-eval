"""Seed-validation parity — the sweep-#2 gate (P10/DAT-735; the Q3 ruling applied).

The nine finance seed validations must regenerate **verdict-identical** from the DB
home vs the pre-migration YAML path. This grade DECIDES the YAML deletion. The Q3
ruling splits the claim by verdict leg:

* **Deterministic legs (per-draw exact, HARD, this module):** the set-of-nine
  identity — every YAML ``validation_id`` present as a ``source='seed'`` DB row
  with matching ``check_type`` / ``severity`` / ``category`` / ``version``, and
  nothing seeded that the YAML home doesn't declare. Any flap here IS a migration
  bug. Prompt-shaping text drift (description / expected_outcome / sql_hints)
  is REPORTED with a per-field diff count — deliberate contract growth is
  sweep-attention material, not an auto-fail, but it is exactly what moves the
  judgment legs, so it is named.
* **Bind mechanics (deterministic, reported per-pass):** the pass/fail VERDICT is
  deliberately never persisted (engine ADR-0017 — recomputed on demand), so what
  a pass can compare is the persisted grounded BIND: each seed validation's
  ``validation_results`` row + a stable fingerprint of its ``sql_used``. The
  fingerprint report feeds cross-pass comparison in the DAT-862 store.
* **LLM-judgment legs (reduced-verdict parity under epochs + reducer):**
  sign_conventions is the observed flapper (verdict flipped failed↔passed across
  prompt revisions — an account-classification judgment reflected in the grounded
  SQL, which is why the fingerprint matters). A single run cannot grade reduced
  parity — that comparison runs across passes under the sweep-#2 read-out
  (majority vote over N draws per home; a reduced-verdict disagreement blocks the
  deletion, a shifted draw split is reported). This module never hard-asserts a
  judgment leg on one draw (manufactured red, the Q3 ban).

Skips (never vacuous-passes) when a home is absent: pre-migration engine (no seed
rows) or post-deletion (no YAMLs — parity retired, the gate decided).

Tier-3 (docker + Temporal + LLM upstream): marked ``llm``.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from calibration import cube
from calibration.conftest import EVAL_ROOT, require_pipeline_run
from calibration.metadata_truth import is_wild
from calibration.tools._runs import workspace_session

pytestmark = cube.needs(vertical="finance", dataset="*", from_stage="operating_model")

_YAML_HOME = (
    EVAL_ROOT / "vendor" / "dataraum-context" / "packages" / "dataraum-config"
    / "verticals" / "finance" / "validations"
)
# Fields with an unambiguous home on both sides — the deterministic-identity legs.
_IDENTITY_FIELDS = ("check_type", "severity", "category", "version")
# Prompt-shaping text — drift here moves the judgment legs; reported, never auto-failed.
_TEXT_FIELDS = ("description", "expected_outcome")

_KNOWN_FLAPPERS = frozenset({"sign_conventions"})


@pytest.fixture(autouse=True)
def _completed_run(strategy_name: str) -> None:
    require_pipeline_run(strategy_name)


def _yaml_home() -> dict[str, dict[str, Any]]:
    if not _YAML_HOME.is_dir():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(_YAML_HOME.glob("*.yaml")):
        spec = yaml.safe_load(path.read_text()) or {}
        if spec.get("validation_id"):
            out[str(spec["validation_id"])] = spec
    return out


def _db_home(session: Any) -> dict[str, Any]:
    from sqlalchemy import text

    rows = session.execute(
        text(
            "SELECT validation_id, name, description, category, severity, check_type, "
            "expected_outcome, version, source "
            "FROM validations WHERE superseded_at IS NULL AND source = 'seed'"
        )
    ).all()
    return {r.validation_id: r for r in rows}


@pytest.mark.llm
def test_seed_parity_deterministic_legs(metadata_truth: dict[str, Any], strategy_name: str) -> None:
    """Set-of-nine identity + identity-field equality, per-draw exact."""
    if is_wild(metadata_truth):
        pytest.skip("Tier-B corpus — seed validations belong to the declaring vertical")
    yaml_specs = _yaml_home()
    if not yaml_specs:
        pytest.skip("YAML home absent — parity retired (the sweep-#2 gate decided the deletion)")

    with workspace_session() as session:
        db = _db_home(session)
    if not db:
        pytest.skip("no seed validations in the DB home — pre-migration engine")

    missing = sorted(set(yaml_specs) - set(db))
    extra = sorted(set(db) - set(yaml_specs))
    print(f"\n[seed parity] YAML home={len(yaml_specs)} DB home={len(db)}")
    assert not missing, f"seed validations in the YAML home but not the DB home: {missing}"
    assert not extra, f"DB-seeded validations the YAML home never declared: {extra}"

    identity_breaks: list[str] = []
    text_drift: dict[str, int] = dict.fromkeys(_TEXT_FIELDS, 0)
    for vid, spec in sorted(yaml_specs.items()):
        row = db[vid]
        for field in _IDENTITY_FIELDS:
            if str(spec.get(field, "")) != str(getattr(row, field) or ""):
                identity_breaks.append(
                    f"{vid}.{field}: yaml={spec.get(field)!r} db={getattr(row, field)!r}"
                )
        for field in _TEXT_FIELDS:
            y = " ".join(str(spec.get(field, "")).split())
            d = " ".join(str(getattr(row, field) or "").split())
            if y != d:
                text_drift[field] += 1
    drifted = {k: v for k, v in text_drift.items() if v}
    if drifted:
        print(f"  [reported] prompt-shaping text drift (sweep-attention, moves judgment legs): {drifted}")
    assert not identity_breaks, (
        "deterministic identity fields diverge between homes — a migration bug, "
        "per-draw exact by the Q3 ruling:\n  " + "\n  ".join(identity_breaks)
    )


@pytest.mark.llm
def test_bind_surface_fingerprinted_not_asserted(
    metadata_truth: dict[str, Any], strategy_name: str
) -> None:
    """Every seed validation executed this run + a stable sql_used fingerprint
    (feeds cross-pass bind-parity in the verdict store); the VERDICT is never
    persisted (ADR-0017) and never hard-asserted on one draw (Q3)."""
    import hashlib

    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    if is_wild(metadata_truth):
        pytest.skip("Tier-B corpus — seed validations belong to the declaring vertical")

    with workspace_session() as session:
        db = _db_home(session)
        if not db:
            pytest.skip("no seed validations in the DB home — pre-migration engine")
        read_schema = read_schema_name_for(
            str(session.execute(text("SELECT current_schema()")).scalar())
        )
        results = session.execute(
            text(
                "SELECT validation_id, sql_used "
                f'FROM "{read_schema}".current_validation_results '
                "WHERE validation_id = ANY(:ids)"
            ),
            {"ids": sorted(db)},
        ).all()

    if not results:
        pytest.skip("seed validations produced no results this run — the validation phase's own gate")

    executed = {str(r.validation_id) for r in results}
    unexecuted = sorted(set(db) - executed)
    print("\n[bind surface] grounded-SQL fingerprints (cross-pass parity = the sweep-#2 read-out):")
    for r in sorted(results, key=lambda r: str(r.validation_id)):
        fp = hashlib.sha256((r.sql_used or "").encode()).hexdigest()[:12]
        flap = "  ← known flapper (reduced-verdict parity applies)" if (
            r.validation_id in _KNOWN_FLAPPERS
        ) else ""
        print(f"  {r.validation_id:<28} sql_fp={fp}{flap}")
    assert not unexecuted, (
        "seed validation(s) never executed this run — a declared check that no longer "
        f"binds is a migration defect, not judgment variance: {unexecuted}"
    )
