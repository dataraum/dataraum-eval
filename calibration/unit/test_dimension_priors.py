"""Tier-1: the dimension prior library and its dry run (DAT-885 / RFC 3 lane A2).

Two things are worth pinning here, and neither is the parser. First, that the priors
stay **vertical-neutral** — they exist to replace a frame seed that leaks one
industry's vocabulary, so finance words creeping in would defeat their whole purpose.
Second, that the dry run never reports capability it does not have: the failure mode
of a coverage read is optimism.
"""

from __future__ import annotations

import re

import pytest

from calibration import dimension_priors as dp

# The A1 corpus (DAT-884) and the two wild corpora, by their real table names.
A1_TABLES = [
    "ar_invoices", "balance_sheet", "bank_transactions", "chart_of_accounts",
    "customers", "fx_rates", "invoices", "journal_entries", "journal_lines",
    "payments", "products", "receipts", "sales_order_lines", "sales_orders",
    "trial_balance",
]
PRE_A1_TABLES = [
    "balance_sheet", "bank_transactions", "chart_of_accounts", "fx_rates",
    "invoices", "journal_entries", "journal_lines", "payments", "trial_balance",
]
REL_HM_TABLES = ["transactions", "customer", "article"]  # retail
REL_F1_TABLES = [  # motorsport — should carry none of the three
    "qualifying", "drivers", "results", "standings", "races", "constructors",
    "constructor_results", "circuits", "constructor_standings",
]


def _by_dimension(tables: list[str], **kw: object) -> dict[str, dp.DimensionRead]:
    return {r.dimension: r for r in dp.dry_run(tables, **kw)}  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# the library itself
# ---------------------------------------------------------------------------


def test_library_is_the_thin_slice_by_decision() -> None:
    """Three dimensions, not six — Supply/Capacity/Throughput wait for their
    generator families (RFC 3 B7). Authoring priors for a dimension nothing can carry
    would put a menu in front of a user that leads nowhere."""
    assert set(dp.load()) == set(dp.THIN_SLICE) == {"demand", "offer", "capital"}


def test_priors_are_vertical_neutral() -> None:
    """No finance vocabulary in the priors — that leak is what they exist to replace.

    The bindings block is the ONLY place a vertical's own table names may appear, and
    it is deliberately separate so this test can be strict about everything else.
    """
    # Matched on WORD TOKENS, not substrings: "creditor" is ordinary commercial
    # vocabulary (the party you owe) while "credit" as a posting side is not, and a
    # substring test conflates them — it flagged `creditor` on the first run.
    banned_words = {
        "journal", "ledger", "debit", "credit", "gl", "fiscal", "posting", "voucher",
    }
    banned_phrases = {"chart_of_accounts", "trial_balance", "balance_sheet", "account_id"}

    for dim in dp.load().values():
        parts = (
            [dim.key, dim.label, *dim.ladder, *dim.levers]
            + [e.name for e in dim.entities]
            + [a for e in dim.entities for a in e.aliases]
            + [m.id for m in dim.metrics]
            + [m.label for m in dim.metrics]
        )
        blob = " ".join(parts).lower()
        tokens = set(re.split(r"[^a-z0-9]+", blob))
        leaked = sorted((banned_words & tokens) | {p for p in banned_phrases if p in blob})
        assert not leaked, f"{dim.key} priors leak finance vocabulary: {leaked}"


def test_every_metric_declares_whether_it_needs_allocation() -> None:
    """Allocation-free metrics are shippable now; the rest wait for the allocation
    object (RFC 3 B5). A metric silent on this would be shipped by accident."""
    for dim in dp.load().values():
        for metric in dim.metrics:
            assert metric.allocation_free != metric.requires_allocation, (
                f"{dim.key}.{metric.id}: allocation status is ambiguous"
            )


# ---------------------------------------------------------------------------
# the dry run — the exit criterion, and its honesty
# ---------------------------------------------------------------------------


