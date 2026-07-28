"""Tier-1: the number behind a verdict (DAT-862 / RFC 5 ext 1).

The store turns from an alarm into a trend instrument only if the value and the bar
that judged it travel together — and only if "nothing judged this" stays honestly
distinct from "it held". Both are proven here, in milliseconds, with no pipeline.
"""

from __future__ import annotations

import pytest

from calibration import verdict_values
from calibration.coverage import build_oracle_ledger


class _Item:
    """The bit of a pytest item the recorder touches."""

    def __init__(self) -> None:
        self.user_properties: list[tuple[str, object]] = []


class _Request:
    """A FixtureRequest wraps its item as ``.node`` — the recorder accepts either."""

    def __init__(self, item: _Item) -> None:
        self.node = item


class _Report:
    def __init__(self, nodeid: str, user_properties: list[tuple[str, object]]) -> None:
        self.nodeid = nodeid
        self.user_properties = user_properties
        self.longrepr = None


def test_held_reads_the_comparator() -> None:
    assert verdict_values.make("delta", 0.42, threshold=0.05, comparator=">").held is True
    assert verdict_values.make("delta", 0.04, threshold=0.05, comparator=">").held is False
    assert verdict_values.make("err", 0.5, threshold=0.5, comparator="<=").held is True
    assert verdict_values.make("err", 0.5, threshold=0.5, comparator="<").held is False


def test_reported_only_value_is_not_held() -> None:
    """No threshold → ``None``, never ``True``.

    A dimension reading *lit* off a number nothing judged is the coverage-map lie
    the honesty gate exists to prevent (RFC 5).
    """
    assert verdict_values.make("fire_rate", 0.9).held is None


def test_make_rejects_incoherent_declarations() -> None:
    with pytest.raises(ValueError, match="comparator"):
        verdict_values.make("x", 1.0, comparator="~=", threshold=1.0)
    with pytest.raises(ValueError, match="no threshold"):
        verdict_values.make("x", 1.0, comparator=">")
    with pytest.raises(ValueError, match="not finite"):
        verdict_values.make("x", float("inf"))
    with pytest.raises(ValueError, match="name"):
        verdict_values.make("", 1.0)


def test_record_accepts_request_or_item_and_roundtrips() -> None:
    item = _Item()
    verdict_values.record(_Request(item), "score", 0.7, threshold=0.3, comparator=">",
                          unit="score", subject="invoices.amount:null_ratio")
    verdict_values.record(item, "delta", 0.2, unit="margin")

    vals = verdict_values.values_from(item.user_properties)
    assert [v["name"] for v in vals] == ["score", "delta"]
    assert vals[0]["threshold"] == 0.3 and vals[0]["subject"] == "invoices.amount:null_ratio"
    assert vals[1]["threshold"] is None
    # Round-trips through the stored payload shape.
    assert verdict_values.from_payload(vals[0]).held is True


def test_from_payload_survives_unknown_fields() -> None:
    """The store is append-only and git-tracked: old rows must stay readable."""
    val = verdict_values.from_payload(
        {"name": "delta", "value": 0.1, "invented_later": "whatever"}
    )
    assert val.name == "delta" and val.value == 0.1


def test_values_from_ignores_other_recorders() -> None:
    props = [("something_else", {"name": "not ours"}), (verdict_values.KEY, {"name": "ours"})]
    assert [v["name"] for v in verdict_values.values_from(props)] == ["ours"]
    assert verdict_values.values_from(None) == []


def test_ledger_carries_values_onto_the_failing_report() -> None:
    """Values ride the ledger the store already writes — one path, no second sink.

    Severity order still decides the status, and a red oracle KEEPS its number:
    that is the one worth trending.
    """
    shared: list[tuple[str, object]] = [
        (verdict_values.KEY, {"name": "delta", "value": 0.01, "threshold": 0.05,
                              "comparator": ">", "unit": "margin", "subject": "x"})
    ]
    ledger = build_oracle_ledger(
        {
            "passed": [_Report("calibration/test_a.py::test_ok", [])],
            "failed": [_Report("calibration/test_b.py::test_red", shared)],
        }
    )
    assert "values" not in ledger["calibration/test_a.py::test_ok"]
    red = ledger["calibration/test_b.py::test_red"]
    assert red["status"] == "failed"
    assert red["values"][0]["value"] == 0.01
