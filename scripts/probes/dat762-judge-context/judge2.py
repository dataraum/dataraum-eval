"""DAT-762 attempt 2 — the judge, fed properly. See GATE.md (frozen first).

Self-contained: does NOT import attempt 1's channels.py (that one is built around
RelBench OBTs and carries the three construction defects the post-mortem found).

The three fixes, by name:
  1. The origin menu spans the truth space, and "cannot tell" is one of the
     origins — not a footnote in the system prompt that no frame references.
  2. No taste in the system prompt. Attempt 1's REJECT exemplar was "proxy key
     like a timestamp"; it then graded the judge wrong for rejecting timestamps.
     Nothing here names a column kind as good or bad.
  3. Every pair renders the frame. No silent bare-evidence fallthrough.

V and VH read their numbers from the SAME facts() call, so any VH - V difference
is presentation, never data.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import polars as pl

import rwd

MODEL = "claude-sonnet-5"
MAX_TOKENS = 400
N_SAMPLE = 8

# The biocase tables encode missing values as the literal 4-character string
# "NULL" -- 2.4M cells in t_biocase_gathering alone. polars reads it as data.
# Parciak et al. computed g3 treating it as missing, so without this the premise
# is FALSE for 24/390 pairs as we render them (AreaCode -> AreaName shows 643
# distinct A and 1,722 distinct B; a function cannot have more outputs than
# inputs), and the sentinel is frequently the "most common value" we show the
# judge. Not a heuristic: it aligns our read with the benchmark's own.
NULL_TOKENS = frozenset({"NULL"})

# ---------------------------------------------------------------- system

SYSTEM = """You judge whether a functional dependency between two columns is \
semantically meaningful.

You are given a pair of columns (A, B) from one table where A -> B holds \
EXACTLY in the rows described: every row with the same A value has the same B \
value, with no exceptions.

Holding exactly is not the question — it is the premise. Every pair you will \
see holds exactly. The question is whether the dependency MEANS anything: \
whether "B is determined by A" is a real rule about what these columns are, or \
whether it is something that happens to be true of the rows in front of you.

Answer with ONLY a JSON object:
{"meaningful": true|false, "confidence": "high"|"medium"|"low", \
"reason": "<one sentence>"}

