"""DAT-687 leg (b): does the engine already KNOW about the erroring validation?

An execution ERROR keeps the artifact at `grounded` with the reason on the row
(validation_phase docstring). If the erroring check sits at `grounded`, the
abstention contract worked and there is nothing to file. If it sits at `executed`,
that is the finding. Check before claiming.
"""

from __future__ import annotations

import sys

from sqlalchemy import text

from calibration.tools._runs import load_run, workspace_session


def main() -> None:
    strategy = sys.argv[1] if len(sys.argv) > 1 else "clean"
    load_run(strategy)
    with workspace_session() as session:
        from dataraum.storage.read_views import read_schema_name_for

        read_schema = read_schema_name_for(
            session.execute(text("SELECT current_schema()")).scalar()
        )
        rows = session.execute(text(f"""
            SELECT a.artifact_key, a.state, a.state_reason, v.name, v.source
            FROM "{read_schema}".current_lifecycle_artifacts a
            LEFT JOIN validations v ON v.validation_id = a.artifact_key
                                   AND v.superseded_at IS NULL
            WHERE a.artifact_type = 'validation'
            ORDER BY a.state, v.name
        """)).all()

    by_state: dict[str, int] = {}
    for r in rows:
        by_state[r.state] = by_state.get(r.state, 0) + 1
    print(f"validation artifacts: {len(rows)} — {by_state}\n")
    for r in rows:
        if r.state == "executed":
            continue
        print(f"  [{r.state}] {r.name or r.artifact_key} (source={r.source})")
        print(f"      {(r.state_reason or '')[:220]}")


if __name__ == "__main__":
    main()
