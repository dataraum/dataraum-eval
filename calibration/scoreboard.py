"""Wild fire-rate scoreboard — the frontier grade when there is no recall truth.

A wild corpus has no injections, so recall is unassertable: you did not put anything
in, and a silently-broken detector that finds *nothing* looks exactly like a clean
pass (charter, "The frontier and the backbone"). Wild data can *falsify* "we're
great"; it can never *certify* "we're correct." This is the instrument that reads a
completed wild run and turns "nothing fired" from an invisible green into a visible,
triageable **finding**.

It computes, per detector, over the head-resolved ``current_entropy_objects`` rows
(the SAME read path the oracles use — never PhaseLog):

- **coverage** — how many targets it produced a row for at all (measured + abstained);
- **fire rate** — of its MEASURED rows, the fraction that scored above zero (a positive
  entropy score is the detector claiming *some* disagreement; ``0.0`` is "perfect fit");
- **score distribution** — min / median / max / mean over measured rows, so
  "fires weakly on everything" is distinguishable from "fires hard on a few".

Three flags surface the findings — each a **triage prompt, never a verdict**. Wild
data is genuinely messy, so a high fire rate can be real signal, not over-fire; the
scoreboard points, a human adjudicates, and a confirmed miss/over-fire is filed as a
:class:`~calibration.findings.Finding` and graduated. The flags:

- **mute** — an in-slice detector that produced ZERO rows. The phase didn't run, or the
  detector errored silently. The strongest "found nothing" signal, and the one the
  charter warns is invisible without an instrument like this.
- **never-fired** — an in-slice detector that ran (has measured rows) but scored ``0.0``
  on every one. Either the corpus is genuinely clean for that dimension, or the detector
  is dead. On messy wild data, suspicious.
- **saturated** — a detector that fired on ~everything (``fire_rate`` over a heuristic
  cut, with enough measured rows to matter). A possible over-fire / miscalibration.

The saturation cut is a HIGHLIGHTER over honest counts, not a grounded statistic we
hold the engine to — the counts and the distribution are the data; the flag just says
"look here". It never fails a run (wild oracles stand down; the scoreboard is a
scoreboard).

    uv run python -m calibration.scoreboard rel-f1
"""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any

# Fire = a MEASURED row with a strictly positive entropy score. 0.0 means "no
# disagreement / perfect fit"; anything above is the detector claiming something. A
# uniform, engine-agnostic cut — the score distribution below shows whether fires are
# strong or noise-floor, so this stays honest without a per-detector threshold.
FIRE_THRESHOLD = 0.0

# Triage heuristics for the FLAGS — not calibrated cuts and not statistics we grade
# the engine against (see the module docstring). A detector firing on >=90% of >=5
# measured targets is worth a human's eye; below that the fire_rate column carries it.
SATURATION_FRACTION = 0.9
SATURATION_MIN_N = 5


@dataclass(frozen=True)
class DetectorFireStats:
    """One detector's fire profile over a run's entropy rows (all fields derived)."""

    detector_id: str
    in_slice: bool
    n_targets: int  # distinct targets with ANY row (measured or abstained) — coverage
    n_measured: int
    n_abstained: int
    n_fired: int  # measured rows scoring above FIRE_THRESHOLD
    fire_rate: float  # n_fired / n_measured; 0.0 when n_measured == 0
    score_min: float | None
    score_median: float | None
    score_max: float | None
    score_mean: float | None


@dataclass
class Scoreboard:
    strategy: str
    total_rows: int
    per_detector: list[DetectorFireStats] = field(default_factory=list)
    # Findings surface — in-slice detectors only (out-of-slice silence is expected).
    mute: list[str] = field(default_factory=list)  # zero rows — didn't run / died silent
    never_fired: list[str] = field(default_factory=list)  # ran, flagged nothing
    saturated: list[str] = field(default_factory=list)  # fired on ~everything
    # Detectors that emitted rows but are NOT in the asserted slice — informational.
    off_slice_active: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["fire_threshold"] = FIRE_THRESHOLD
        d["saturation_fraction"] = SATURATION_FRACTION
        return d


