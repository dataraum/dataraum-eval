"""The tracked (corpus → vertical) pairings — the CAP-vertical-dataset-match seam.

Wild corpora are staged from external sources; each is paired with a *vertical* (a named
concept bundle the engine grounds columns against). ``calibration/corpus_registry.yaml``
holds that PAIRING — which corpus wears which vertical, from which source, at which tier
— in ONE place, so it is a tracked, gradeable pairing rather than a constant baked into a
code path. The concept CONTENT stays in ``scripts/frame_wild_vertical.py`` until frame
induction (DAT-738) can induce it from the dataset; the induced vertical will then be
graded against the pairing declared here (docs/generator_backlog.yaml).

The registry lives under ``calibration/`` (tracked config), NOT under ``corpora/`` (which
is gitignored wholesale — NC-licensed wild DATA is fetched, never committed). A vertical
is product configuration, not ground truth — the registry records the pairing so it is
deliberate, nothing more. Pure (yaml + dataclass), so Tier-1 exercises it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

EVAL_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = EVAL_ROOT / "calibration" / "corpus_registry.yaml"


@dataclass(frozen=True)
class CorpusSpec:
    """One tracked wild-corpus pairing."""

    name: str
    source: str  # relbench | ... (where the raw corpus is fetched from)
    vertical: str  # the vertical id it wears — defaults to ``name``
    tier: str = "wild"


def load_registry(path: Path = REGISTRY) -> dict[str, CorpusSpec]:
    """Parse the registry into ``name -> CorpusSpec`` (empty if the file is absent)."""
    if not path.exists():
        return {}
    data: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    out: dict[str, CorpusSpec] = {}
    for name, raw in (data.get("corpora") or {}).items():
        spec = raw or {}
        out[name] = CorpusSpec(
            name=name,
            source=str(spec.get("source") or ""),
            vertical=str(spec.get("vertical") or name),  # defaults to the corpus name
            tier=str(spec.get("tier") or "wild"),
        )
    return out


def wild_corpora(path: Path = REGISTRY) -> dict[str, CorpusSpec]:
    """Just the wild-tier corpora."""
    return {n: s for n, s in load_registry(path).items() if s.tier == "wild"}


def get(name: str, path: Path = REGISTRY) -> CorpusSpec | None:
    """The spec for ``name``, or ``None`` if it is not a registered corpus."""
    return load_registry(path).get(name)
