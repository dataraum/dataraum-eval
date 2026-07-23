"""Role-separated conformed identity — the O6 oracle (DAT-788, detection-roleplay-v1).

Grades the role-playing-FK probe shape (CAP-roleplay-fk-fixture: one address
dimension, orders.bill_to/ship_to as two roles, deliveries.delivery_addr sharing
the ship role under another name — role-consistent BY CONSTRUCTION) against the
catalogue's shared-axes surface. Truth = the corpus's ``fk_roles`` section; grading
is structure-first and label-invariant (role STRINGS the engine invents are never
asserted — only separation and pairing):

1. **Role separation (HARD)** — the two orders→addresses exposures are TWO
   distinct axes: distinct ``fk_role`` values on their slice rows and distinct
   ``conformed_group``s on their referenced bus-matrix entries. One merged axis is
   the DAT-788 bug.
2. **No cross-role conformance (HARD)** — deliveries' address exposure never
   lands in the BILL-role group (delivery_addr is ship-role by construction);
   a cross-role merge is fabricated identity, judge or no judge.
3. **Conform path (in-body xfail, LLM/judge-dependent)** — the differently-named
   same-role pair (delivery_addr ↔ ship_to_addr) DOES share the ship-role group
   when the judge conforms it; on judge role/abstain the cell surfaces
   ``needs_confirmation`` instead — reported either way.
4. **Content-derived identity (HARD)** — every referenced address entry's
   ``signature`` is the content-derived ``ref:{dimension_table_id}:…`` form,
   never per-run random.

Tier-3 (docker + Temporal + LLM upstream): marked ``llm``.
"""

from __future__ import annotations

from typing import Any

import pytest

from calibration import cube
from calibration.conftest import require_pipeline_run
from calibration.metadata_truth import read_view_exists
from calibration.tools._runs import workspace_session

pytestmark = cube.needs(
    vertical="finance", dataset="detection-roleplay-v1", from_stage="begin_session"
)


@pytest.fixture(autouse=True)
def _completed_run(strategy_name: str) -> None:
    require_pipeline_run(strategy_name)


def _fk_roles(metadata_truth: dict[str, Any]) -> dict[tuple[str, str], str]:
    """(table, column) → declared role, from the corpus's fk_roles truth."""
    out: dict[tuple[str, str], str] = {}
    for qualified, role in (metadata_truth.get("fk_roles") or {}).items():
        table, _, column = str(qualified).partition(".")
        out[(table, column)] = role
    return out


def _address_exposures(session: Any) -> list[dict[str, Any]]:
    """Referenced bus-matrix entries + their slice rows for the role-play facts."""
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    from calibration.tools._runs import short

    read_schema = read_schema_name_for(
        str(session.execute(text("SELECT current_schema()")).scalar())
    )
    rows = session.execute(
        text(
            "SELECT ft.table_name AS fact, b.attachment AS attachment, "
            "b.roles AS roles, b.conformed_group AS conformed_group, "
            "b.needs_confirmation AS needs_confirmation, b.signature AS signature, "
            "b.dimension_table_id AS dimension_table_id, dt.table_name AS dimension "
            f'FROM "{read_schema}".current_bus_matrix b '
            "JOIN tables ft ON ft.table_id = b.fact_table_id "
            "LEFT JOIN tables dt ON dt.table_id = b.dimension_table_id "
            "WHERE b.attachment = 'referenced'"
        )
    ).all()
    out = []
    for r in rows:
        out.append(
            {
                "fact": short(r.fact),
                "roles": list(r.roles or []),
                "conformed_group": r.conformed_group,
                "needs_confirmation": bool(r.needs_confirmation),
                "signature": r.signature,
                "dimension_table_id": r.dimension_table_id,
                "dimension": short(r.dimension) if r.dimension else None,
            }
        )
    return [e for e in out if e["dimension"] == "addresses"]


def _entries_by_role(
    exposures: list[dict[str, Any]], fact: str, roles_truth: dict[tuple[str, str], str]
) -> dict[str, dict[str, Any]]:
    """Map a fact's address exposures onto DECLARED roles via the truth's FK columns.

    An exposure's ``roles`` carries the engine's role names for the columns it
    groups; we match by the truth column's presence in a role name (label-tolerant:
    the engine derives role names from column names), never by exact string.
    """
    truth_cols = {col: role for (t, col), role in roles_truth.items() if t == fact}
    out: dict[str, dict[str, Any]] = {}
    for e in exposures:
        if e["fact"] != fact:
            continue
        for engine_role in e["roles"]:
            for col, declared in truth_cols.items():
                if engine_role in col or col in str(engine_role):
                    out.setdefault(declared, e)
    return out


@pytest.mark.llm
def test_role_separation(metadata_truth: dict[str, Any], strategy_name: str) -> None:
    """orders' bill and ship exposures are DISTINCT axes (groups + slice roles)."""
    roles_truth = _fk_roles(metadata_truth)
    if not roles_truth:
        pytest.skip("no fk_roles truth — not the role-play corpus")

    with workspace_session() as session:
        if not read_view_exists(session, "current_bus_matrix"):
            pytest.skip("current_bus_matrix absent — pre-DAT-762 engine")
        exposures = _address_exposures(session)

    if not exposures:
        pytest.skip(
            "no referenced address exposures in the bus matrix — the shared-axes "
            "surface did not materialize (its recall is the bus-matrix oracle's job)"
        )

    by_role = _entries_by_role(exposures, "orders", roles_truth)
    print(f"\n[role separation] orders address exposures resolved: {sorted(by_role)}")
    if not {"bill_to", "ship_to"} <= set(by_role):
        pytest.xfail(
            "orders' two FK roles did not both surface as referenced address exposures "
            f"(got {sorted(by_role)}) — exposure recall, graded in the bus-matrix lane"
        )
    bill, ship = by_role["bill_to"], by_role["ship_to"]
    assert bill["signature"] != ship["signature"], (
        "bill_to and ship_to collapsed into ONE bus-matrix identity — the exact "
        "role-merging DAT-788 exists to prevent"
    )
    if bill["conformed_group"] and ship["conformed_group"]:
        assert bill["conformed_group"] != ship["conformed_group"], (
            "bill_to and ship_to share a conformed_group — two roles merged into one axis"
        )


