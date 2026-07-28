"""DAT-687 pre-flight 3: the engine's own metric values vs generator truth."""

from __future__ import annotations

import sys

import yaml
from sqlalchemy import text

from calibration import runner as runner_mod
from calibration.tools._runs import load_run, workspace_session


def main() -> None:
    strategy = sys.argv[1] if len(sys.argv) > 1 else "clean"
    load_run(strategy)
    gt = yaml.safe_load(open(f"data/{strategy}/ground_truth.yaml"))

    print("ground truth (annual):")
    for k, v in gt["annual"].items():
        print(f"  {k:<28} {v}")
    print(f"\nfiscal_year_start={gt.get('fiscal_year_start')} months={gt.get('months')}")
    print(f"other top-level keys: {[k for k in gt if k not in ('annual', 'monthly', 'invariants')]}")

    with workspace_session() as session:
        snippets = session.execute(text("""
            SELECT source, sql FROM sql_snippets
            WHERE snippet_type = 'formula' AND source LIKE 'graph:%' ORDER BY source
        """)).all()

    runner_mod.bootstrap_engine()
    from dataraum.worker.bootstrap import bootstrap_worker_substrate, shutdown_worker_substrate

    computed: dict[str, float] = {}
    manager = bootstrap_worker_substrate()
    try:
        with manager.duckdb_cursor() as cursor:
            for s in snippets:
                cursor.execute(s.sql)
                row = cursor.fetchone()
                if row and row[0] is not None:
                    computed[s.source.removeprefix("graph:")] = float(row[0])
    finally:
        shutdown_worker_substrate(manager)

    print("\nengine metric values:")
    for k, v in sorted(computed.items()):
        print(f"  {k:<28} {v:,.4f}")

    print("\ndirect comparisons where truth exists:")
    annual = gt["annual"]
    pairs = [
        ("gross_profit", "gross_profit", 1.0),
        ("dso", "annual_dso", None),
    ]
    for metric, truth_key, tol_pct in pairs:
        if metric not in computed or truth_key not in annual:
            print(f"  {metric}: no pair (truth key {truth_key!r} present={truth_key in annual})")
            continue
        got, want = computed[metric], float(annual[truth_key])
        rel = abs(got - want) / abs(want) * 100 if want else float("nan")
        bar = f"{tol_pct}%" if tol_pct else "—"
        print(f"  {metric:<20} engine={got:,.4f}  truth={want:,.4f}  "
              f"rel_err={rel:.3f}%  tol={bar}")


if __name__ == "__main__":
    main()
