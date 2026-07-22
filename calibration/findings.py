"""The Finding as data (Phase 2) — machine-readable, vertical-scoped.

The charter says every complaint is backed by a NAMED STATISTIC and a deterministic
repro. Until now a finding was free text in a skill template that nothing read; this
makes it a validated object, so it can be queued on the generator backlog and
graduated into a permanent Tier-1/2 oracle. Pure — no pytest, no docker.

Vertical-scoped by construction (backlog item CAP-vertical-dataset-match): a finding
names the (vertical, dataset) it was found on, so eval is not finance-only in its
model even while finance is the only shipped vertical.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

KINDS = frozenset({"miss", "over-fire", "ungrounded-score", "wrong-metric", "stale-eval"})
DISPOSITIONS = frozenset({"DAT-ticket", "teach-scenario", "ours-to-fix", "graduate"})
STATUSES = frozenset({"open", "filed", "graduated", "declined"})

# A finding about a detector's SCORE must name the detector; a metric/eval finding
# (a wrong number, a stale oracle) need not.
_DETECTOR_KINDS = frozenset({"miss", "over-fire", "ungrounded-score"})

_REQUIRED = (
    "id", "kind", "title", "vertical", "dataset", "target",
    "named_statistic", "evidence", "disposition", "source",
)


@dataclass
class Finding:
    """One filed finding. Always valid once constructed (``__post_init__`` validates)."""

    id: str
    kind: str                # miss | over-fire | ungrounded-score | wrong-metric | stale-eval
    title: str               # one line
    vertical: str            # finance | rel-f1 | ... — prep for vertical-dataset match
    dataset: str             # the corpus that surfaced it (detection-v1, rel-f1, ...)
    target: str              # "table.column" or a metric id
    named_statistic: str     # KS | orphan-rate | Cramer's V | ... (charter: no finding without one)
    evidence: str            # numbers + the read that shows it
    disposition: str         # DAT-ticket | teach-scenario | ours-to-fix | graduate
    source: str              # where it surfaced (free text: "rel-f1 (wild)", "DAT-834")
    detector_id: str | None = None
    status: str = "open"     # open | filed | graduated | declined
    graduated_to: str = ""   # injection family + Tier-1/2 oracle nodeid, once graduated

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        for name in (
            "id", "title", "vertical", "dataset", "target", "named_statistic",
            "evidence", "source",
        ):
            if not (getattr(self, name) or "").strip():
                raise ValueError(
                    f"Finding {self.id or '<no id>'}: {name} is required and non-empty"
                )
        if self.kind not in KINDS:
            raise ValueError(f"Finding {self.id}: kind {self.kind!r} not in {sorted(KINDS)}")
        if self.disposition not in DISPOSITIONS:
            raise ValueError(
                f"Finding {self.id}: disposition {self.disposition!r} not in {sorted(DISPOSITIONS)}"
            )
        if self.status not in STATUSES:
            raise ValueError(f"Finding {self.id}: status {self.status!r} not in {sorted(STATUSES)}")
        if self.kind in _DETECTOR_KINDS and not (self.detector_id or "").strip():
            raise ValueError(
                f"Finding {self.id}: kind {self.kind!r} is about a detector's score, so "
                "detector_id is required"
            )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Finding:
        missing = [k for k in _REQUIRED if k not in d]
        if missing:
            raise ValueError(f"finding {d.get('id', '<no id>')}: missing keys {missing}")
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(d) - known)
        if unknown:
            raise ValueError(f"finding {d.get('id')}: unknown keys {unknown}")
        return cls(**d)

    def to_backlog_item(self) -> dict[str, Any]:
        """The ``docs/generator_backlog.yaml`` finding-kind entry for this finding."""
        if self.status == "graduated" or self.graduated_to:
            status = "graduated"
        elif self.status == "declined":
            status = "declined"
        else:
            status = "queued"
        return {
            "id": self.id,
            "kind": "finding",
            "title": self.title,
            "status": status,
            "source": self.source,
            "vertical": self.vertical,
            "dataset": self.dataset,
            "detector_id": self.detector_id,
            "named_statistic": self.named_statistic,
            "evidence": self.evidence,
            "graduated_to": self.graduated_to,
        }


def load_findings(path: str | Path) -> list[Finding]:
    """Load + validate the ``findings`` list from an investigation's findings.yaml."""
    data = yaml.safe_load(Path(path).read_text())
    if not isinstance(data, dict) or "findings" not in data:
        raise ValueError(f"{path}: no top-level `findings:` list")
    return [Finding.from_dict(item) for item in (data["findings"] or [])]
