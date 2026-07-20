"""DAT-762 judge-context spike — the evidence channels (protocol: PROTOCOL.md).

The ONE variable across arms is what the judge is shown. Judge, verdict space and
output schema are held constant. Statistic definitions are imported from the frozen
DAT-757 instrument (`fdlib`, `probe_ablation`) — one definition home, so VR and VH
provably carry identical numbers and differ only in framing.

Arms:
    N   names-only                     — PR-500's veto surface, DAT-757 C2
    V   + value profiles               — NO pair statistics (never tested before)
    VR  + raw statistics               — DAT-757 C3 reproduction ("bad presentation")
    VH  + hypothesis-framed statistics — same numbers as VR, reframed (the core arm)

VH's thesis: C3 did not fail because the judge saw statistics. It failed because a
raw number carries no null hypothesis, so a near-FD reads as authority to assert.
VH renders each finding together with the origins that could produce it and the
computed fact that discriminates each origin. The judge still decides; nothing is
pattern-matched, nothing is pre-classified, no verdict is supplied.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[0] / "dat757-g3-wide"))
sys.path.insert(0, str(HERE.parents[0] / "dat757-relbench"))
sys.path.insert(0, str(HERE.parents[0] / "dat757-channel-ablation"))

from cells import Cell  # noqa: E402
from fdlib import FD_MAX_G3, NEAR_KEY_FRAC, Scan  # noqa: E402
from probe_ablation import (  # noqa: E402  — frozen statistic definitions, imported not copied
    LAMBDA_MIN,
    NULL,
    col_profile,
    constructed_profiles,
    evidence_c2,
    lam,
    minority,
    pair_stats,
    utf,
)

# --------------------------------------------------------------------------- #
# system prompt — constant across every arm                                    #
# --------------------------------------------------------------------------- #
SYSTEM = """You are a dimensional-modeling judge for a data-analytics engine. Given two
columns, classify their DIMENSIONAL relationship with exactly one verdict:

- MERGE: the two columns are the same thing — collapse into one identity
  (code<->name of one entity, duplicated copies, or the same concept split across
  views that should conform into one dimension).
- HIERARCHY: one column is a coarser level or attribute of the other — a valid,
  groupable dimension edge (give the direction: which determines which).
- ROLE: same concept family but deliberately distinct instances that must be kept
  apart (e.g. bill-to vs ship-to, start vs finish, item override of a header value).
- REJECT: no dimension relationship worth asserting (coincidental or trivial
  determination, quasi-identifier, proxy key like a timestamp, measure computed
  from another column, free text, unrelated concepts).

A practitioner will group, filter and drill on what you accept. Accepting a
relationship that is real-but-not-groupable is as costly as rejecting a real one.

