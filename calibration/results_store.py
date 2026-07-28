"""Immutable verdict store (DAT-862) — regression is a query, not a memory.

Every assert pass appends one JSON line per Tier-3 oracle to
``calibration/results/verdicts.jsonl`` — git-tracked, append-only by construction
(the writer only ever opens in append mode; history rewrites would show in git).
Each row names the oracle, its cube declaration (vertical / from_stage / oracle
version / dimension, DAT-860), the dataset graded, the verdict (ALL statuses — a
skip is first-class evidence, the charter's vacuous-pass rule), and the exact code
that produced it (eval + engine commits, the run's run_id). "Did this regress?" is
then a diff between the last two passes — no re-run, no human memory.

**The four comparability extensions** (RFC 3 lane A4 / RFC 5), which turn the store
from a regression alarm into a trend instrument:

1. **Values, not only statuses** (``values`` on a row, ``verdict_values``): the
   measured number and the threshold that judged it. A pass/fail cannot say the
   margin halved. This is what lets DAT-687 report a pipeline-error *distribution*
   instead of a pass rate — ``values(ds, name="relative_error")``.
2. **Wild runs write here too** (``tier``, ``record_scoreboard``): same schema, same
   coordinates. The standing rule is unchanged and is now structural — scoreboard
   rows are ``kind='scoreboard'`` and no verdict query can see them, because wild
   data has no recall truth and a fire rate must never become a gate.
3. **``dimension`` as a coordinate** (``dimension_status``): the coverage map's
   lit / partial / dark gate reads off the store instead of off a claim. *Lit*
   requires a value that was judged AND held — a reported-only number never lights
   a dimension.
4. **Reducer variance reported** (``variance``): flip rates and value spread over
   repeats at one pin, computed from passes that already happened. Reported, never
   suppressed, and never an override of a judge.

This store replaces nothing yet: ``coverage_baselines/`` (the blessed graded-set)
stays until the store has enough history to take over its job. Still open on the
ticket: the verdict-leg split (threshold/verdict as a separately versioned object
out of detector-specific test code).
"""

from __future__ import annotations

import json
import statistics
import subprocess
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

from calibration import verdict_values

EVAL_ROOT = Path(__file__).parent.parent
STORE = Path(__file__).parent / "results" / "verdicts.jsonl"
ENGINE_DIR = EVAL_ROOT / "vendor" / "dataraum-context"

# What a row IS. An oracle row is a VERDICT (it passed, failed, stood down); a
# scoreboard row is a REPORTED measurement off a wild run (RFC 5 ext 2) and is
# excluded from every verdict query — wild data has no recall truth, so a fire rate
# can never be a pass/fail. Rows written before the split carry no ``kind`` and are
# read as oracle rows (``_kind``).
KIND_ORACLE = "oracle"
KIND_SCOREBOARD = "scoreboard"


def _kind(row: dict[str, Any]) -> str:
    """A row's kind, defaulting pre-split rows to ``oracle``."""
    return str(row.get("kind") or KIND_ORACLE)


@cache
def _commit(repo: Path) -> str:
    """Short commit hash + ``+dirty`` marker — the provenance a verdict is pinned to.

    The engine is keyed by its SUBMODULE COMMIT, not a version string (DAT-861
    ruling): a stale-but-plausible cached artifact is the silent failure mode, and
    the commit hash is the only key that moves when the engine does.
    """
    try:
        head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return f"{head}+dirty" if dirty else head
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


@cache
def _on_main(repo: Path) -> bool | None:
    """Is the repo's HEAD an ancestor of origin/main? The durable-identity check.

    DAT-736 pin protocol: the engine's epic branch is REBASED onto main when main
    moves, so an epic-tip SHA is a fine development target but a bad durable identity
    for verdicts — it can vanish from history. Dev-pin passes record
    ``engine_on_main=False`` (self-identifying, still useful iteration data); graded
    sweeps must record on-main commits. Best-effort: reads the locally-fetched
    ``origin/main`` (a stale fetch can read False for a fresh main commit); ``None``
    when undeterminable. The field is a hint for queries — the protocol is the rule.
    """
    try:
        res = subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor",
             "HEAD", "refs/remotes/origin/main"],
            capture_output=True,
        )
    except OSError:
        return None
    if res.returncode == 0:
        return True
    if res.returncode == 1:
        return False
    return None  # ref missing / not a repo — undeterminable, not "off main"


