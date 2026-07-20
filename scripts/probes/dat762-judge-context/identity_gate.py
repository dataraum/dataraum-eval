"""DAT-762 identity kill-gate — the class RWD could not test.

The dangerous FP the mechanical stack asserts deterministically (DAT-762 comment
16686): `races.raceId <-> date` and `salesdocument.SALESDOCUMENT <-> CREATIONTIMESTAMP`
are perfect bijections, so g3=0, lambda=1, and they survive the permutation null —
statistically IDENTICAL to a true alias. Only semantics can separate them, and the
RWD benchmark cannot test it (its labels are FD-truth; it never separates the
identity class from the drill class).

So this is the missing gate: does a judge separate a COINCIDENTAL bijection (an
entity key that lines up 1:1 with a per-row timestamp) from a TRUE alias (an id and
its slug/name for the same entity)? All pairs are real bijections in the shipped
RelBench exports (corpora/relbench/, DAT-757 fold harness).

Ground-first pass/fail: confidence(true alias) > confidence(coincidental) by a
margin, with the coincidental pair landing on the correct side of 0.5. No labels in
the prompt — the two categories are described abstractly, never with the id/timestamp
tell that would hand over the answer.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import polars as pl

MODEL = "claude-sonnet-5"
N_SAMPLE = 8


# (dataset, table, A, B, is_true_alias, note) — ground truth is the PAIR's nature,
# not anything in the prompt.
CASES = [
    ("rel-f1", "races", "raceId", "date", False, "entity key vs per-race timestamp"),
    ("rel-salt", "salesdocument", "SALESDOCUMENT", "CREATIONTIMESTAMP", False,
     "entity key vs per-doc timestamp"),
    ("rel-f1", "drivers", "driverId", "driverRef", True, "id vs slug, same driver"),
    ("rel-f1", "circuits", "circuitId", "circuitRef", True, "id vs slug, same circuit"),
    ("rel-f1", "constructors", "constructorId", "constructorRef", True,
     "id vs slug, same constructor"),
    ("rel-f1", "circuits", "circuitId", "name", True, "id vs proper name, same circuit"),
]

SYSTEM = """You are given two columns, A and B, from ONE table. In the data they are \
in one-to-one correspondence: each A value maps to exactly one B value and each B to \
exactly one A (a bijection over the rows present).

A bijection can mean two different things, and the distinction matters:
 - ALIAS: A and B are two encodings of the SAME underlying thing — for instance an \
identifier and a human-readable label for that one entity. Collapsing them into a \
single dimension loses nothing.
 - COINCIDENTAL: A and B describe DIFFERENT things that merely happen to line up \
one-to-one on these particular rows. They are two dimensions and must not be merged; \
the 1:1 is an artifact of the data, not a rule about what the columns are.

Decide which, from the column names and the sample values shown.

Return a confidence in [0.0, 1.0] that A and B are the SAME dimension (an ALIAS) — \
house convention: 0.85-1.0 decisive (an alias near 1.0, a clearly coincidental pair \
near 0.0); 0.5-0.8 probable but not certain; 0.2-0.4 you are guessing. A confident \
call on thin evidence is worse than an honest middling one.

Answer with ONLY: {"same_dimension": true|false, "confidence": <float>, "reason": "<one sentence>"}"""


@dataclass
class Pair:
    ds: str
    table: str
    a: str
    b: str
    is_alias: bool
    note: str
    n: int
    da: int
    db: int
    dab: int
    sa: list[str]
    sb: list[str]

    @property
    def bijection(self) -> bool:
        return self.da == self.db == self.dab and self.n > 0


def _samples(s: pl.Series) -> list[str]:
    vc = s.drop_nulls().value_counts(sort=True)
    return [str(v) for v in vc[vc.columns[0]][:N_SAMPLE].to_list()]


def load_pair(ds: str, table: str, a: str, b: str, is_alias: bool, note: str) -> Pair:
    df = pl.read_parquet(Path("corpora/relbench") / ds / "tables" / f"{table}.parquet",
                         columns=[a, b])
    pair = df.drop_nulls()
    return Pair(
        ds, table, a, b, is_alias, note,
        n=len(pair),
        da=int(pair[a].n_unique()),
        db=int(pair[b].n_unique()),
        dab=int(pair.n_unique()),
        sa=_samples(pair[a]),
        sb=_samples(pair[b]),
    )


def prompt(p: Pair) -> str:
    sa = ", ".join(f"`{v}`" for v in p.sa)
    sb = ", ".join(f"`{v}`" for v in p.sb)
    return (
        f"Table `{p.table}`, {p.n:,} rows.\n\n"
        f"A `{p.a}`: {p.da:,} distinct, e.g. {sa}\n"
        f"B `{p.b}`: {p.db:,} distinct, e.g. {sb}\n\n"
        f"`{p.a}` and `{p.b}` are a bijection over these rows."
    )


def load_key() -> str:
    env = Path(__file__).resolve().parents[3] / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("no ANTHROPIC_API_KEY")
    return key


def ask(client, p: Pair) -> dict:
    resp = client.messages.create(
        model=MODEL, max_tokens=400, system=SYSTEM,
        messages=[{"role": "user", "content": prompt(p)}])
    text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), None)
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].removeprefix("json").strip()
    return json.loads(raw)


def main() -> None:
    import anthropic
    client = anthropic.Anthropic(api_key=load_key())
    pairs = [load_pair(*c) for c in CASES]

    print(f"{'pair':<44} {'bijection':>9} {'truth':>10} {'same?':>6} {'conf':>5}  reason")
    print("-" * 120)
    rows = []
    for p in pairs:
        if not p.bijection:
            print(f"{p.table+'.'+p.a+'<->'+p.b:<44} {'NO':>9}  (da={p.da} db={p.db} dab={p.dab}) — not a bijection, skipped")
            continue
        v = ask(client, p)
        truth = "ALIAS" if p.is_alias else "COINCID"
        c = float(v["confidence"])
        rows.append((p, c))
        print(f"{p.table+'.'+p.a+'<->'+p.b:<44} {'yes':>9} {truth:>10} "
              f"{str(v['same_dimension']):>6} {c:>5.2f}  {v['reason']}")

    alias = [c for p, c in rows if p.is_alias]
    coincid = [c for p, c in rows if not p.is_alias]
    print("\n--- SEPARATION ---")
    if alias and coincid:
        print(f"true aliases     conf(same_dim): min {min(alias):.2f}  mean {sum(alias)/len(alias):.2f}")
        print(f"coincidental     conf(same_dim): max {max(coincid):.2f}  mean {sum(coincid)/len(coincid):.2f}")
        margin = min(alias) - max(coincid)
        print(f"margin (min alias - max coincidental): {margin:+.2f}")
        gate = margin > 0 and max(coincid) < 0.5
        print(f"GATE {'PASS' if gate else 'FAIL'}: "
              f"{'aliases separate from coincidentals AND coincidentals below 0.5' if gate else 'no clean separation'}")


if __name__ == "__main__":
    main()
