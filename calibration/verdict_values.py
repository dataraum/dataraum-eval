"""The number behind a verdict (DAT-862 / RFC 5 extension 1).

A pass/fail tells you a threshold held. It cannot tell you the margin shrank by
half — and a margin halving twice in a row is the regression that matters, because
the third time it crosses. The verdict store (``results_store.py``) records status;
this records the **measured value and the threshold that judged it**, so the store
turns from a regression alarm into a trend instrument.

It is also the prerequisite for DAT-687: a pipeline-error *distribution* over graded
metrics cannot be assembled from pass rates, only from the per-metric errors that
produced them.

The transport is pytest's own ``user_properties`` (what the builtin
``record_property`` fixture writes to): the values ride on the test report, get
picked up by ``coverage.build_oracle_ledger`` alongside the status, and land in the
verdict row. No global sink, no second write path, nothing to keep in sync.

    def test_something(request):
        verdict_values.record(request, "delta", 0.42, threshold=0.10,
                              comparator=">", unit="margin", subject="invoices.amount")

**What this is not.** Recording a value never changes an outcome — the assertion
above it is still what fails the test. A value recorded on a red oracle is kept
(that is the interesting one), and no threshold here is ever read back to decide a
verdict at runtime: relaxing an oracle by moving a number is the thing the charter
forbids, and it would be invisible if the number lived in two places.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

# The ``user_properties`` key every graded value rides on. One key, so a reader can
# tell our values apart from anything else pytest or a plugin records there.
KEY = "graded_value"

# How a threshold judged a value. "" = reported only (a statistic with no bar — a
# distribution input, e.g. a per-metric relative error whose spec carries no pct).
COMPARATORS = frozenset({">", ">=", "<", "<=", "==", ""})

_OPS = {
    ">": lambda v, t: v > t,
    ">=": lambda v, t: v >= t,
    "<": lambda v, t: v < t,
    "<=": lambda v, t: v <= t,
    "==": lambda v, t: v == t,
}


@dataclass(frozen=True)
class Value:
    """One measured number an oracle judged (or merely reported).

    ``name`` is the STATISTIC (``delta``, ``relative_error``, ``fire_rate``) and
    ``subject`` is what it was measured on (``invoices.amount:derived_value``,
    ``free_cash_flow``). Keeping them apart is what makes a trend query possible:
    "how has ``relative_error`` moved across passes" groups by name, "…on
    free_cash_flow" filters by subject. Folding the subject into the name would
    make every metric its own unrelated series.
    """

    name: str
    value: float
    threshold: float | None = None
    comparator: str = ""
    unit: str = ""  # score | margin | relative | count | currency | ratio
    subject: str = ""

    @property
    def held(self) -> bool | None:
        """Did the value satisfy its threshold? ``None`` when nothing judged it.

        Reported-only values (no threshold / no comparator) are honest ``None`` —
        not ``True``. A dimension reading *lit* off an unjudged number is exactly
        the coverage-map lie the honesty gate exists to prevent (RFC 5).
        """
        if self.threshold is None or self.comparator not in _OPS:
            return None
        return bool(_OPS[self.comparator](self.value, self.threshold))


def make(
    name: str,
    value: float,
    *,
    threshold: float | None = None,
    comparator: str = "",
    unit: str = "",
    subject: str = "",
) -> Value:
    """Validate and build a :class:`Value` (pure — the Tier-1 seam)."""
    if not name:
        raise ValueError("a graded value needs a name (the statistic)")
    if comparator not in COMPARATORS:
        raise ValueError(f"comparator {comparator!r} not in {sorted(COMPARATORS)}")
    if comparator and threshold is None:
        raise ValueError(f"{name}: comparator {comparator!r} given with no threshold")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{name}: value {value!r} is not finite — nothing to trend")
    return Value(
        name=name,
        value=numeric,
        threshold=None if threshold is None else float(threshold),
        comparator=comparator,
        unit=unit,
        subject=subject,
    )


def record(
    node: Any,
    name: str,
    value: float,
    *,
    threshold: float | None = None,
    comparator: str = "",
    unit: str = "",
    subject: str = "",
) -> Value:
    """Attach a graded value to the running test. ``node`` is a request or an item.

    Reporting only — it never changes an outcome. Call it BEFORE the assertion it
    describes, so the number is recorded on the red pass too (a failed oracle's
    value is the one worth trending).
    """
    val = make(
        name, value, threshold=threshold, comparator=comparator, unit=unit, subject=subject
    )
    item = getattr(node, "node", node)  # FixtureRequest → Item
    item.user_properties.append((KEY, asdict(val)))
    return val


def from_payload(payload: dict[str, Any]) -> Value:
    """Rebuild a :class:`Value` from a stored row's payload (pure).

    Unknown keys are dropped rather than raising: the store is append-only and
    git-tracked, so rows written by an older schema must stay readable forever —
    a query that dies on history is a query nobody runs.
    """
    fields = {"name", "value", "threshold", "comparator", "unit", "subject"}
    return Value(**{k: v for k, v in payload.items() if k in fields})


def values_from(user_properties: Any) -> list[dict[str, Any]]:
    """The graded values on one test report's ``user_properties`` (pure).

    Ignores anything recorded under another key — pytest plugins share this list.
    """
    return [dict(payload) for key, payload in (user_properties or []) if key == KEY]