def test_a1_corpus_lights_all_three_dimensions() -> None:
    """A2's exit criterion, first half: the A1 chain makes Demand/Offer/Capital
    carryable where they were dark."""
    reads = _by_dimension(A1_TABLES, vertical="finance")
    assert {r.status for r in reads.values()} == {dp.PARTIAL}

    assert "db1_per_customer" in reads["demand"].metrics_available
    assert "db1_per_product_group" in reads["offer"].metrics_available
    assert "dso_by_customer" in reads["capital"].metrics_available

    # …and each is PARTIAL for a NAMED reason, not a vague one.
    assert reads["demand"].metrics_blocked["cost_to_serve"] == ("allocation_scheme",)
    assert reads["offer"].metrics_blocked["db2_per_product_group"] == ("allocation_scheme",)
    assert "inventory_position" in reads["capital"].metrics_blocked["dio_by_product_group"]


def test_pre_a1_corpus_reproduces_the_rfc_2_assessment() -> None:
    """RFC 2 predicted: Demand no, Offer no, Capital partial (payables side).

    Reproducing that mechanically is what makes the read trustworthy — it agrees with
    an assessment written before it existed.
    """
    reads = _by_dimension(PRE_A1_TABLES, vertical="finance")
    assert reads["demand"].status == dp.DARK
    assert reads["offer"].status == dp.DARK
    assert reads["capital"].status == dp.PARTIAL
    assert reads["capital"].metrics_available == ("dpo_by_supplier",)
    assert "receivable" in reads["capital"].metrics_blocked["dso_by_customer"]


def test_a_schema_supporting_nothing_reads_dark_not_partial() -> None:
    """The coverage-map lie in miniature, and a bug this test was written after.

    Capital marks no entity `required` on purpose (partial coverage is normal there),
    which made a motorsport schema read PARTIAL with ZERO metrics available — a status
    implying "some of this works" when none of it does. Availability decides.
    """
    for tables in (REL_F1_TABLES, REL_HM_TABLES):
        reads = _by_dimension(tables)
        for read in reads.values():
            if not read.metrics_available:
                assert read.status == dp.DARK, (
                    f"{read.dimension} claims {read.status} with no metric available"
                )


def test_wild_retail_finds_its_entities_without_a_binding() -> None:
    """rel-hm has customer + article and no order line: partial recognition, honestly
    reported. Alias matching earns its keep here — no binding is authored for it."""
    reads = _by_dimension(REL_HM_TABLES)
    assert reads["demand"].resolved.get("customer") == "customer"
    assert reads["offer"].resolved.get("product") == "article"
    # …but neither dimension is carryable: the order-line grain is missing.
    assert reads["demand"].status == dp.DARK
    assert reads["offer"].status == dp.DARK


def test_authored_binding_beats_alias_guessing() -> None:
    """A binding is a stated fact; alias matching is a guess. The fact wins."""
    reads = _by_dimension(A1_TABLES, vertical="finance")
    assert reads["capital"].resolved["receivable"] == "ar_invoices"
    assert reads["capital"].resolved["payable"] == "invoices"


def test_binding_to_an_absent_table_resolves_nothing() -> None:
    """A binding naming a table this schema lacks must not resolve it — otherwise the
    read would report capability the data does not have."""
    reads = _by_dimension(["journal_lines"], vertical="finance")
    assert all(not r.resolved for r in reads.values())
    assert all(r.status == dp.DARK for r in reads.values())


def test_entity_matching_does_not_confuse_order_with_order_line() -> None:
    """`orders` and `order_lines` are different grains; collapsing them would make a
    header-only schema look like it had line detail."""
    entities = {e.name: e for e in dp.load()["demand"].entities}
    assert entities["order"].matches("sales_orders")
    assert not entities["order_line"].matches("orders")
    assert entities["order_line"].matches("sales_order_lines")


def test_render_states_that_carryable_is_not_lit() -> None:
    """The distinction is the whole point; losing it from the output is how the two
    get conflated downstream."""
    text = dp.render(dp.dry_run(A1_TABLES, vertical="finance"), title="t")
    assert "NOT 'lit'" in text


@pytest.mark.parametrize("dimension", dp.THIN_SLICE)
def test_every_dimension_has_a_ladder_and_at_least_one_free_metric(dimension: str) -> None:
    dim = dp.load()[dimension]
    assert dim.ladder, f"{dimension} has no granularity ladder"
    assert any(m.allocation_free for m in dim.metrics)