def build_scoreboard(
    rows: list[Any],
    slice_detectors: frozenset[str],
    *,
    strategy: str = "",
    abstained_status: str = "abstained",
) -> Scoreboard:
    """Aggregate head-resolved entropy rows into a fire-rate scoreboard (pure).

    ``rows`` carry ``detector_id`` / ``target`` / ``status`` / ``score`` (the
    ``current_entropy_objects`` shape). ``slice_detectors`` is the set the recall lane
    asserts on (``CURRENT_SLICE_DETECTORS``) — silence is only a finding for those; an
    out-of-slice detector's silence is expected. ``abstained_status`` defaults to the
    engine's ``STATUS_ABSTAINED`` value; the CLI passes the real constant so production
    never depends on this default. Pure, so Tier-1 exercises it on synthetic rows with
    no pipeline and no engine bootstrap.
    """
    # detector_id -> {"targets": set, "measured_scores": list, "n_abstained": int}
    acc: dict[str, dict[str, Any]] = {}
    for r in rows:
        det = r.detector_id
        bucket = acc.setdefault(
            det, {"targets": set(), "measured_scores": [], "n_abstained": 0}
        )
        bucket["targets"].add(r.target)
        if r.status == abstained_status:
            bucket["n_abstained"] += 1
            continue
        if r.score is None:
            # A MEASURED row with a NULL score violates the engine's status/score
            # pairing (corrupt) — fail loud, never treat as a silent non-fire.
            raise ValueError(
                "measured entropy row has a NULL score (corrupt — violates the engine's "
                f"status/score pairing): {det} on {r.target}"
            )
        bucket["measured_scores"].append(float(r.score))

    per_detector: list[DetectorFireStats] = []
    for det, b in acc.items():
        scores: list[float] = b["measured_scores"]
        n_measured = len(scores)
        n_fired = sum(1 for s in scores if s > FIRE_THRESHOLD)
        per_detector.append(
            DetectorFireStats(
                detector_id=det,
                in_slice=det in slice_detectors,
                n_targets=len(b["targets"]),
                n_measured=n_measured,
                n_abstained=b["n_abstained"],
                n_fired=n_fired,
                fire_rate=(n_fired / n_measured) if n_measured else 0.0,
                score_min=min(scores) if scores else None,
                score_median=statistics.median(scores) if scores else None,
                score_max=max(scores) if scores else None,
                score_mean=statistics.mean(scores) if scores else None,
            )
        )
    # Loudest first: highest fire rate, then most measured — the over-fire suspects top.
    per_detector.sort(key=lambda s: (-s.fire_rate, -s.n_measured, s.detector_id))

    active = set(acc)
    mute = sorted(d for d in slice_detectors if d not in active)
    never_fired = sorted(
        s.detector_id
        for s in per_detector
        if s.in_slice and s.n_measured > 0 and s.n_fired == 0
    )
    saturated = sorted(
        s.detector_id
        for s in per_detector
        if s.n_measured >= SATURATION_MIN_N and s.fire_rate >= SATURATION_FRACTION
    )
    off_slice_active = sorted(d for d in active if d not in slice_detectors)

    return Scoreboard(
        strategy=strategy,
        total_rows=len(rows),
        per_detector=per_detector,
        mute=mute,
        never_fired=never_fired,
        saturated=saturated,
        off_slice_active=off_slice_active,
    )


def _fmt(x: float | None) -> str:
    return "—" if x is None else f"{x:.3f}"


