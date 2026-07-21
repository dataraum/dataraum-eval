"""What the typing phase actually decided, per column, for one strategy.

``type_candidates`` is empty on rel-f1 and full on the finance corpus. That is
either "parquet arrives typed, nothing to infer" (fine) or "every column fell
through to the VARCHAR fallback" (a data-destroying bug). The decision rows say
which — ``decision_source`` and ``decided_type`` are the whole answer.

    uv run python scripts/probes/add-source-audit/typing_detail.py rel-f1
"""

from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import text

from calibration.tools._runs import load_run, workspace_session

QUERY = """
SELECT t.table_name, c.column_name, c.raw_type, c.resolved_type,
       d.decided_type, d.decision_source, d.decision_reason
FROM current_type_decisions d
JOIN current_columns c ON c.column_id = d.column_id
JOIN current_tables t ON t.table_id = c.table_id
ORDER BY t.table_name, c.column_position
"""


def main(strategy: str) -> None:
    load_run(strategy)
    with workspace_session() as session:
        read = session.execute(text("SELECT current_schema()")).scalar() + "_read"
        session.execute(text(f'SET search_path TO "{read}"'))
        rows = session.execute(text(QUERY)).fetchall()

    sources: Counter[str] = Counter()
    decided: Counter[str] = Counter()
    raws: Counter[str] = Counter()
    resolved: Counter[str] = Counter()
    print(f"{'table.column':<40} {'raw':<14} {'resolved':<14} {'decided':<12} source")
    for tbl, col, raw, res, dtype, src, _reason in rows:
        print(f"  {tbl + '.' + col:<38} {raw!s:<14} {res!s:<14} {dtype!s:<12} {src}")
        sources[src] += 1
        decided[str(dtype)] += 1
        raws[str(raw)] += 1
        resolved[str(res)] += 1

    print(f"\n[{len(rows)} decisions]")
    print(f"  decision_source: {dict(sources)}")
    print(f"  decided_type:    {dict(decided)}")
    print(f"  raw_type:        {dict(raws)}")
    print(f"  resolved_type:   {dict(resolved)}")
    if rows:
        print(f"\n  sample reason: {rows[0][6]!r}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("strategy")
    main(**vars(p.parse_args()))