Answer with ONLY a JSON object: {"verdict": "MERGE"|"HIERARCHY"|"ROLE"|"REJECT",
"direction": "a->b"|"b->a"|null, "confidence": "high"|"medium"|"low",
"reason": "<one sentence>"} — direction only for HIERARCHY, meaning the left/first
column determines the right/second one. Use confidence "low" when the evidence does
not support a call; a low-confidence verdict is recorded but not acted on."""


# --------------------------------------------------------------------------- #
# facts behind the framing — computed once, rendered two ways (VR raw / VH framed)
# --------------------------------------------------------------------------- #
def pair_facts(scan: Scan, obt: pl.DataFrame, a: str, b: str) -> dict:
    """Every number VR dumps and VH frames. Single source — the arms cannot diverge."""
    ps = pair_stats(scan, obt, a, b)
    key = (a, b) if (a, b) in scan.stats else (b, a)
    raw = scan.stats[key]
    d_a, d_b = (raw.d_a, raw.d_b) if key == (a, b) else (raw.d_b, raw.d_a)
    n = scan.n
    return {
        **ps,
        "n_rows": n,
        "distinct_a": d_a,
        "distinct_b": d_b,
        "near_key_ratio_a": round(d_a / n, 4) if n else 0.0,
        "near_key_ratio_b": round(d_b / n, 4) if n else 0.0,
        "majority_mass_b": round(1.0 - minority(obt, b), 4),
        "majority_mass_a": round(1.0 - minority(obt, a), 4),
    }


def _pct(x: float) -> str:
    return f"{100.0 * x:.2f}%"


def frame_determination(f: dict, a: str, b: str, s: str, t: str) -> str:
    """One directional finding, with its competing origins and discriminating facts."""
    g3 = f["row_g3_a_to_b"] if (s, t) == (a, b) else f["row_g3_b_to_a"]
    rev = f["row_g3_b_to_a"] if (s, t) == (a, b) else f["row_g3_a_to_b"]
    lam_st = f["lambda_a_to_b"] if (s, t) == (a, b) else f["lambda_b_to_a"]
    d_s = f["distinct_a"] if s == a else f["distinct_b"]
    nk_s = f["near_key_ratio_a"] if s == a else f["near_key_ratio_b"]
    maj_t = f["majority_mass_b"] if t == b else f["majority_mass_a"]
    n = f["n_rows"]

    return f"""FINDING — `{s}` determines `{t}`.
  {_pct(1 - g3)} of rows are consistent with "each value of `{s}` maps to exactly one
  value of `{t}`" (violation rate g3 = {g3:.5f}; the engine asserts an edge at
  g3 <= {FD_MAX_G3}). The reverse direction violates at {rev:.5f}.

  Several different things produce a pattern like this. The facts that tell them apart:

  * A REAL dimension hierarchy — `{t}` is a coarser level or a descriptive attribute
    of `{s}`, and a practitioner would group by it.

  * A NEAR-KEY ARTIFACT — if `{s}` is close to unique, almost ANY column is trivially
    "determined" by it and the finding says nothing. Here `{s}` has {d_s:,} distinct
    values over {n:,} rows = {nk_s:.2f} of rows. (At >= {NEAR_KEY_FRAC} the engine treats a
    determinant as a near-key and the finding as vacuous.)

  * A VACUOUS SKEW — if `{t}` is dominated by one value, "determining" it barely beats
    always guessing that value. Here `{t}`'s most common value covers {_pct(maj_t)} of
    rows; over that baseline this determination reduces error by Goodman-Kruskal
    lambda = {lam_st:.3f}. (lambda near 0 = no real reduction; the engine's floor is
    lambda >= {LAMBDA_MIN}.)

  * A PROXY DETERMINANT — `{s}` is fine-grained enough to determine `{t}` but is not
    something anyone groups by: an operational id, a timestamp, a free-text field.
    Decide this from `{s}`'s actual values and profile above — not from its name."""


def frame_bidirectional(f: dict, a: str, b: str) -> str:
    return f"""FINDING — `{a}` and `{b}` determine EACH OTHER.
  Both directions hold (violations {f["row_g3_a_to_b"]:.5f} and {f["row_g3_b_to_a"]:.5f};
  pair-count form {f["paircount_g3_a_to_b"]:.5f} / {f["paircount_g3_b_to_a"]:.5f}). The two
  columns cut the rows into the same groups.

  Origins that produce this, and what separates them here:
  * TWO ENCODINGS OF ONE IDENTITY (code <-> name of one entity) — one thing, two spellings.
  * TWO DIFFERENT CONCEPTS IN LOCKSTEP — e.g. an id minted in timestamp order, or a
    1:1 attribute that is nonetheless not the entity's identity. Bijection is not identity.
  * A COPIED VALUE — the same value materialized into two columns.

  Discriminating facts: the two columns hold literally equal values on
  {_pct(1 - f["value_equality_disagreement"])} of rows; their value sets overlap at
  Jaccard {f["value_set_jaccard"]:.4f}; `{a}` has {f["distinct_a"]:,} distinct values,
  `{b}` has {f["distinct_b"]:,}, over {f["n_rows"]:,} rows."""


def frame_near_copy(f: dict, a: str, b: str) -> str:
    return f"""FINDING — same-domain near-copy.
  `{a}` and `{b}` draw on the same value domain (value-set Jaccard
  {f["value_set_jaccard"]:.4f}) and disagree on only
  {_pct(f["value_equality_disagreement"])} of rows.

  Origins: a DIRTY DUPLICATE of one thing (disagreements are noise/error), or TWO
  DELIBERATELY DISTINCT ROLES of one concept, where the disagreements are
  business-systematic — the rows that differ, differ for a reason. Judge which from
  the values and the columns' place in the table."""


