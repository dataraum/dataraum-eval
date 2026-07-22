"""Corpus registry (Phase 3) — the tracked (corpus → vertical) pairing, Tier 1.

Exercises the pure loader against tmp registries: defaults, wild filtering, and the
vertical-defaults-to-name rule that keeps the pairing declarable without ceremony.
"""

from __future__ import annotations

from pathlib import Path

from calibration import corpora


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "registry.yaml"
    p.write_text(body)
    return p


def test_loads_spec_fields(tmp_path: Path) -> None:
    reg = _write(
        tmp_path,
        "corpora:\n"
        "  rel-f1:\n"
        "    source: relbench\n"
        "    vertical: rel-f1\n"
        "    tier: wild\n",
    )
    specs = corpora.load_registry(reg)
    assert set(specs) == {"rel-f1"}
    s = specs["rel-f1"]
    assert (s.name, s.source, s.vertical, s.tier) == ("rel-f1", "relbench", "rel-f1", "wild")


def test_vertical_defaults_to_corpus_name(tmp_path: Path) -> None:
    reg = _write(tmp_path, "corpora:\n  rel-hm:\n    source: relbench\n")
    s = corpora.get("rel-hm", reg)
    assert s is not None and s.vertical == "rel-hm" and s.tier == "wild"


def test_wild_filter_excludes_non_wild(tmp_path: Path) -> None:
    reg = _write(
        tmp_path,
        "corpora:\n"
        "  rel-f1:\n    source: relbench\n    tier: wild\n"
        "  demo:\n    source: local\n    tier: synthetic\n",
    )
    assert set(corpora.wild_corpora(reg)) == {"rel-f1"}


def test_missing_registry_is_empty(tmp_path: Path) -> None:
    assert corpora.load_registry(tmp_path / "nope.yaml") == {}
    assert corpora.get("rel-f1", tmp_path / "nope.yaml") is None


def test_shipped_registry_pairs_rel_f1() -> None:
    """The committed registry declares rel-f1 (the one wild corpus wired today)."""
    s = corpora.get("rel-f1")
    assert s is not None and s.source == "relbench" and s.tier == "wild"
