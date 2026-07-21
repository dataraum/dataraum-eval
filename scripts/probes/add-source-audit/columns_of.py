"""Print the column list of every ``current_*`` view — so census queries are
written against the real shape instead of a guessed one.

    uv run python scripts/probes/add-source-audit/columns_of.py rel-f1
"""

from __future__ import annotations

import argparse

from sqlalchemy import text

from calibration.tools._runs import load_run, workspace_session


def main(strategy: str) -> None:
    load_run(strategy)
    with workspace_session() as session:
        read = str(session.execute(text("SELECT current_schema()")).scalar()) + "_read"
        rows = session.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = :s ORDER BY table_name, ordinal_position"
            ),
            {"s": read},
        ).fetchall()
    shape: dict[str, list[str]] = {}
    for tbl, col in rows:
        shape.setdefault(tbl, []).append(col)
    for tbl, cols in shape.items():
        print(f"{tbl}: {', '.join(cols)}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("strategy")
    main(**vars(p.parse_args()))
