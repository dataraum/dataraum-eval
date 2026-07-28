"""DAT-687 pre-flight: what does a completed run actually leave to grade?

Read-only over the post-band-3 `clean` run still live in the eval stack. Answers
the three questions A3's design hangs on, before a line of oracle is written:
  1. which metric artifacts exist, and what state did they reach?
  2. is the composed formula SQL persisted per metric, and is it executable?
  3. which of them can be compared to ground_truth.yaml at all?
"""

from __future__ import annotations

import sys

from sqlalchemy import text

from calibration.tools._runs import load_run, workspace_session


def main() -> None:
    strategy = sys.argv[1] if len(sys.argv) > 1 else "clean"
    run = load_run(strategy)
    print(f"strategy={strategy} run_id={run.run_id}\n")

    with workspace_session() as session:
        from dataraum.storage.read_views import read_schema_name_for

        read_schema = read_schema_name_for(
            session.execute(text("SELECT current_schema()")).scalar()
        )
        print(f"read schema: {read_schema}\n")

        rows = session.execute(text(f"""
            SELECT artifact_key, state, state_reason, run_id
            FROM "{read_schema}".current_lifecycle_artifacts
            WHERE artifact_type = 'metric'
            ORDER BY state, artifact_key
        """)).all()
        print(f"metric artifacts: {len(rows)}")
        for r in rows:
            reason = f"  — {(r.state_reason or '')[:90]}" if r.state_reason else ""
            print(f"  {r.state:<12} {r.artifact_key}{reason}")

        print()
        snips = session.execute(text("""
            SELECT snippet_type, source, standard_field, aggregation,
                   length(sql) AS sql_len, failure_count
            FROM sql_snippets
            ORDER BY snippet_type, source
        """)).all()
        print(f"sql_snippets: {len(snips)}")
        by_type: dict[str, int] = {}
        for s in snips:
            by_type[s.snippet_type] = by_type.get(s.snippet_type, 0) + 1
        print(f"  by type: {by_type}")
        for s in snips:
            if s.snippet_type == "formula":
                print(f"  formula  {s.source:<28} len={s.sql_len} failures={s.failure_count}")


if __name__ == "__main__":
    main()
