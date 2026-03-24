# Bug: slicing_view column persistence is intermittent

## Symptom

The `slicing_view` pipeline phase creates a `Table(layer="slicing_view")` record
AND registers its columns via `DESCRIBE` → `Column` inserts. Intermittently, the
Table persists but the Columns do not. This happens specifically for
`slicing_journal_lines` — other slicing views (bank_transactions, invoices, etc.)
get their columns consistently.

When this happens, downstream `build_slice_profiles()` produces zero
ColumnSliceProfile records for that table (it resolves columns via the
slicing_view Table, finds none, skips). This breaks `dimensional_entropy`
detection for the affected table.

## Reproduction

Not reliably reproducible. Observed on ~50% of fresh runs with `rm -rf output/`
followed by full pipeline. Same codebase, same data, same seed — sometimes
journal_lines gets 0 columns, sometimes 11.

## What we know

1. **DuckDB view is always correct** — `DESCRIBE slicing_journal_lines` returns
   12 columns in every run. The view creation and grain verification always pass.

2. **The Table record always persists** — `Table(layer="slicing_view",
   table_name="slicing_journal_lines")` is in metadata.db with correct row_count.

3. **The Column records sometimes don't persist** — 0 rows in `columns` for that
   table_id, while other slicing_view Tables have their columns.

4. **Single pipeline run, single phase execution** — confirmed via `phase_logs`
   that `slicing_view` runs exactly once, creates all 5-6 views in one pass.

5. **No errors logged** — the phase succeeds, reports correct `slicing_views`
   count. No exceptions, no warnings (a diagnostic log was added to detect
   empty DESCRIBE results — it never fires).

6. **Session adds look correct** — the code does `ctx.session.add(sv_table)`
   then `ctx.session.add(Column(...))` in a loop. Both use the same session.
   No try/except, no conditional logic. If the Table persists, the Columns
   should too — they're in the same uncommitted session.

## Architecture context

- Pipeline phases use a long-lived `ctx.session` from `PipelineSetup`
- Phases do NOT commit within `_run()` — the scheduler commits after the phase
- `slicing_view` and `validation` phases run **in parallel** (both depend on
  `semantic` completing). They start within ~1ms of each other.
- SQLite with WAL mode + busy_timeout. Session uses `autoflush=False`.
- Python 3.14t with free-threading (GIL disabled)

## Hypothesis: free-threading + SQLite session contention

With GIL disabled, truly parallel phases write to the same SQLite database
through separate sessions. The `slicing_view` phase adds ~50 objects
(5 Tables + ~45 Columns) to its session. When the scheduler commits this
session, it competes with `validation`'s session for SQLite write locks.

Possible failure mode:
- Session flush batches the INSERT statements
- SQLite busy_timeout expires during the Column INSERTs (not the Table INSERT)
- SQLAlchemy silently drops the timed-out Columns but keeps the already-committed Table
- The phase reports success because no Python exception was raised

This would explain:
- Why it's intermittent (depends on timing between parallel phases)
- Why the Table persists but Columns don't (Table is flushed first, smaller batch)
- Why only journal_lines is affected (it has the most enriched dimension columns = most Column INSERTs, processed last in the loop when contention is highest)

## Investigation suggestions

1. **Check if this is a free-threading issue** — run with `PYTHON_GIL=1` and see
   if the problem disappears. If so, the SQLite session handling needs mutex
   protection for commits.

2. **Add post-commit verification** — after the scheduler commits the phase
   session, query the Column count for each slicing_view Table. Log a warning
   if any have 0 columns. This would confirm whether the issue is at commit
   time vs session-add time.

3. **Check SQLAlchemy session.new before commit** — log `len(session.new)` right
   before the commit. If the Columns are in `session.new`, the issue is in the
   commit. If they're not, something removes them from the session between add
   and commit.

4. **Serialize slicing_view and validation** — if making them sequential instead
   of parallel fixes the issue, the root cause is confirmed as write contention.

## Files

- Phase: `src/dataraum/pipeline/phases/slicing_view_phase.py` (lines 259-280)
- Scheduler commit: `src/dataraum/pipeline/scheduler.py` (line 343)
- Profile builder: `src/dataraum/analysis/slicing/profiling.py` (lines 98-106)
- Diagnostic log: `slicing_view_phase.py` line 270 (`slicing_view_describe_empty`)
