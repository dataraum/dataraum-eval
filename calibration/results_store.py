"""Immutable verdict store (DAT-862 slice 1) — regression is a query, not a memory.

Every assert pass appends one JSON line per Tier-3 oracle to
``calibration/results/verdicts.jsonl`` — git-tracked, append-only by construction
(the writer only ever opens in append mode; history rewrites would show in git).
Each row names the oracle, its cube declaration (vertical / from_stage / oracle
version, DAT-860), the dataset graded, the verdict (ALL statuses — a skip is
first-class evidence, the charter's vacuous-pass rule), and the exact code that
produced it (eval + engine commits, the run's run_id). "Did this regress?" is then
a diff between the last two passes — no re-run, no human memory.

This store replaces nothing yet: ``coverage_baselines/`` (the blessed graded-set)
stays until the store has enough history to take over its job (the DAT-862 ticket's
full scope). Slice 1 is: record everything from now on, so sweep #1 onward writes
history.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

EVAL_ROOT = Path(__file__).parent.parent
STORE = Path(__file__).parent / "results" / "verdicts.jsonl"
ENGINE_DIR = EVAL_ROOT / "vendor" / "dataraum-context"


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


def _dataset_vertical(strategy: str) -> str:
    """The graded dataset's vertical: wild corpora carry their own, synthetic = finance."""
    from calibration import corpora

    spec = corpora.get(strategy)
    return spec.vertical if spec else "finance"


def _tier3_rows(ledger: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    """Tier-3 oracle nodeids only — unit (Tier-1/2) verdicts are not run records."""
    return {
        nid: entry
        for nid, entry in ledger.items()
        if nid.startswith("calibration/test_")
    }


def record_pass(
    strategy: str,
    ledger: dict[str, dict[str, str]],
    *,
    store: Path = STORE,
) -> int:
    """Append one assert pass's Tier-3 verdicts. Returns the number of rows written.

    Called from ``conftest.pytest_terminal_summary`` after the coverage ledger is
    built — every pass from sweep #1 onward writes history. One ``pass_id`` groups
    the batch; the diff queries below compare pass to pass.
    """
    rows = _tier3_rows(ledger)
    if not rows:
        return 0

    from calibration import cube

    reg = cube.registry()
    pass_id = uuid.uuid4().hex[:12]
    recorded_at = datetime.now(UTC).isoformat(timespec="seconds")
    eval_commit = _commit(EVAL_ROOT)
    engine_commit = _commit(ENGINE_DIR)
    run_id = _run_id(strategy)
    vertical = _dataset_vertical(strategy)

    store.parent.mkdir(parents=True, exist_ok=True)
    with open(store, "a") as f:
        for nid, entry in sorted(rows.items()):
            module = Path(nid.split("::", 1)[0]).stem
            spec = reg.get(module)
            row = {
                "pass_id": pass_id,
                "recorded_at": recorded_at,
                "dataset": strategy,
                "vertical": vertical,
                "oracle": nid,
                "module": module,
                "status": entry.get("status", ""),
                "reason": entry.get("reason", ""),
                "oracle_version": spec.version if spec else None,
                "from_stage": spec.from_stage if spec else None,
                "eval_commit": eval_commit,
                "engine_commit": engine_commit,
                "engine_on_main": _on_main(ENGINE_DIR),
                "run_id": run_id,
            }
            f.write(json.dumps(row, sort_keys=True) + "\n")
    return len(rows)


def load(*, store: Path = STORE) -> list[dict[str, Any]]:
    """Every recorded verdict row, oldest first."""
    if not store.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in store.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def passes(strategy: str, *, store: Path = STORE) -> list[list[dict[str, Any]]]:
    """The strategy's recorded passes, oldest first, each a list of verdict rows."""
    by_pass: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for row in load(store=store):
        if row.get("dataset") != strategy:
            continue
        pid = row["pass_id"]
        if pid not in by_pass:
            by_pass[pid] = []
            order.append(pid)
        by_pass[pid].append(row)
    return [by_pass[pid] for pid in order]


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
    args = parser.parse_args()

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