@pytest.mark.llm
def test_no_cross_role_conformance(metadata_truth: dict[str, Any], strategy_name: str) -> None:
    """deliveries' (ship-role by construction) exposure never joins the bill group."""
    roles_truth = _fk_roles(metadata_truth)
    if not roles_truth:
        pytest.skip("no fk_roles truth — not the role-play corpus")

    with workspace_session() as session:
        if not read_view_exists(session, "current_bus_matrix"):
            pytest.skip("current_bus_matrix absent — pre-DAT-762 engine")
        exposures = _address_exposures(session)

    orders = _entries_by_role(exposures, "orders", roles_truth)
    deliveries = [e for e in exposures if e["fact"] == "deliveries"]
    if "bill_to" not in orders or not deliveries:
        pytest.skip("bill exposure or deliveries exposure absent — nothing to cross-check")

    bill_group = orders["bill_to"]["conformed_group"]
    ship_group = orders.get("ship_to", {}).get("conformed_group")
    cross = [
        e for e in deliveries
        if bill_group and e["conformed_group"] == bill_group and bill_group != ship_group
    ]
    print(f"\n[cross-role] deliveries exposures={len(deliveries)}, cross-role merges={len(cross)}")
    assert not cross, (
        "deliveries' address exposure conformed into the BILL-role group — identity "
        "fabricated ACROSS roles (delivery_addr is ship-role by construction): "
        + ", ".join(str(e["signature"]) for e in cross)
    )


@pytest.mark.llm
def test_same_role_conform_path(metadata_truth: dict[str, Any], strategy_name: str) -> None:
    """The differently-named same-role pair pairs (judge-conformed) OR surfaces
    needs_confirmation — LLM-dependent, so shortfall is an in-body xfail."""
    roles_truth = _fk_roles(metadata_truth)
    if not roles_truth:
        pytest.skip("no fk_roles truth — not the role-play corpus")

    with workspace_session() as session:
        if not read_view_exists(session, "current_bus_matrix"):
            pytest.skip("current_bus_matrix absent — pre-DAT-762 engine")
        exposures = _address_exposures(session)

    orders = _entries_by_role(exposures, "orders", roles_truth)
    deliveries = [e for e in exposures if e["fact"] == "deliveries"]
    if "ship_to" not in orders or not deliveries:
        pytest.skip("ship exposure or deliveries exposure absent — nothing to pair")

    ship_group = orders["ship_to"]["conformed_group"]
    conformed = [e for e in deliveries if ship_group and e["conformed_group"] == ship_group]
    abstained = [e for e in deliveries if e["needs_confirmation"]]
    print(
        f"\n[conform path] ship-group conformed={len(conformed)}, "
        f"needs_confirmation surfaced={len(abstained)}"
    )
    if not conformed:
        pytest.xfail(
            "the judge did not conform the differently-named same-role pair this draw "
            f"(needs_confirmation on {len(abstained)} cell(s)) — judge-dependent, the "
            "abstain path is legitimate; a conformed draw XPASSes"
        )


@pytest.mark.llm
def test_identity_signature_content_derived(
    metadata_truth: dict[str, Any], strategy_name: str
) -> None:
    """The CONFORMED-IDENTITY key (conformed_group) is the content-derived
    ``ref:{dimension_table_id}:…`` form — never per-run random.

    (v1 of this test asserted the ``ref:`` form on the bus-matrix ENTRY signature,
    which is legitimately ``bus:referenced:{fact_id}:{dim_id}:{key_column}`` — a
    different, also content-derived key. The ``ref:`` form is the role-group /
    conformed-identity key, i.e. ``conformed_group``. The first roleplay run's red
    was this oracle's field mixup, not the engine.)
    """
    roles_truth = _fk_roles(metadata_truth)
    if not roles_truth:
        pytest.skip("no fk_roles truth — not the role-play corpus")

    with workspace_session() as session:
        if not read_view_exists(session, "current_bus_matrix"):
            pytest.skip("current_bus_matrix absent — pre-DAT-762 engine")
        exposures = _address_exposures(session)

    grouped = [e for e in exposures if e["conformed_group"]]
    if not grouped:
        pytest.skip(
            "no conformed_group on any address exposure this draw — the conform-path "
            "oracle owns whether grouping should have happened"
        )
    bad = [
        str(e["conformed_group"])
        for e in grouped
        if not str(e["conformed_group"]).startswith(f"ref:{e['dimension_table_id']}:")
    ]
    print(f"\n[signature] {len(grouped)} grouped exposures, {len(bad)} non-content-derived")
    assert not bad, (
        f"conformed_group keys not content-derived (ref:{{dim_table_id}}:…): {bad}"
    )