def _run_id(strategy: str) -> str:
    """The pipeline run this verdict graded, from the strategy's sidecar."""
    sidecar = EVAL_ROOT / "output" / strategy / "calibration_run.json"
    if not sidecar.exists():
        return ""
    try:
        return str(json.loads(sidecar.read_text()).get("run_id", ""))
    except (OSError, ValueError):
        return ""


def _coordinates(strategy: str) -> tuple[str, str]:
    """``(vertical, tier)`` for the graded dataset — the cube axes a row is keyed on.

    Wild corpora carry their own vertical and ``tier: wild`` from the committed
    registry; anything else is the synthetic finance backbone. The tier rides on the
    row (DAT-862 / RFC 5 ext 2) so wild results are retained WITHOUT ever being
    mistaken for a gate: wild data has no recall truth, so a wild row is a finding,
    never a correctness verdict. A query that forgets to filter tier would otherwise
    average the two, which is the one thing the corpus policy forbids.
    """
    from calibration import corpora

    spec = corpora.get(strategy)
    return (spec.vertical, spec.tier) if spec else ("finance", "synthetic")


def _tier3_rows(ledger: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Tier-3 oracle nodeids only — unit (Tier-1/2) verdicts are not run records."""
    return {
        nid: entry
        for nid, entry in ledger.items()
        if nid.startswith("calibration/test_")
    }


def _provenance(strategy: str) -> dict[str, Any]:
    """The coordinates every row of one pass shares — commits, run, dataset axes."""
    vertical, tier = _coordinates(strategy)
    return {
        "pass_id": uuid.uuid4().hex[:12],
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dataset": strategy,
        "vertical": vertical,
        "tier": tier,
        "eval_commit": _commit(EVAL_ROOT),
        "engine_commit": _commit(ENGINE_DIR),
        "engine_on_main": _on_main(ENGINE_DIR),
        "run_id": _run_id(strategy),
    }


def record_pass(
    strategy: str,
    ledger: dict[str, dict[str, Any]],
    *,
    store: Path = STORE,
    reg: dict[str, Any] | None = None,
) -> int:
    """Append one assert pass's Tier-3 verdicts. Returns the number of rows written.

    Called from ``conftest.pytest_terminal_summary`` after the coverage ledger is
    built — every pass from sweep #1 onward writes history. One ``pass_id`` groups
    the batch; the diff queries below compare pass to pass. ``reg`` overrides the
    cube registry (the Tier-1 seam — the real one is read otherwise).
    """
    rows = _tier3_rows(ledger)
    if not rows:
        return 0

    from calibration import cube

    reg = cube.registry() if reg is None else reg
    shared = _provenance(strategy)

    store.parent.mkdir(parents=True, exist_ok=True)
    with open(store, "a") as f:
        for nid, entry in sorted(rows.items()):
            module = Path(nid.split("::", 1)[0]).stem
            spec = reg.get(module)
            row: dict[str, Any] = {
                **shared,
                "kind": KIND_ORACLE,
                "oracle": nid,
                "module": module,
                "status": entry.get("status", ""),
                "reason": entry.get("reason", ""),
                "oracle_version": spec.version if spec else None,
                "from_stage": spec.from_stage if spec else None,
                "dimension": spec.dimension if spec else None,
            }
            # The numbers behind the verdict (RFC 5 ext 1) — the margin, not just
            # whether it held. Recorded on red rows too: that is the interesting one.
            if entry.get("values"):
                row["values"] = entry["values"]
            if nid.endswith("::test_bind_surface_fingerprinted_not_asserted"):
                detail = _bind_fingerprints(strategy)
                if detail is not None:
                    row["detail"] = {"sql_fingerprints": detail}
            f.write(json.dumps(row, sort_keys=True) + "\n")
    return len(rows)


def record_scoreboard(
    strategy: str,
    board: Any,  # calibration.scoreboard.Scoreboard (imported lazily — no cycle)
    *,
    store: Path = STORE,
) -> int:
    """Retain a wild run's fire-rate scoreboard as store rows (RFC 5 ext 2).

    The wild lane graded a scoreboard and PRINTED it; nothing was kept, so "has our
    false-positive rate on unseen schemas moved?" was un-askable without re-running a
    real corpus through the pipeline. One row per detector, carrying its fire rate,
    coverage and score distribution as graded values under the pass's coordinates.

    These rows are ``kind='scoreboard'`` and are excluded from ``passes()`` /
    ``diff_last_two`` by construction: a fire rate is a **finding surface**, never a
    verdict, and a wild corpus has no recall truth to make it one. The flags
    (mute / never-fired / saturated) stay triage prompts — retaining them makes the
    triage comparable across runs, it does not promote them to gates.
    """
    stats = list(board.per_detector)
    if not stats:
        return 0

    shared = _provenance(strategy)
    flags = {
        "mute": set(board.mute),
        "never_fired": set(board.never_fired),
        "saturated": set(board.saturated),
    }

    store.parent.mkdir(parents=True, exist_ok=True)
    with open(store, "a") as f:
        for d in sorted(stats, key=lambda s: s.detector_id):
            values = [
                asdict(verdict_values.make(
                    "fire_rate", d.fire_rate, unit="ratio", subject=d.detector_id,
                )),
                asdict(verdict_values.make(
                    "n_measured", d.n_measured, unit="count", subject=d.detector_id,
                )),
                asdict(verdict_values.make(
                    "n_abstained", d.n_abstained, unit="count", subject=d.detector_id,
                )),
                asdict(verdict_values.make(
                    "n_targets", d.n_targets, unit="count", subject=d.detector_id,
                )),
            ]
            if d.score_mean is not None:
                values.append(asdict(verdict_values.make(
                    "score_mean", d.score_mean, unit="score", subject=d.detector_id,
                )))
            if d.score_max is not None:
                values.append(asdict(verdict_values.make(
                    "score_max", d.score_max, unit="score", subject=d.detector_id,
                )))
            row: dict[str, Any] = {
                **shared,
                "kind": KIND_SCOREBOARD,
                "oracle": f"scoreboard::{d.detector_id}",
                "module": "scoreboard",
                "status": "reported",  # a scoreboard reports; it never passes or fails
                "reason": "",
                "detector_status": d.status,
                "flags": sorted(name for name, ids in flags.items() if d.detector_id in ids),
                "values": values,
            }
            f.write(json.dumps(row, sort_keys=True) + "\n")
    return len(stats)


def _bind_fingerprints(strategy: str) -> dict[str, str] | None:
    """The parity oracle's per-pass sql_used fingerprint sidecar, if it wrote one.

    Written by ``test_bind_surface_fingerprinted_not_asserted`` (Q3: the VERDICT is
    never persisted, the grounded BIND is) — attaching it to the verdict row makes
    cross-pass bind parity a store query instead of a run-log archaeology dig.
    """
    path = EVAL_ROOT / "output" / strategy / "parity_fingerprints.json"
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def bind_parity(strategy: str, *, store: Path = STORE) -> list[dict[str, Any]]:
    """The sweep-#2 read-out: bind fingerprints per pass, oldest first.

    Each entry: ``{pass_id, recorded_at, engine_commit, fingerprints}``. Drift in a
    deterministic check's fingerprint across same-engine passes is a bind-stability
    finding; ``sign_conventions`` is the known flapper (reduced-verdict parity, Q3).
    """
    out: list[dict[str, Any]] = []
    for pass_rows in passes(strategy, store=store):
        for row in pass_rows:
            fps = (row.get("detail") or {}).get("sql_fingerprints")
            if fps and row["oracle"].endswith("::test_bind_surface_fingerprinted_not_asserted"):
                out.append(
                    {
                        "pass_id": row["pass_id"],
                        "recorded_at": row["recorded_at"],
                        "engine_commit": row["engine_commit"],
                        "fingerprints": fps,
                    }
                )
    return out


def load(*, store: Path = STORE) -> list[dict[str, Any]]:
    """Every recorded verdict row, oldest first."""
    if not store.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in store.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def passes(
    strategy: str, *, store: Path = STORE, kind: str = KIND_ORACLE
) -> list[list[dict[str, Any]]]:
    """The strategy's recorded passes, oldest first, each a list of rows of ``kind``.

    Defaults to VERDICT rows: the scoreboard rows a wild run retains are reported
    measurements, and letting them into a regression diff would invent a regression
    out of a fire rate that legitimately moved on messy real data.
    """
    by_pass: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for row in load(store=store):
        if row.get("dataset") != strategy or _kind(row) != kind:
            continue
        pid = row["pass_id"]
        if pid not in by_pass:
            by_pass[pid] = []
            order.append(pid)
        by_pass[pid].append(row)
    return [by_pass[pid] for pid in order]


# ---------------------------------------------------------------------------
# The trend instrument (RFC 5 ext 1 + 4): values, their spread, their dimension
# ---------------------------------------------------------------------------


def values(
    strategy: str,
    *,
    name: str | None = None,
    subject: str | None = None,
    store: Path = STORE,
    kind: str = KIND_ORACLE,
) -> list[dict[str, Any]]:
    """Every graded value recorded for ``strategy``, oldest first, flattened.

    Each entry carries the value's own fields plus the pass coordinates it was
    measured under — so a pipeline-error distribution (DAT-687) is
    ``values(ds, name="relative_error")`` and nothing else.
    """
    out: list[dict[str, Any]] = []
    for pass_rows in passes(strategy, store=store, kind=kind):
        for row in pass_rows:
            for val in row.get("values") or []:
                if name is not None and val.get("name") != name:
                    continue
                if subject is not None and val.get("subject") != subject:
                    continue
                out.append(
                    {
                        **val,
                        "pass_id": row["pass_id"],
                        "recorded_at": row["recorded_at"],
                        "engine_commit": row["engine_commit"],
                        "oracle": row["oracle"],
                        "oracle_version": row.get("oracle_version"),
                        "dimension": row.get("dimension"),
                        "tier": row.get("tier"),
                    }
                )
    return out


def _spread(sample: list[float]) -> dict[str, Any]:
    """n / min / max / mean / stdev over repeated measurements of one thing.

    The sample standard deviation (``statistics.stdev``, Bessel-corrected) is the
    named statistic; ``n < 2`` reports ``None`` rather than a fabricated ``0.0``.
    """
    return {
        "n": len(sample),
        "min": min(sample),
        "max": max(sample),
        "mean": statistics.fmean(sample),
        "stdev": statistics.stdev(sample) if len(sample) > 1 else None,
    }


def variance(
    strategy: str, *, store: Path = STORE, engine_commit: str | None = None
) -> dict[str, Any]:
    """Non-determinism as a REPORTED statistic, over passes already recorded.

    RFC 5 ext 4: the discipline for a flapping judgment is epochs plus a named
    reducer with the reducer's variance reported — never an override of a judge and
    never a relaxed oracle (that is Goodhart at the harness level). With values in
    the store this is computable from the passes that already happen, so it costs no
    tokens and needs no new run.

    Repeats are grouped by ``(engine_commit, eval_commit)`` — both sides of the code
    identical, so the only thing that differed is the draw. Two passes on different
    commits differ for a reason, and calling that "variance" would launder a real
    regression into noise; an oracle whose ``version`` moved inside a group is
    likewise excluded (a version bump IS a different oracle). Within a group:

      * ``flapping`` — oracles whose STATUS was not identical across the repeats,
        with the observed statuses and the flip rate (share of adjacent passes that
        changed verdict), the known live case being ~25% 1:1 FK-orientation flips;
      * ``value_spread`` — per (oracle, value name, subject), the spread above.

    **Disagreement here is reported, not diagnosed.** A flip can be a fresh LLM draw,
    but it can equally be a pass graded against an incomplete run (DAT-877) or a
    ``+dirty`` working tree that differed between the two passes — ``dirty`` on the
    group says the commit pair is not a durable identity. Reading every flip as
    "just non-determinism" would bury exactly the bugs this store exists to surface.

    ``engine_commit`` narrows to one pin; omitted, every pin with ≥2 passes reports.
    """
    groups: dict[tuple[str, Any], list[list[dict[str, Any]]]] = {}
    for pass_rows in passes(strategy, store=store):
        commit = str(pass_rows[0].get("engine_commit") or "")
        if engine_commit is not None and commit != engine_commit:
            continue
        groups.setdefault((commit, pass_rows[0].get("eval_commit")), []).append(pass_rows)

    report: dict[str, Any] = {"strategy": strategy, "groups": []}
    for (commit, eval_commit), repeats in sorted(groups.items()):
        if len(repeats) < 2:
            continue
        statuses: dict[str, list[str]] = {}
        samples: dict[tuple[str, str, str], list[float]] = {}
        versions: dict[str, set[Any]] = {}
        for pass_rows in repeats:
            for row in pass_rows:
                statuses.setdefault(row["oracle"], []).append(row["status"])
                versions.setdefault(row["oracle"], set()).add(row.get("oracle_version"))
                for val in row.get("values") or []:
                    key = (row["oracle"], str(val.get("name")), str(val.get("subject") or ""))
                    samples.setdefault(key, []).append(float(val["value"]))

        flapping = []
        for oracle, seen in sorted(statuses.items()):
            if len(set(seen)) < 2:
                continue
            if len(versions.get(oracle, set())) > 1:
                continue  # a version bump is a different oracle, not a flap
            flips = sum(1 for a, b in zip(seen, seen[1:], strict=False) if a != b)
            flapping.append(
                {
                    "oracle": oracle,
                    "statuses": seen,
                    "flip_rate": flips / (len(seen) - 1) if len(seen) > 1 else 0.0,
                }
            )

        spread = [
            {"oracle": o, "name": n, "subject": s, **_spread(sample)}
            for (o, n, s), sample in sorted(samples.items())
            if len(sample) > 1
        ]
        report["groups"].append(
            {
                "engine_commit": commit,
                "eval_commit": eval_commit,
                "repeats": len(repeats),
                # A dirty tree is not a durable identity — two "same-pin" passes may
                # have run different code. Say so rather than implying same-code.
                "dirty": "dirty" in commit or "dirty" in str(eval_commit),
                "flapping": flapping,
                "value_spread": [s for s in spread if s["stdev"]],
            }
        )
    return report


def dimension_status(strategy: str, *, store: Path = STORE) -> dict[str, str]:
    """Per-dimension read-out off the last pass: ``lit`` / ``partial`` / ``dark``.

    The coverage map's honesty gate (RFC 3 B2 / RFC 5 ext 3), computed from the
    store instead of from a hand-maintained claim:

      * **lit** — a dimension-tagged oracle GRADED a value of that dimension and the
        value HELD its threshold. Graded means judged: a reported-only number
        (``held is None``) never lights a dimension.
      * **partial** — a dimension-tagged oracle reached a verdict, but no judged
        value backs it (grounded-but-ungraded, or judged and out of tolerance).
      * **dark** — no dimension-tagged oracle graded at all (a skip counts as dark).

    Dimensions with no declared oracle are absent from the result, not ``dark``:
    "nothing claims this" and "something claims it and failed" are different facts,
    and the map must not blur them.
    """
    history = passes(strategy, store=store)
    if not history:
        return {}
    graded = {"passed", "failed", "xfailed", "xpassed"}
    rank = {"dark": 0, "partial": 1, "lit": 2}
    out: dict[str, str] = {}
    for row in history[-1]:
        dim = row.get("dimension")
        if not dim:
            continue
        state = "dark"
        if row["status"] in graded:
            state = "partial"
            for val in row.get("values") or []:
                if verdict_values.from_payload(val).held:
                    state = "lit"
                    break
        # A declared dimension always appears (dark if nothing graded it); several
        # oracles on one dimension take the BEST — one graded metric lights it.
        if rank[state] >= rank.get(out.setdefault(dim, "dark"), 0):
            out[dim] = state
    return out


def fire_rates(strategy: str, *, store: Path = STORE) -> list[dict[str, Any]]:
    """Per-detector fire rate across the wild passes retained for ``strategy``.

    The wild-lane trend question ("has our false-positive rate on unseen schemas
    moved?"), answered without re-running a real corpus. Findings, never gates.
    """
    per_detector: dict[str, list[dict[str, Any]]] = {}
    for pass_rows in passes(strategy, store=store, kind=KIND_SCOREBOARD):
        for row in pass_rows:
            for val in row.get("values") or []:
                if val.get("name") != "fire_rate":
                    continue
                per_detector.setdefault(str(val.get("subject")), []).append(
                    {
                        "recorded_at": row["recorded_at"],
                        "engine_commit": row["engine_commit"],
                        "fire_rate": float(val["value"]),
                        "flags": row.get("flags") or [],
                    }
                )
    return [
        {"detector_id": det, "observations": obs}
        for det, obs in sorted(per_detector.items())
    ]


def diff_last_two(strategy: str, *, store: Path = STORE) -> dict[str, Any]:
    """The regression query: last pass vs the one before, per oracle.

    Returns ``{"changed": {oracle: (prev, curr)}, "gone": [...], "new": [...]}``.
    A changed or vanished verdict is a FINDING TO TRIAGE (test-suite bug vs engine
    bug vs intended surface change), never an automatic engine-blame — same rule as
    the coverage baseline diff.
    """
    history = passes(strategy, store=store)
    if len(history) < 2:
        return {"changed": {}, "gone": [], "new": [], "passes": len(history)}
    prev = {r["oracle"]: r["status"] for r in history[-2]}
    curr = {r["oracle"]: r["status"] for r in history[-1]}
    changed = {
        nid: (prev[nid], curr[nid])
        for nid in prev.keys() & curr.keys()
        if prev[nid] != curr[nid]
    }
    return {
        "changed": changed,
        "gone": sorted(prev.keys() - curr.keys()),
        "new": sorted(curr.keys() - prev.keys()),
        "passes": len(history),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="verdict store queries (DAT-862)")
    parser.add_argument("-s", "--strategy", required=True)
    parser.add_argument(
        "--bind-parity", action="store_true",
        help="sweep-#2 read-out: seed-validation sql_used fingerprints across passes",
    )
    parser.add_argument(
        "--values", metavar="NAME", nargs="?", const="",
        help="graded values across passes (optionally one statistic, e.g. relative_error)",
    )
    parser.add_argument(
        "--variance", action="store_true",
        help="reducer variance: status flips + value spread over repeats at one pin",
    )
    parser.add_argument(
        "--dimensions", action="store_true",
        help="per-dimension coverage read off the last pass (lit / partial / dark)",
    )
    parser.add_argument(
        "--fire-rates", action="store_true",
        help="wild-lane detector fire rates across retained scoreboards",
    )
    args = parser.parse_args()

    if args.values is not None:
        rows = values(args.strategy, name=args.values or None)
        if not rows:
            print(f"{args.strategy}: no graded values recorded yet")
            return
        for v in rows:
            bar = (
                f" {v['comparator']} {v['threshold']}"
                if v.get("comparator") and v.get("threshold") is not None
                else "  (reported)"
            )
            held = verdict_values.from_payload(v).held
            mark = {True: "ok ", False: "OFF", None: " · "}[held]
            print(f"  [{mark}] {v['recorded_at']}  {v['name']:<22} "
                  f"{v['value']:>12.4f}{bar:<16}  {v.get('subject', '')}")
        return

    if args.variance:
        report = variance(args.strategy)
        if not report["groups"]:
            print(f"{args.strategy}: no repeated pass at a single (engine, eval) pin — "
                  "variance needs >= 2 passes on identical code")
            return
        for g in report["groups"]:
            print(f"engine {g['engine_commit']} / eval {g['eval_commit']} — "
                  f"{g['repeats']} repeat(s)"
                  + ("   ⚠ dirty tree: not the same code by proof" if g["dirty"] else ""))
            for f in g["flapping"]:
                print(f"  FLAP  flip_rate={f['flip_rate']:.2f}  "
                      f"{'→'.join(f['statuses'])}  {f['oracle'].split('::', 1)[-1]}")
            for s in g["value_spread"]:
                print(f"  SPREAD {s['name']:<22} n={s['n']} "
                      f"[{s['min']:.4f}, {s['max']:.4f}] mean={s['mean']:.4f} "
                      f"sd={s['stdev']:.4f}  {s['subject']}")
            if not (g["flapping"] or g["value_spread"]):
                print("  stable across the repeats")
        return

    if args.dimensions:
        status = dimension_status(args.strategy)
        if not status:
            print(f"{args.strategy}: no oracle declares a performance dimension yet "
                  "(the axis ships empty until DAT-884/DAT-855 land — cube.DIMENSIONS)")
            return
        for dim, state in sorted(status.items()):
            print(f"  {dim:<12} {state}")
        return

    if args.fire_rates:
        rates = fire_rates(args.strategy)
        if not rates:
            print(f"{args.strategy}: no wild scoreboard retained "
                  "(scoreboards are recorded from the wild lane only)")
            return
        for entry in rates:
            obs = entry["observations"]
            trail = " → ".join(f"{o['fire_rate']:.2f}" for o in obs)
            flags = ",".join(sorted({f for o in obs for f in o["flags"]}))
            print(f"  {entry['detector_id']:<28} {trail}"
                  + (f"   [{flags}]" if flags else ""))
        return

    if args.bind_parity:
        entries = bind_parity(args.strategy)
        if not entries:
            print(f"{args.strategy}: no fingerprint-bearing passes recorded yet")
            return
        ids = sorted({vid for e in entries for vid in e["fingerprints"]})
        for e in entries:
            print(f"pass {e['pass_id']} ({e['recorded_at']}, engine {e['engine_commit']}):")
            for vid in ids:
                print(f"  {vid:<28} {e['fingerprints'].get(vid, '—')}")
        if len(entries) >= 2:
            prev, curr = entries[-2]["fingerprints"], entries[-1]["fingerprints"]
            drift = sorted(v for v in ids if prev.get(v) != curr.get(v))
            print("drift vs previous pass: " + (", ".join(drift) if drift else "none"))
        return

    history = passes(args.strategy)
    print(f"{args.strategy}: {len(history)} recorded pass(es)")
    if not history:
        return
    last = history[-1]
    counts: dict[str, int] = {}
    for row in last:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(f"last pass ({last[0]['recorded_at']}, engine {last[0]['engine_commit']}): "
          + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    diff = diff_last_two(args.strategy)
    if diff["passes"] < 2:
        print("no prior pass to diff against")
        return
    if not (diff["changed"] or diff["gone"] or diff["new"]):
        print("no verdict changes vs previous pass")
        return
    for nid, (a, b) in sorted(diff["changed"].items()):
        print(f"  CHANGED {a} → {b}  {nid.split('::', 1)[-1]}")
    for nid in diff["gone"]:
        print(f"  GONE    {nid.split('::', 1)[-1]}")
    for nid in diff["new"]:
        print(f"  NEW     {nid.split('::', 1)[-1]}")


if __name__ == "__main__":
    main()
