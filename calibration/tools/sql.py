"""Read-only SQL against the run's DuckLake data — the practitioner's query path.

    uv run python -m calibration.tools.sql <strategy> "SELECT ... FROM <typed table> ..."

Opens the worker substrate (DuckLake anchor + workspace overlay) exactly the
way the engine worker does, executes ONE read-only statement, and prints the
result. Table names are the typed DuckDB paths — list them first:

    uv run python -m calibration.tools.look <strategy>

The retired MCP ``query`` tool wrapped an LLM that wrote SQL; that judgment now
belongs to the investigating agent — this tool only executes.
"""

from __future__ import annotations

import argparse
from typing import Any

import yaml

from calibration.tools._runs import load_run

_READ_PREFIXES = ("select", "with", "describe", "show", "from")
_MAX_ROWS = 200


def _assert_read_only(statement: str) -> None:
    """Parse-level guard: exactly one statement, and it must be a pure read.

    Prefix sniffing alone is bypassable ("WITH x AS (...) DELETE ..." starts
    with a read prefix but mutates — review wave-1). DuckDB's own parser
    decides (DAT-654 retired sqlglot workspace-wide): the statement must
    extract to exactly one statement typed SELECT. DESCRIBE and SHOW parse to
    SELECT-typed statements; "WITH ... DELETE" carries StatementType.DELETE.
    """
    import duckdb

    try:
        statements = duckdb.extract_statements(statement)
    except duckdb.Error as err:
        raise SystemExit(f"read-only tool: could not parse statement: {err}") from err
    if len(statements) != 1:
        raise SystemExit("read-only tool: one statement only")
    if statements[0].type != duckdb.StatementType.SELECT:
        raise SystemExit("read-only tool: only SELECT / DESCRIBE / SHOW are allowed")


def run_sql(statement: str) -> dict[str, Any]:
    """Execute one read-only statement on the lake; return columns + rows."""
    lowered = statement.lstrip().lower()
    if not lowered.startswith(_READ_PREFIXES):
        raise SystemExit(f"read-only tool: statement must start with one of {_READ_PREFIXES}")
    _assert_read_only(statement)

    from calibration import runner as runner_mod

    runner_mod.bootstrap_engine()

    from dataraum.worker.bootstrap import bootstrap_worker_substrate, shutdown_worker_substrate

    manager = bootstrap_worker_substrate()
    try:
        with manager.duckdb_cursor() as cursor:
            result = cursor.execute(statement)
            columns = [d[0] for d in result.description or []]
            rows = result.fetchmany(_MAX_ROWS + 1)
    finally:
        shutdown_worker_substrate(manager)

    truncated = len(rows) > _MAX_ROWS
    return {
        "columns": columns,
        "rows": [list(map(_plain, row)) for row in rows[:_MAX_ROWS]],
        "row_count": min(len(rows), _MAX_ROWS),
        "truncated": truncated,
    }


def _plain(value: Any) -> Any:
    """YAML-safe scalar: stringify what safe_dump cannot represent."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("strategy")
    parser.add_argument("statement", help="one read-only SQL statement")
    args = parser.parse_args()

    load_run(args.strategy)  # tools read completed runs only
    print(yaml.safe_dump(run_sql(args.statement), sort_keys=False, allow_unicode=True))


if __name__ == "__main__":
    main()
