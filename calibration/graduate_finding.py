"""graduate_finding — scaffold a finding into a permanent Tier-1/2 oracle (Phase 2).

The keystone of the authenticity loop: a filed Finding becomes an injection family +
a deterministic oracle, so a bug found once (expensively, on wild data or a live run)
is monitored forever for free. Graduation = VERIFY A GENERATED DIFF, not write from
scratch.

Safety: writes only eval-owned paths — the oracle stub in ``calibration/unit/`` and
the generator backlog. The testdata injector + strategy entry are PRINTED for you to
place (cross-repo; you verify and paste). ``--dry-run`` writes nothing. A finding
with no ``repro`` is refused (the charter: no rumors). The generated oracle is
``@pytest.mark.skip`` so it does not fake-green the lane — Phase 1's coverage ledger
surfaces it as a skipped oracle awaiting its fixture + assertion.

    uv run python -m calibration.graduate_finding --findings output/<ds>/findings.yaml --id <id>
    uv run python -m calibration.graduate_finding --findings <path> --id <id> --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

from calibration.findings import Finding, load_findings

_EVAL_ROOT = Path(__file__).resolve().parent.parent
BACKLOG = _EVAL_ROOT / "docs" / "generator_backlog.yaml"
UNIT_DIR = _EVAL_ROOT / "calibration" / "unit"


def slug(finding_id: str) -> str:
    """A python-safe identifier suffix from a finding id."""
    s = re.sub(r"[^0-9a-zA-Z]+", "_", finding_id.lower()).strip("_")
    return s or "finding"


def parse_target(target: str) -> tuple[str, str]:
    """``table.column`` -> (table, column); raise for a non-column target."""
    if "." not in target:
        raise ValueError(
            f"target {target!r} is not a table.column — only detector findings on a "
            "column graduate into an injection (a metric finding graduates elsewhere)"
        )
    table, _, col = target.partition(".")
    return table, col


def oracle_nodeid(s: str) -> str:
    return f"calibration/unit/test_{s}.py::test_{s}_separates"


def injector_stub(f: Finding, table: str, col: str, s: str) -> str:
    return f'''def inject_{s}(
    df: pl.DataFrame,
    col: str,
    ratio: float,
    registry: InjectionRegistry,
    table_name: str,
    rng: random.Random,
    severity: str = "medium",
) -> pl.DataFrame:
    """{f.title}

    Graduated from finding {f.id} ({f.source}). Statistic: {f.named_statistic}.
    Repro: {f.repro}
    TODO: mutate df[col] on the sampled rows to reproduce the finding's signal.
    """
    n = len(df)
    count = max(1, int(n * ratio))
    indices = rng.sample(range(n), min(count, n))
    # TODO: apply the corruption on `indices` that makes {f.detector_id} fire.
    registry.record(
        EntropyInjection(
            injection_id=registry.next_id("{s.upper()[:8]}"),
            target_file=f"{{table_name}}.csv",
            target_column=col,
            target_rows=sorted(indices),
            layer="value",            # TODO: structural | semantic | value | computational
            dimension="{f.detector_id}",
            sub_dimension="{s}",
            detector_id="{f.detector_id}",
            injection_type="{s}",
            parameters={{"ratio": ratio}},
            severity=severity,
        )
    )
    return df
'''


def strategy_entry(f: Finding, table: str, col: str, s: str) -> str:
    return f'''  - injector: inject_{s}
    table: {table}
    detector_id: {f.detector_id}
    params:
      col: {col}
      ratio: 0.20   # TODO: 2-3 severity levels for an ordering assertion, not one magic ratio
      severity: high
'''


def oracle_stub(f: Finding, s: str) -> str:
    return f'''"""Graduated regression oracle for {f.id} — {f.title}.

