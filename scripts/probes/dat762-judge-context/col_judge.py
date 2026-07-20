"""Ask about COLUMNS, not pairs. 77 calls instead of 2,340.

The oracle ceiling says a perfect per-column answer kills 74% of the junk at
ZERO recall cost. This asks whether the question is answerable WITHOUT the user
-- i.e. can an LLM stand in for the "do you group by this?" answer.

The prompt contains no label knowledge and never mentions a pair. It is asked
once per (table, column) that appears as an LHS.
"""
from __future__ import annotations
import json, sys, time
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import anthropic  # noqa: E402
import judge2, rwd  # noqa: E402

CACHE = Path(__file__).parent / "results_cols2.json"  # v1 sent the pair SYSTEM by accident; discarded

SYSTEM = """You are looking at one column of one table in a customer's database.

Answer this: is this column something a business user would GROUP BY, FILTER ON,
or DRILL INTO when analysing this data? That is -- is it a dimension of their
business, or a way of slicing it?

It is NOT, if it is: a technical identifier that exists to identify a row, a
surrogate key, an internal reference, a free-form note, or a value that is
unique-per-record and carries no category anyone reports on.

Judge from what the column actually contains and what the table is about.

Answer with ONLY a JSON object:
{"groupable": true|false, "confidence": "high"|"medium"|"low", "reason": "<one sentence>"}

Use confidence "low" when you genuinely cannot tell."""


def prompt(table: str, col: str) -> str:
    """One column, profiled directly. facts() takes a PAIR and selecting the same
    column twice makes polars reject the duplicate output name."""
    df = rwd.load_table(table)
    one = judge2._blank_sentinels(df.select([col]), [col])
    p = judge2._profile(one, col)
    return (
        f"Table columns: {', '.join('`' + c + '`' for c in df.columns)}\n"
        f"Rows in the table: {df.height:,}\n\n"
        f"Column `{col}` — type {p.dtype}, {p.distinct:,} distinct values "
        f"over {p.non_null:,} non-null rows "
        f"({p.distinct / max(p.non_null,1):.1%} unique), "
        f"most common value covers {p.majority_share:.1%}\n"
        f"    most frequent: {', '.join('`' + v + '`' for v in p.samples)}\n\n"
        f"Would a business user group by, filter on, or drill into `{col}`?"
    )


def main() -> None:
    cands = rwd.exact_candidates()
    cols = sorted({(c["table"], c["lhs"]) for c in cands})
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    client = anthropic.Anthropic(api_key=judge2.load_key())

    print(f"{len(cols)} distinct LHS columns to ask about "
          f"(vs {len(cands)} pairs)\n")
    t0 = time.time()
    for i, (t, col) in enumerate(cols, 1):
        for rep in range(3):
            key = f"{t}:{col}:{rep}"
            if key in cache:
                continue
            try:
                cache[key] = judge2.ask_with(client, SYSTEM, prompt(t, col), "groupable")
            except Exception as exc:  # noqa: BLE001
                print(f"  ERR {key}: {exc}")
                continue
            CACHE.write_text(json.dumps(cache, indent=1))
        if i % 10 == 0:
            print(f"  {i}/{len(cols)} columns  ({time.time()-t0:.0f}s)")
    print(f"\n{len(cache)} cached answers in {time.time()-t0:.0f}s")

    # majority vote per column
    verdict = {}
    for t, col in cols:
        votes = [cache[f"{t}:{col}:{r}"] for r in range(3) if f"{t}:{col}:{r}" in cache]
        if not votes:
            continue
        yes = sum(v["groupable"] for v in votes)
        verdict[(t, col)] = yes >= 2

    # apply Model 1 and grade
    n_real = sum(c["meaningful"] for c in cands)
    n_junk = len(cands) - n_real
    surv = [c for c in cands if verdict.get((c["table"], c["lhs"]), True)]
    sr = sum(c["meaningful"] for c in surv)
    print(f"\n--- MODEL 1 applied with the LLM as the user ---")
    print(f"columns answered NO: {sum(1 for v in verdict.values() if not v)}/{len(verdict)}")
    print(f"survivors: {len(surv)}/{len(cands)} pairs")
    print(f"  real kept: {sr}/{n_real}   -> recall {sr/n_real:.3f}")
    print(f"  junk killed: {n_junk - (len(surv)-sr)}/{n_junk} "
          f"({(n_junk-(len(surv)-sr))/n_junk:.1%})")
    print(f"  precision: {sr/len(surv):.3f}  (baseline 0.323, oracle ceiling 0.649)")

    # what did it get wrong, per column?
    truth = defaultdict(list)
    for c in cands:
        truth[(c["table"], c["lhs"])].append(c["meaningful"])
    fp_cols = [k for k, v in verdict.items() if v and not any(truth[k])]
    fn_cols = [k for k, v in verdict.items() if not v and any(truth[k])]
    print(f"\ncolumns it wrongly kept (all-junk, said groupable): {len(fp_cols)}")
    for t, c in fp_cols[:8]:
        print(f"    {t.split('.')[0][:20]:20s} {c[:28]:28s} ({len(truth[(t,c)])} junk pairs)")
    print(f"columns it wrongly killed (had real pairs, said not groupable): {len(fn_cols)}")
    for t, c in fn_cols[:8]:
        print(f"    {t.split('.')[0][:20]:20s} {c[:28]:28s} "
              f"({sum(truth[(t,c)])} REAL pairs lost)")


if __name__ == "__main__":
    main()