def frame_no_finding(f: dict, a: str, b: str) -> str:
    return f"""FINDING — no determination in either direction.
  `{a}` -> `{b}` violates at {f["row_g3_a_to_b"]:.5f}, `{b}` -> `{a}` at
  {f["row_g3_b_to_a"]:.5f} (the engine asserts only at g3 <= {FD_MAX_G3}). The columns
  hold {f["distinct_a"]:,} and {f["distinct_b"]:,} distinct values over {f["n_rows"]:,}
  rows; their value sets overlap at Jaccard {f["value_set_jaccard"]:.4f}.

  Overlapping value domains alone do not make two columns the same concept."""


def hypothesis_block(f: dict, a: str, b: str) -> str:
    """Assemble only the findings that actually apply to this pair."""
    parts: list[str] = []
    fwd = f["row_g3_a_to_b"] <= FD_MAX_G3
    bwd = f["row_g3_b_to_a"] <= FD_MAX_G3

    if fwd and bwd:
        parts.append(frame_bidirectional(f, a, b))
    elif fwd:
        parts.append(frame_determination(f, a, b, a, b))
    elif bwd:
        parts.append(frame_determination(f, a, b, b, a))
    else:
        parts.append(frame_no_finding(f, a, b))

    if 0.0 < f["value_equality_disagreement"] <= 0.05:
        parts.append(frame_near_copy(f, a, b))

    return "\n\n".join(parts)


# --------------------------------------------------------------------------- #
# the four arms                                                                #
# --------------------------------------------------------------------------- #
def evidence_N(cell: Cell, data: dict, rng: np.random.Generator) -> str:
    """Names-only — imported verbatim from the frozen instrument (DAT-757 C2)."""
    return evidence_c2(cell, data)


def _profiles(cell: Cell, data: dict, rng: np.random.Generator) -> dict:
    if cell.dataset.startswith("constructed"):
        return constructed_profiles(cell, data, rng)
    obt, _, _ = data[cell.dataset]
    return {
        f"profile[{cell.a}]": col_profile(obt, cell.a, rng),
        f"profile[{cell.b}]": col_profile(obt, cell.b, rng),
    }


def evidence_V(cell: Cell, data: dict, rng: np.random.Generator) -> str:
    """+ value evidence, NO pair statistics. The arm C3 never isolated."""
    return (
        evidence_c2(cell, data)
        + "\n\nColumn profiles:\n"
        + json.dumps(_profiles(cell, data, rng), ensure_ascii=False)
    )


def evidence_VR(cell: Cell, data: dict, rng: np.random.Generator) -> str:
    """+ raw statistics dumped as JSON — the DAT-757 C3 presentation, reproduced."""
    base = evidence_V(cell, data, rng)
    if cell.dataset.startswith("constructed"):
        return base  # no joint statistics exist across views — C3 did the same
    obt, _, scan = data[cell.dataset]
    ev = {
        "pair_statistics": pair_stats(scan, obt, cell.a, cell.b),
        "notes": (
            "row_g3(x->y)=min fraction of rows violating the FD x->y; "
            "lambda = 1 - g3/minority_mass (reduction over majority baseline); "
            "value_equality_disagreement = fraction of rows where the two values differ"
        ),
    }
    return base + "\n\nStatistical evidence:\n" + json.dumps(ev, ensure_ascii=False)


def evidence_VH(cell: Cell, data: dict, rng: np.random.Generator) -> str:
    """+ the SAME statistics as VR, framed as competing origins. The core arm."""
    base = evidence_V(cell, data, rng)
    if cell.dataset.startswith("constructed"):
        return base
    obt, _, scan = data[cell.dataset]
    f = pair_facts(scan, obt, cell.a, cell.b)
    return base + "\n\nWhat the engine's statistics found, and what could explain it:\n\n" + hypothesis_block(f, cell.a, cell.b)


ARMS: dict[str, object] = {
    "N": evidence_N,
    "V": evidence_V,
    "VR": evidence_VR,
    "VH": evidence_VH,
}
CORE_ARMS = ("N", "V", "VR", "VH")