def render(board: Scoreboard, *, is_wild: bool | None = None) -> str:
    """A human-facing table + findings block. Never blames the engine — it points."""
    lines: list[str] = []
    tier = {True: "wild (no recall truth)", False: "synthetic (recall assertable)", None: "unknown tier"}[is_wild]
    lines.append(f"=== fire-rate scoreboard: {board.strategy}  [{tier}] ===")
    lines.append(f"    {board.total_rows} entropy rows over {len(board.per_detector)} detectors\n")
    lines.append(
        f"    {'detector':<26} {'slice':<5} {'tgts':>4} {'meas':>4} "
        f"{'abst':>4} {'fired':>5} {'fire%':>6}  {'min':>5} {'med':>5} {'max':>5}"
    )
    lines.append(f"    {'-' * 26} {'-' * 5} {'-' * 4} {'-' * 4} {'-' * 4} {'-' * 5} {'-' * 6}  {'-' * 5} {'-' * 5} {'-' * 5}")
    for s in board.per_detector:
        mark = "SAT" if s.detector_id in board.saturated else ("·" if s.n_fired else "0")
        lines.append(
            f"    {s.detector_id:<26} {'yes' if s.in_slice else 'no':<5} "
            f"{s.n_targets:>4} {s.n_measured:>4} {s.n_abstained:>4} {s.n_fired:>5} "
            f"{s.fire_rate * 100:>5.0f}% {mark:>1}  "
            f"{_fmt(s.score_min):>5} {_fmt(s.score_median):>5} {_fmt(s.score_max):>5}"
        )

    lines.append("\n  findings to triage (a scoreboard, not a verdict — file confirmed misses/over-fires):")
    if board.mute:
        lines.append(f"    ⚠ MUTE (in-slice, ZERO rows — phase didn't run or detector died silent): {', '.join(board.mute)}")
    if board.never_fired:
        lines.append(f"    ⚠ NEVER-FIRED (ran, scored 0.0 on every target): {', '.join(board.never_fired)}")
    if board.saturated:
        lines.append(f"    ⚠ SATURATED (fired on ≥{SATURATION_FRACTION:.0%} of ≥{SATURATION_MIN_N} targets — possible over-fire): {', '.join(board.saturated)}")
    if not (board.mute or board.never_fired or board.saturated):
        lines.append("    (none flagged — coverage looks live; read the distribution before trusting it)")
    if board.off_slice_active:
        lines.append(f"    · off-slice detectors that emitted (informational): {', '.join(board.off_slice_active)}")

    if is_wild is False:
        lines.append(
            "\n  note: this is a SYNTHETIC corpus — recall IS assertable here (the injection map). "
            "The scoreboard is descriptive; grade recall with the recall oracles, not fire rate."
        )
    return "\n".join(lines)


def _load_rows(strategy: str) -> list[Any]:
    """Head-resolved entropy rows for a completed run — mirrors measure.py's read path."""
    from calibration.conftest import _head_resolved_entropy_rows
    from calibration.tools._runs import load_run, workspace_session

    load_run(strategy)  # guard: the pipeline must have run (sidecar present)
    with workspace_session() as session:
        return _head_resolved_entropy_rows(session)


def _is_wild(strategy: str) -> bool | None:
    from calibration import runner

    path = runner.DATA_DIR / strategy / "metadata_truth.yaml"
    if not path.exists():
        return None
    try:
        import yaml

        from calibration.metadata_truth import is_wild

        return is_wild(yaml.safe_load(path.read_text()) or {})
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("strategy", help="a completed run to score (e.g. rel-f1)")
    parser.add_argument(
        "--no-write", action="store_true", help="print only; don't write the json artifact"
    )
    args = parser.parse_args()

    from dataraum.entropy.models import STATUS_ABSTAINED

    from calibration import runner
    from calibration.test_detector_recall import CURRENT_SLICE_DETECTORS

    rows = _load_rows(args.strategy)
    board = build_scoreboard(
        rows, CURRENT_SLICE_DETECTORS, strategy=args.strategy, abstained_status=STATUS_ABSTAINED
    )
    print(render(board, is_wild=_is_wild(args.strategy)))

    if not args.no_write:
        out = runner.OUTPUT_DIR / args.strategy / "fire_scoreboard.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(board.to_dict(), indent=2, sort_keys=False))
        print(f"\n  → {out.relative_to(runner.EVAL_ROOT)}")


if __name__ == "__main__":
    main()