Statistic: {f.named_statistic}. Repro: {f.repro}
Graduated from finding {f.id} ({f.source}), (vertical={f.vertical}, dataset={f.dataset}).
Fill the fixture legs + the separation assertion, then remove the skip.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="graduated stub for {f.id} — fill the fixture legs + separation assertion")
def test_{s}_separates() -> None:
    """{f.named_statistic} separates the injected family from clean by a margin.

    Recall is ordering (charter): injected > clean + margin, never a point threshold.
    TODO: load the recorded fixture legs (calibration/unit/fixture.py) or synthesize,
    compute {f.named_statistic}, and assert clean < injected with a reported margin.
    """
    raise NotImplementedError("fill the graduated oracle for {f.id}")
'''


def backlog_snippet(f: Finding) -> str:
    """The finding's backlog item as an indented YAML list entry (comments preserved
    in the file; we append textually)."""
    item = f.to_backlog_item()
    dumped = yaml.safe_dump([item], default_flow_style=False, sort_keys=False, allow_unicode=True)
    return "".join(("  " + ln if ln.strip() else ln) for ln in dumped.splitlines(keepends=True))


def append_backlog(f: Finding, *, path: Path = BACKLOG) -> None:
    """Append the finding to the backlog, verifying the file still parses (or restore)."""
    original = path.read_text()
    path.write_text(original.rstrip("\n") + "\n\n" + backlog_snippet(f))
    try:
        data = yaml.safe_load(path.read_text())
        ids = [i.get("id") for i in data.get("items", [])]
        if f.id not in ids:
            raise ValueError("appended item did not parse back into items")
    except Exception:
        path.write_text(original)  # restore — never leave the backlog corrupt
        raise


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(_EVAL_ROOT))
    except ValueError:
        return str(p)


def graduate(
    f: Finding, *, dry_run: bool, unit_dir: Path = UNIT_DIR, backlog_path: Path = BACKLOG
) -> str:
    """Scaffold the finding. Returns the human-facing report; performs eval-owned writes.

    ``unit_dir`` / ``backlog_path`` are injectable so tests isolate to tmp dirs without
    monkeypatching module state.
    """
    f.require_repro()  # no rumors
    s = slug(f.id)
    table, col = parse_target(f.target)
    nodeid = oracle_nodeid(s)
    oracle_path = unit_dir / f"test_{s}.py"

    report = [
        f"# Graduating {f.id} — {f.title}",
        f"# (vertical={f.vertical}, dataset={f.dataset}, detector={f.detector_id}, "
        f"statistic={f.named_statistic})",
        "",
        "## 1. Injector stub — PASTE into "
        "vendor/dataraum-testdata/src/testdata/entropy/injectors.py:",
        injector_stub(f, table, col, s),
        "## 2. Strategy entry — add under `injections:` in a strategies/*.yaml:",
        strategy_entry(f, table, col, s),
        f"## 3. Tier-1/2 oracle stub -> {_rel(oracle_path)}"
        + ("  (DRY-RUN: not written)" if dry_run else ""),
        f"##    nodeid: {nodeid}",
        f"## 4. Backlog: {f.id} -> status graduated"
        + ("  (DRY-RUN: not appended)" if dry_run else ""),
    ]

    if not dry_run:
        if oracle_path.exists():
            raise FileExistsError(f"{oracle_path} already exists — refusing to clobber")
        oracle_path.write_text(oracle_stub(f, s))
        f.graduated_to = nodeid
        f.status = "graduated"
        append_backlog(f, path=backlog_path)

    return "\n".join(report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--findings", required=True, help="path to an investigation's findings.yaml")
    parser.add_argument("--id", required=True, help="the finding id to graduate")
    parser.add_argument("--dry-run", action="store_true", help="print the scaffold; write nothing")
    args = parser.parse_args()

    findings = {f.id: f for f in load_findings(args.findings)}
    if args.id not in findings:
        sys.exit(f"no finding {args.id!r} in {args.findings} — have: {sorted(findings)}")
    print(graduate(findings[args.id], dry_run=args.dry_run))


if __name__ == "__main__":
    main()