Use confidence "low" when the evidence in front of you does not distinguish the \
possibilities. A low-confidence answer is a useful answer: it is recorded and \
surfaced to the reader rather than acted on. Guessing at high confidence is \
worse than saying you cannot tell."""

# ---------------------------------------------------------------- facts


@dataclass(frozen=True)
class ColProfile:
    name: str
    dtype: str
    distinct: int
    non_null: int
    majority_share: float
    samples: list[str]


@dataclass(frozen=True)
class Facts:
    table_cols: list[str]
    n_table_rows: int  # the whole table
    n_rows: int  # rows where BOTH columns are present
    a: ColProfile
    b: ColProfile
    rows_per_a: float
    a_key_frac: float


def _profile(df: pl.DataFrame, col: str) -> ColProfile:
    s = df[col]
    nn = s.drop_nulls()
    distinct = int(nn.n_unique()) if len(nn) else 0
    if len(nn):
        vc = nn.value_counts(sort=True)
        majority = int(vc[vc.columns[1]][0]) / len(nn)
        samples = [str(v) for v in vc[vc.columns[0]][:N_SAMPLE].to_list()]
    else:
        majority, samples = 0.0, []
    return ColProfile(col, str(s.dtype), distinct, len(nn), majority, samples)


def _blank_sentinels(df: pl.DataFrame, cols: list[str]) -> pl.DataFrame:
    """Turn sentinel strings into real nulls. See NULL_TOKENS."""
    return df.with_columns(
        [
            pl.when(pl.col(c).is_in(list(NULL_TOKENS)))
            .then(None)
            .otherwise(pl.col(c))
            .alias(c)
            for c in cols
        ]
    )


def facts(table: str, a: str, b: str) -> Facts:
    """Every number both arms use. One definition home."""
    df = rwd.load_table(table)
    pair = _blank_sentinels(df.select([a, b]), [a, b]).drop_nulls()
    pa, pb = _profile(pair, a), _profile(pair, b)
    n = len(pair)
    return Facts(
        table_cols=list(df.columns),
        n_table_rows=df.height,
        n_rows=n,
        a=pa,
        b=pb,
        rows_per_a=n / pa.distinct if pa.distinct else 0.0,
        a_key_frac=pa.distinct / n if n else 0.0,
    )


def holds_exactly(table: str, a: str, b: str) -> bool:
    """Does a -> b actually hold on the rows we profile? The probe's premise.

    Every prompt asserts 'A -> B holds exactly'. If that is false for the rows
    facts() renders, we are asking the judge to explain something that isn't
    there, and its answer means nothing.
    """
    df = rwd.load_table(table)
    pair = _blank_sentinels(df.select([a, b]), [a, b]).drop_nulls()
    if not len(pair):
        return False
    return pair.n_unique(subset=[a]) == pair.n_unique(subset=[a, b])


def _render_col(p: ColProfile, role: str) -> str:
    vals = ", ".join(f"`{v}`" for v in p.samples)
    return (
        f"{role} `{p.name}` — type {p.dtype}, {p.distinct:,} distinct values, "
        f"most common value covers {p.majority_share:.1%} of rows\n"
        f"    most frequent: {vals}"
    )


def evidence_block(f: Facts) -> str:
    cols = ", ".join(f"`{c}`" for c in f.table_cols)
    return (
        f"Table columns: {cols}\n"
        f"Rows in the table: {f.n_table_rows:,}\n"
        f"Rows where BOTH columns are present: {f.n_rows:,} "
        f"(the other {f.n_table_rows - f.n_rows:,} have at least one missing; "
        f"everything below is computed on the {f.n_rows:,})\n\n"
        f"  {_render_col(f.a, 'A')}\n"
        f"  {_render_col(f.b, 'B')}\n\n"
        f"A has {f.a.distinct:,} distinct values over those {f.n_rows:,} rows "
        f"({f.a_key_frac:.1%} — {f.rows_per_a:.1f} rows per A value on average)."
    )


# ---------------------------------------------------------------- arms


def evidence_V(f: Facts) -> str:
    """Names, table context, profiles, values. No framing.

    Deliberately does NOT pose its own question. SYSTEM asks it once, for both
    arms. An earlier version closed with "Is it part of the design schema?" while
    SYSTEM asked whether the dependency is "semantically meaningful" — two
    different tests (`Zip -> State` is a real rule about the world that no schema
    declares), and VH inherits SYSTEM's question via frame_clean. So the arms
    would have differed by framing AND by question, and VH - V would measure
    neither. Caught before any call was spent.
    """
    return f"{evidence_block(f)}\n\n`{f.a.name}` -> `{f.b.name}` holds exactly."


# judge2's own frame() is DELETED, not left dead. It encoded a direction belief
# ("the closer to one row per value, the less this dependency means") that the
# data falsifies, and GATE.md Amendment 1 records that I cannot correct it
# without writing the answer key into the prompt. frame_clean.frame() supersedes
# it: written by a subagent banned from the labels. See frame_clean.py's docstring.


def evidence_VH(f: Facts) -> str:
    """Same numbers as V, framed as competing origins + a real abstain.

    Imported function-locally: frame_clean does `from judge2 import Facts`, so a
    module-level import here would be circular.
    """
    from frame_clean import frame as clean_frame

    return f"{evidence_block(f)}\n\n{clean_frame(f)}"


ARMS = {"V": evidence_V, "VH": evidence_VH}

# ---------------------------------------------------------------- ask


def load_key() -> str:
    env = Path(__file__).resolve().parents[3] / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("no ANTHROPIC_API_KEY in .env or environment")
    return key


def ask_with(client, system: str, prompt: str, bool_key: str) -> dict:
    """One grading against an explicit system prompt. Returns the parsed verdict.

    Attempt 1's ask() assumed content[0] was text; sonnet-5 emits spontaneous
    thinking blocks, so it raised, and the caller cached an ERROR that scored as
    a silent miss. Take the first TEXT block; never cache a failure as a verdict.

    `system` is explicit because a hardcoded module SYSTEM silently sent the PAIR
    judge's instructions to a COLUMN prompt once — the model answered a blend of
    two questions. The system prompt must match the user turn.
    """
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    text = next(
        (blk.text for blk in resp.content if getattr(blk, "type", None) == "text"),
        None,
    )
    if text is None:
        raise RuntimeError(f"no text block in response: {[b.type for b in resp.content]}")
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].removeprefix("json").strip()
    out = json.loads(raw)
    if not isinstance(out.get(bool_key), bool):
        raise RuntimeError(f"bad verdict shape (want {bool_key}): {out}")
    if out.get("confidence") not in {"high", "medium", "low"}:
        raise RuntimeError(f"bad confidence: {out}")
    return out


def ask(client, prompt: str) -> dict:
    """The pair judge: judge2.SYSTEM, validates `meaningful`. Kept for the RWD run."""
    return ask_with(client, SYSTEM, prompt, "meaningful")
