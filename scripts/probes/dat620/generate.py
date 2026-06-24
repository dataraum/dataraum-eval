"""DAT-620 lane-1 fixture: a seeded long-format finance table + concept oracle.

One `amount` column + an `account_type` discriminator (the BookSQL shape). Every
`account_type` value carries a known concept (the oracle) across graded difficulty
classes, so a labeler's precision/recall — and the gross-margin it reconstructs — can be
scored. Probe-local + disposable; graduate into dataraum-testdata only if a tier survives.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

# value -> (oracle concept, difficulty class). Concepts are the finance ontology names.
# 'unmapped' = no ontology concept applies; the safe label is abstention, not a force-fit.
CANONICAL: dict[str, tuple[str, str]] = {
    # exact — an ontology indicator appears literally (the floor)
    "Sales Revenue": ("revenue", "exact"),
    "COGS": ("cost_of_goods_sold", "exact"),
    "Operating Expenses": ("operating_expense", "exact"),
    # synonym — semantically the concept, no literal indicator match
    "Turnover": ("revenue", "synonym"),
    "Service Income": ("revenue", "synonym"),
    "Cost of Sales": ("cost_of_goods_sold", "synonym"),
    "Direct Materials": ("cost_of_goods_sold", "synonym"),
    "SG&A": ("operating_expense", "synonym"),
    "Overhead": ("operating_expense", "synonym"),
    # exclude_trap — contains a word that is an *exclude_pattern* of its true concept
    # ("cost" is a revenue exclude_pattern) yet belongs to it semantically
    "Cost Recovery Income": ("revenue", "exclude_trap"),
    # non_pl — a real concept, but not revenue/cogs/opex; must route to its own concept,
    # NOT be force-fit into a P&L bucket (precision test; irrelevant to gross margin)
    "Accounts Receivable": ("accounts_receivable", "non_pl"),
    # unmapped — genuinely outside the ontology; must abstain (the no-force-fit trap)
    "Suspense": ("unmapped", "unmapped"),
    "Clearing Account": ("unmapped", "unmapped"),
    "Intercompany Elimination": ("unmapped", "unmapped"),
}

# HARD universe — where feed-only should hit a wall. Opaque GL codes carry a
# chart-of-accounts convention only a human (teach) or the measure itself (drivers)
# could know; abbreviations are recoverable-with-effort; ambiguous buckets genuinely
# span concepts, so the safe label is abstention. A few clean anchors keep the metric
# base recoverable so gross-profit error is meaningful.
HARD: dict[str, tuple[str, str]] = {
    # clean semantic anchors
    "Sales Revenue": ("revenue", "exact"),
    "COGS": ("cost_of_goods_sold", "exact"),
    "Operating Expenses": ("operating_expense", "exact"),
    # opaque GL codes — 4xxx=revenue / 5xxx=cogs / 6xxx=opex (US COA convention).
    # Uninferrable from the discriminator alone → the teach/binding case.
    "4000": ("revenue", "code"),
    "5000": ("cost_of_goods_sold", "code"),
    "6000": ("operating_expense", "code"),
    # abbreviations — recoverable with effort
    "Rev": ("revenue", "abbrev"),
    "CGS": ("cost_of_goods_sold", "abbrev"),
    # genuine ambiguity — spans concepts; safe answer is abstain (unmapped)
    "Other Income & Expense": ("unmapped", "ambiguous"),
    "Miscellaneous": ("unmapped", "ambiguous"),
    # true unmapped
    "Suspense": ("unmapped", "unmapped"),
}

# amount distribution (lo, hi) per oracle concept — realistic relative magnitudes
_AMOUNT_RANGE: dict[str, tuple[float, float]] = {
    "revenue": (1_000.0, 50_000.0),
    "cost_of_goods_sold": (500.0, 30_000.0),
    "operating_expense": (100.0, 10_000.0),
    "accounts_receivable": (1_000.0, 40_000.0),
    "unmapped": (10.0, 5_000.0),
}


@dataclass(frozen=True)
class Fixture:
    """One seeded long-format instance, reduced to what the rig needs."""

    counts: dict[str, int]  # account_type -> row count  (feeds top_values)
    totals: dict[str, float]  # account_type -> Σ amount (feeds metric reconstruction)
    oracle: dict[str, tuple[str, str]]  # account_type -> (concept, class)

    def top_values(self) -> list[tuple[str, int]]:
        """Mirror StatisticalProfile.top_values ordering: count DESC, value."""
        return sorted(self.counts.items(), key=lambda kv: (-kv[1], kv[0]))

    @property
    def gross_profit(self) -> float:
        return self._sum("revenue") - self._sum("cost_of_goods_sold")

    @property
    def revenue_total(self) -> float:
        return self._sum("revenue")

    def _sum(self, concept: str) -> float:
        return sum(
            self.totals[v] for v, (c, _) in self.oracle.items() if c == concept
        )


def make_fixture(seed: int, n_rows: int = 4_000, hard: bool = False) -> Fixture:
    """Build a deterministic long-format instance for `seed`.

    The full value set is present every seed (so every difficulty class is measured each
    seed); only row counts, amounts, and ordering vary. `hard=True` swaps in the HARD
    universe (codes / abbrevs / ambiguity). Drift / fall-loud on a value absent from a
    *confirmed set* is out of lane-1 scope — there is no confirmed set without the
    binding table (tier C).
    """
    universe = HARD if hard else CANONICAL
    rng = random.Random(seed)
    values = list(universe)
    # per-value sampling weight (varies the count distribution across seeds)
    weights = [rng.uniform(0.3, 1.0) for _ in values]

    counts: dict[str, int] = dict.fromkeys(values, 0)
    totals: dict[str, float] = dict.fromkeys(values, 0.0)
    for _ in range(n_rows):
        v = rng.choices(values, weights=weights, k=1)[0]
        lo, hi = _AMOUNT_RANGE[universe[v][0]]
        counts[v] += 1
        totals[v] += rng.uniform(lo, hi)

    return Fixture(counts=counts, totals=totals, oracle=dict(universe))
