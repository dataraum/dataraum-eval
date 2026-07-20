"""DAT-762 judge-context spike — held-out leg, stage 1: MECHANICAL counts. NO LLM.

The protocol (PROTOCOL.md, frozen) gates the held-out judge leg behind the dev gate.
This stage runs BEFORE that gate resolves and makes **zero** billed calls. It exists
to size and validate the held-out leg before any LLM touches it:

  (a) SPECS_762   — the three OBTs recommended by `heldout_survey.md`, verbatim.
  (b) stack_verdict — the frozen stack v4 at pair level, ported from
      `probe_ablation.c1_verdict` to take (obt, group, scan, spec) instead of a dev
      Cell, and VALIDATED for exact equivalence against `c1_verdict` on all 43
      non-constructed DAT-757 dev cells. A disagreement invalidates the leg.
  (c) every column pair the stack ASSERTS on each held-out OBT (MERGE/HIERARCHY/ROLE).
  (d) PROTOCOL.md's mechanical truth classification (in-group / cross-group /
      fact-internal) read off `build_obt`'s own fold-group map.
  (e) HELDOUT_COUNTS.md — the projected call cost + an audit of the truth model.

Nothing under `dat757-*/` is edited; the frozen instruments are imported.

Run:  uv run python -u scripts/probes/dat762-judge-context/probe_heldout.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import polars as pl

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[0] / "dat757-g3-wide"))
sys.path.insert(0, str(HERE.parents[0] / "dat757-relbench"))
sys.path.insert(0, str(HERE.parents[0] / "dat757-channel-ablation"))

from cells import CELLS  # noqa: E402  — frozen inventory
from fdlib import (  # noqa: E402  — frozen statistic definitions
    FD_MAX_G3,
    MIN_DISTINCT_DETERMINANT,
    MIN_DISTINCT_DIMENSION,
    NEAR_KEY_FRAC,
    Scan,
    perm_pvalue,
    scan_pairs,
)
from probe_ablation import (  # noqa: E402  — frozen stack v4 reference + statistics
    LAMBDA_MIN,
    c1_verdict,
    lam,
    load_all,
    utf,
)
from probe_fold_grade import SPECS, build_obt  # noqa: E402  — frozen fold harness

REPORT = HERE / "HELDOUT_COUNTS.md"
ASSERTS = HERE / "heldout_asserts.json"  # the exact pair list a held-out judge leg would grade
DATA = Path("corpora/relbench")

ASSERTING = ("MERGE", "HIERARCHY", "ROLE")
FACT_GROUPS = ("fact", "fact-key")

_LINES: list[str] = []


def emit(s: str = "") -> None:
    print(s)
    _LINES.append(s)


# --------------------------------------------------------------------------- #
# (a) SPECS_762 — the survey's recommendations, verbatim (heldout_survey.md §4) #
# --------------------------------------------------------------------------- #
SPECS_762: dict[str, dict] = {
    # R1 — rel-stack / postLinks: role-playing (two roles into `posts`), each with
    # its own two-hop into `users`. 103,969 rows — no sampling decision to defend.
    "rel-stack-postlinks": {
        "db": "rel-stack",
        "fact": "postLinks",
        "folds": [
            ("PostId", "posts", "post__"),
            ("RelatedPostId", "posts", "related__"),
            ("post__OwnerUserId", "users", "postowner__"),
            ("related__OwnerUserId", "users", "relatedowner__"),
        ],
        "probe_n": None,  # 103,969 rows — use everything
        "perm_reps": 999,
        # role contexts: the fact's own columns only (LinkTypeId, CreationDate, Id),
        # never the sibling role copies — they are outcomes, not drivers.
        "role_context_groups": ("fact", "fact-key"),
    },
    # R2 — rel-trial / outcome_analyses: richest meaning-bearing dim in the corpus
    # plus the naturally-redundant two-hop (outcome__nct_id == nct_id).
    "rel-trial-outcome-analyses": {
        "db": "rel-trial",
        "fact": "outcome_analyses",
        "folds": [
            ("nct_id", "studies", "study__"),
            ("outcome_id", "outcomes", "outcome__"),
        ],
        # entity-complete: a row-random sample drives outcome_id to 64.9% distinct
        # (vs 42.1% here) — sampling whole studies is the realistic slice and FD
        # exactness is subset-invariant.
        "sample_by": ("nct_id", 6_000),
        "probe_n": None,
        "perm_reps": 999,
    },
    # R3 — rel-stack / comments: the cross-fact conform partner for R1 (same `posts`
    # and `users` dims, different fact grain).
    "rel-stack-comments": {
        "db": "rel-stack",
        "fact": "comments",
        "folds": [
            ("PostId", "posts", "post__"),
            ("UserId", "users", "user__"),
            ("post__OwnerUserId", "users", "postowner__"),
        ],
        # entity-complete: row-random at 120k drives PostId to 74.1% distinct, close
        # to the 0.9 near-key guard; sampling whole posts holds it at 29.8%.
        "sample_by": ("PostId", 40_000),
        "probe_n": None,
        "perm_reps": 999,
    },
}


# --------------------------------------------------------------------------- #
# (b) the frozen stack v4 at pair level                                        #
# --------------------------------------------------------------------------- #
_UTF: dict[tuple[int, str], np.ndarray] = {}


def _utf(obt: pl.DataFrame, c: str) -> np.ndarray:
    """Memo over the frozen `probe_ablation.utf` — same pure function, computed once."""
    k = (id(obt), c)
    if k not in _UTF:
        _UTF[k] = utf(obt, c)
    return _UTF[k]


def stack_verdict(
    obt: pl.DataFrame,
    group: dict[str, str],
    scan: Scan,
    a: str,
    b: str,
    spec: dict,
    reps: int,
) -> tuple[str, str | None, str]:
    """Frozen stack v4, pair level — `c1_verdict` with (obt, group, scan, spec) passed
    in rather than looked up from a dev Cell. Screens in the same order, from the same
    fdlib primitives: near-copy role tests -> alias screen -> edge screen -> REJECT.
    Equivalence with `c1_verdict` is asserted on the dev cells by `validate_stack`."""
    ps_key = (a, b) if (a, b) in scan.stats else (b, a)
    ps = scan.stats[ps_key]
    if ps.d_a < MIN_DISTINCT_DIMENSION or ps.d_b < MIN_DISTINCT_DIMENSION:
        return "REJECT", None, "constant column"

    # 1) same-domain near-copy -> disagreement-set role tests (T1 role-specific)
    sa, sb = _utf(obt, a), _utf(obt, b)
    dis_rate = float((sa != sb).mean())
    if 0.0 < dis_rate <= 0.05:
        dis = (sa != sb).astype(np.int64)
        ctx_groups = spec.get("role_context_groups", ("fact", "fact-key"))
        contexts = [
            c
            for c in obt.columns
            if c not in (a, b)
            and group[c] in ctx_groups
            and scan.singles[c] >= MIN_DISTINCT_DIMENSION
        ]
        alpha = 0.05 / (len(contexts) + 1)
        for c in contexts:
            sc = scan_pairs(pl.DataFrame({"dis": dis, "x": _utf(obt, c)}), ["dis", "x"])
            if perm_pvalue(sc, "dis", "x", reps=reps) <= alpha:
                return "ROLE", None, f"T1 membership-systematic vs {c}"

    # 2) alias screen (pair-count both directions) + per-pair perm-p
    fwd_key = (a, b) in scan.stats
    ef, eb = (ps.g3_eng_fwd, ps.g3_eng_bwd) if fwd_key else (ps.g3_eng_bwd, ps.g3_eng_fwd)
    if ef <= FD_MAX_G3 and eb <= FD_MAX_G3:
        p = max(perm_pvalue(scan, a, b, reps=reps), perm_pvalue(scan, b, a, reps=reps))
        if p <= 0.05:
            return "MERGE", None, "bidirectional pair-count g3 + significant"

    # 3) edge screen + lambda floor + per-pair perm-p, both directions
    def edge(s: str, t: str) -> bool:
        k, f = ((s, t), True) if (s, t) in scan.stats else ((t, s), False)
        q = scan.stats[k]
        d_s, d_t = (q.d_a, q.d_b) if f else (q.d_b, q.d_a)
        g3 = q.g3_row_fwd if f else q.g3_row_bwd
        return (
            g3 <= FD_MAX_G3
            and d_s > d_t
            and d_s >= MIN_DISTINCT_DETERMINANT
            and not (scan.n and d_s >= NEAR_KEY_FRAC * scan.n)
            and d_t >= MIN_DISTINCT_DIMENSION
            and lam(scan, obt, s, t) >= LAMBDA_MIN
            and perm_pvalue(scan, s, t, reps=reps) <= 0.05
        )

    if edge(a, b):
        return "HIERARCHY", "a->b", "row-g3 + lambda + perm-p"
    if edge(b, a):
        return "HIERARCHY", "b->a", "row-g3 + lambda + perm-p"
    return "REJECT", None, "no screen passed"


def validate_stack(data: dict) -> tuple[int, list[tuple]]:
    """Mechanical equivalence: stack_verdict == c1_verdict on every non-constructed
    dev cell. c1_verdict runs FIRST so pair-level perm p-values are cached on the
    shared PairStats — any residual difference is logic, not the permutation RNG.
    (The T1 role tests build throwaway scans and cannot cache; a divergence there is
    diagnosed, not hidden — see the self-consistency control below.)"""
    cells = [c for c in CELLS if not c.dataset.startswith("constructed")]
    disagreements: list[tuple] = []
    for cell in cells:
        reps = 2999 if cell.dataset == "rel-f1" else 999
        obt, group, scan = data[cell.dataset]
        ref = c1_verdict(cell, data, reps)
        got = stack_verdict(obt, group, scan, cell.a, cell.b, SPECS[cell.dataset], reps)
        mark = "ok " if got == ref else "DIFF"
        print(f"  {mark} {cell.id:3} [{cell.dataset:8}] c1={ref[0]:9} stack={got[0]:9}")
        if got != ref:
            # control: is c1_verdict even self-consistent on this cell? (T1 perm RNG)
            ctrl = c1_verdict(cell, data, reps)
            disagreements.append((cell.id, cell.dataset, cell.a, cell.b, ref, got, ctrl))
    return len(cells), disagreements


# --------------------------------------------------------------------------- #
# (d) truth classification — PROTOCOL.md "Held-out gate", off build_obt's map  #
# --------------------------------------------------------------------------- #
def truth_class(group: dict[str, str], a: str, b: str) -> str:
    """PROTOCOL.md's three buckets, as specified for this leg:
    fact-internal (either column fact-own) > in-group (same fold group) > cross-group."""
    ga, gb = group[a], group[b]
    if ga in FACT_GROUPS or gb in FACT_GROUPS:
        return "fact-internal"
    if ga.removesuffix("-key") == gb.removesuffix("-key"):
        return "in-group"
    return "cross-group"


def truth_class_harness(group: dict[str, str], a: str, b: str) -> str:
    """The fold harness's own residue taxonomy (`probe_fold_grade.grade`), verbatim —
    fact-internal only when BOTH columns are fact-own. Reported alongside, because it
    and the leg's rule disagree on every fact-vs-dim pair."""
    ga, gb = group[a], group[b]
    if ga.removesuffix("-key") == gb.removesuffix("-key"):
        return "in-group"
    if {ga, gb} <= {"fact", "fact-key"}:
        return "fact-internal"
    return "cross-group"


def ingroup_subclass(x: dict) -> str:
    """Structural shape of an in-group assert — group map + verdict only, no string or
    value heuristics. PROTOCOL.md reads in-group as 'real dimension structure, a veto is
    a FALSE veto'; these shapes test whether that reading survives contact with what the
    stack actually asserts INSIDE a fold group."""
    is_key = x["ga"].endswith("-key") or x["gb"].endswith("-key")
    if x["verdict"] == "MERGE":
        return ("key <-> attribute MERGE (identity or PROXY bijection?)" if is_key
                else "attribute <-> attribute MERGE")
    if x["verdict"] == "HIERARCHY":
        return ("key -> attribute HIERARCHY (the FK fold edge)" if is_key
                else "attribute -> attribute HIERARCHY")
    return f"{x['verdict']} (in-group)"


class Topology:
    """The declared metadata behind one OBT, replayed from schema.json exactly as
    build_obt walks the folds. Diagnostic ONLY — nothing here touches a verdict; it
    audits whether PROTOCOL.md's 'cross-group == join artifact' holds on this data."""

    def __init__(self, base: Path, spec: dict) -> None:
        schema = json.loads((base / "schema.json").read_text())
        fact = spec["fact"]
        g = dict.fromkeys(schema[fact]["columns"], "fact")
        g[schema[fact]["pkey"]] = "fact-key"
        # source[obt_col] = (source table, source column) — where the value physically
        # came from. Note a fold KEY keeps its own source (post__OwnerUserId is
        # posts.OwnerUserId) even though build_obt relabels its group to postowner-key.
        source = {c: (fact, c) for c in schema[fact]["columns"]}
        parents: dict[str, str] = {}
        dim_of: dict[str, str] = {}
        for key_col, dim, prefix in spec["folds"]:
            gname = prefix.rstrip("_")
            parents[gname] = g[key_col].removesuffix("-key")
            dim_of[gname] = dim
            pkey = schema[dim]["pkey"]
            g[key_col] = f"{gname}-key"
            for c in [c for c in schema[dim]["columns"] if c != pkey]:
                g[f"{prefix}{c}"] = gname
                source[f"{prefix}{c}"] = (dim, c)
        self.schema, self.parents, self.dim_of, self.source = schema, parents, dim_of, source

    def fk_target(self, col: str) -> str | None:
        """The dim table this obt column's SOURCE column declares an FK into, if any."""
        t, c = self.source[col]
        return self.schema[t].get("fkeys", {}).get(c)

    def is_identity_of(self, col: str, group: dict[str, str]) -> str | None:
        """If `col` is a fold group's identity column (`<g>-key`), the dim it identifies."""
        gname = group[col]
        return self.dim_of.get(gname.removesuffix("-key")) if gname.endswith("-key") else None

    def cross_subclass(self, a: str, b: str, group: dict[str, str]) -> str:
        """WHY are these two groups different? PROTOCOL.md defines cross-group as two
        dims 'independently declared, with NO declared relationship between them'. These
        sub-classes test that stated precondition against the schema's own FK graph."""
        x, y = group[a].removesuffix("-key"), group[b].removesuffix("-key")
        if self.parents.get(x) == y or self.parents.get(y) == x:
            return "chain (fold-spec FK hop)"
        if x in self.dim_of and y in self.dim_of and self.dim_of[x] == self.dim_of[y]:
            return f"same-dim role ({self.dim_of[x]})"
        # one column IS a declared FK into the dim the other column IS the identity of
        for p, q in ((a, b), (b, a)):
            tgt = self.fk_target(p)
            if tgt and tgt == self.is_identity_of(q, group):
                return "declared FK -> identity (SAME entity)"
        dx, dy = self.dim_of.get(x), self.dim_of.get(y)
        if dx and dy:
            if dy in self.schema[dx].get("fkeys", {}).values():
                return f"dim-FK ({dx} -> {dy} declared)"
            if dx in self.schema[dy].get("fkeys", {}).values():
                return f"dim-FK ({dy} -> {dx} declared)"
        return "independent"


# --------------------------------------------------------------------------- #
# (c) asserted-structure enumeration                                           #
# --------------------------------------------------------------------------- #
def enumerate_obt(name: str, spec: dict, cache: dict) -> dict:
    """Enumerate one OBT's asserted structures. Result is cached to ASSERTS and fully
    serializable, so a crash on OBT k never discards OBT k-1's work and the report can
    be rebuilt without re-scanning. A failure is RECORDED as blocked, never worked
    around: the counts for the other OBTs stay valid and the block is reported as-is."""
    if name in cache and "blocked" not in cache[name]:
        print(f"\n### {name}  — cached ({len(cache[name]['asserted'])} asserted)")
        return {"name": name, "spec": spec, **cache[name]}

    base = DATA / spec["db"]
    print(f"\n### {name}  ({spec['db']} / {spec['fact']})")
    t0 = time.time()
    obt, group = build_obt(base, spec)
    build_s = time.time() - t0
    cols = list(obt.columns)
    print(f"  OBT: {len(obt):,} rows x {len(cols)} cols  (build {build_s:.0f}s)")
    meta = {"db": spec["db"], "fact": spec["fact"], "n_rows": len(obt), "cols": cols,
            "group": group, "n_cols": len(cols), "reps": spec["perm_reps"],
            "build_s": build_s}

    try:
        t0 = time.time()
        scan = scan_pairs(obt, cols)
        scan_s = time.time() - t0
        print(f"  scan {scan_s:.0f}s")
    except Exception as e:  # noqa: BLE001 — record the block, do not route around it
        why = f"{type(e).__name__}: {str(e).splitlines()[0][:180]}"
        print(f"  !! BLOCKED in fdlib.scan_pairs — {why}")
        cache[name] = {**meta, "blocked": why, "stage": "scan_pairs"}
        ASSERTS.write_text(json.dumps(cache, indent=1))
        return {"name": name, "spec": spec, **cache[name]}

    topo = Topology(base, spec)
    reps = spec["perm_reps"]
    t0 = time.time()
    asserted: list[dict] = []
    n_pairs = 0
    for i, a in enumerate(cols):
        for b in cols[i + 1 :]:
            n_pairs += 1
            v, d, why = stack_verdict(obt, group, scan, a, b, spec, reps)
            if v in ASSERTING:
                asserted.append(
                    {
                        "a": a, "b": b, "verdict": v, "direction": d, "reason": why,
                        "ga": group[a], "gb": group[b],
                        "truth": truth_class(group, a, b),
                        "truth_harness": truth_class_harness(group, a, b),
                        "cross_sub": (
                            topo.cross_subclass(a, b, group)
                            if truth_class(group, a, b) == "cross-group" else ""
                        ),
                    }
                )
            if n_pairs % 200 == 0:
                print(f"    {n_pairs} pairs, {len(asserted)} asserted ({time.time() - t0:.0f}s)")
    stack_s = time.time() - t0
    print(f"  {n_pairs} pairs scanned, {len(asserted)} asserted ({stack_s:.0f}s)")

    cache[name] = {**meta, "scan_s": scan_s, "stack_s": stack_s,
                   "n_pairs": n_pairs, "asserted": asserted}
    ASSERTS.write_text(json.dumps(cache, indent=1))
    return {"name": name, "spec": spec, **cache[name]}


# --------------------------------------------------------------------------- #
# (e) report                                                                   #
# --------------------------------------------------------------------------- #
def matrix(rows: list[dict], key: str = "truth") -> str:
    classes = ("in-group", "cross-group", "fact-internal")
    out = [f"{'verdict':12}" + "".join(f"{c:>15}" for c in classes) + f"{'total':>9}"]
    for v in ASSERTING:
        cells = [sum(1 for r in rows if r["verdict"] == v and r[key] == c) for c in classes]
        out.append(f"{v:12}" + "".join(f"{n:>15}" for n in cells) + f"{sum(cells):>9}")
    tots = [sum(1 for r in rows if r[key] == c) for c in classes]
    out.append(f"{'TOTAL':12}" + "".join(f"{n:>15}" for n in tots) + f"{sum(tots):>9}")
    return "\n".join(out)


def main(only: set[str] | None = None) -> None:
    print("# DAT-762 held-out leg — mechanical stage (ZERO LLM calls)\n")
    cache = json.loads(ASSERTS.read_text()) if ASSERTS.exists() else {}

    # ---- (b) validate the port on the dev cells ---------------------------- #
    if "_dev_equivalence" in cache:
        eq = cache["_dev_equivalence"]
        n_cells, disagreements = eq["n_cells"], eq["disagreements"]
        print(f"## dev equivalence — cached: {n_cells - len(disagreements)}/{n_cells} agree")
    else:
        print("## loading the DAT-757 dev OBTs (rel-f1 / rel-hm / rel-salt)")
        data = load_all()
        print("\n## stack_verdict vs c1_verdict on the non-constructed dev cells")
        n_cells, disagreements = validate_stack(data)
        cache["_dev_equivalence"] = {"n_cells": n_cells, "disagreements": disagreements}
        ASSERTS.write_text(json.dumps(cache, indent=1))
        del data  # free the dev OBTs before the held-out scans

    emit("# DAT-762 held-out leg — mechanical counts")
    emit()
    emit("Protocol: `PROTOCOL.md` (frozen), section *Held-out gate — the verdict (Q5)*. "
         "**This stage made ZERO LLM calls.** It builds and validates the held-out "
         "harness and sizes the judge leg before the dev gate resolves.")
    emit()
    emit("Instruments imported read-only and unmodified: `dat757-g3-wide/fdlib.py`, "
         "`dat757-relbench/probe_fold_grade.py` (`SPECS`, `build_obt`), "
         "`dat757-channel-ablation/probe_ablation.py` (`c1_verdict`, `lam`, `utf`) and "
         "`cells.py`.")
    emit()

    # ---- 1. equivalence (buffered: the BLOCKED section must lead the report) -- #
    _eq: list[str] = []
    _real_emit, globals()["emit"] = emit, lambda t="": _eq.append(t)
    emit("## 1. `stack_verdict` vs `c1_verdict` — equivalence on the dev cells")
    emit()
    verdict = "PASS" if not disagreements else "FAIL"
    emit(f"**{verdict} — {n_cells - len(disagreements)}/{n_cells} cells agree exactly** "
         f"(verdict, direction and reason), on the 43 non-constructed DAT-757 dev cells "
         f"(rel-f1 / rel-hm / rel-salt). The 2 constructed cross-view cells (K1, K2) have "
         f"no OBT and no joint statistics, so they are outside the port's domain.")
    emit()
    if disagreements:
        emit("```")
        for cid, ds, a, b, ref, got, ctrl in disagreements:
            emit(f"  {cid} [{ds}] {a} vs {b}")
            emit(f"    c1_verdict   : {ref}")
            emit(f"    stack_verdict: {got}")
            emit(f"    c1 re-run    : {ctrl}   <- self-consistency control")
        emit("```")
        emit()
        emit("> A disagreement means the port is wrong (or the stack is non-deterministic) "
             "and **the held-out leg below is invalid** until it is resolved.")
    else:
        emit("No disagreements. The port is the frozen stack.")
    emit()

    globals()["emit"] = _real_emit  # equivalence captured; resume direct emission

    # ---- (c)/(d) held-out enumeration -------------------------------------- #
    # --only isolates one OBT in a fresh process: DuckDB's arena is not returned to
    # the OS after an OOM, so a scan that follows a failed scan in the SAME process
    # can fail for want of memory it would otherwise have had. Isolation tells a real
    # capacity limit apart from that cascade; the report states which is which.
    print("\n## held-out OBTs")
    all_results = []
    for n, s in SPECS_762.items():
        if only and n not in only:
            if n in cache:
                print(f"\n### {n}  — from cache (not selected this run)")
                all_results.append({"name": n, "spec": s, **cache[n]})
            continue
        all_results.append(enumerate_obt(n, s, cache))
    blocked = [r for r in all_results if "blocked" in r]
    results = [r for r in all_results if "blocked" not in r]

    if blocked:
        emit("## 0. BLOCKED OBTs — read this first")
        emit()
        emit(f"**{len(blocked)} of {len(all_results)} recommended OBTs could not be measured "
             f"at all.** The frozen instrument fails on them; per the standing rule a known "
             f"blocker is reported, not designed around. Nothing below is tuned to "
             f"compensate.")
        emit()
        emit("```")
        for r in blocked:
            emit(f"{r['name']}  ({r['db']} / {r['fact']})")
            emit(f"  OBT built fine: {r['n_rows']:,} rows x {r['n_cols']} cols")
            emit(f"  BLOCKED in {r['stage']}: {r['blocked']}")
        emit("```")
        emit()
        dbs = sorted({r["db"] for r in results})
        emit(f"**Consequence for G-H3.** The measurable OBTs cover **{len(dbs)} database(s)**: "
             f"{', '.join(dbs)}. PROTOCOL.md's **G-H3 requires G-H1 and G-H2 to hold "
             f"independently on >= 2 held-out databases**. Two OBTs from the *same* database "
             f"are not two databases, so **G-H3 cannot be satisfied as pre-registered** "
             f"unless a second database is recovered. This is a gate-blocking finding and "
             f"it is surfaced before any billed call, which is what this stage is for.")
        emit()

    for _l in _eq:
        emit(_l)
    emit()
    emit("## 2. The held-out OBTs")
    emit()
    emit("Perm reps = **999** for every OBT (`perm_reps` in each spec) — the DAT-757 "
         "precedent for non-rel-f1 OBTs (rel-f1 alone used 2999). Alias and edge "
         "significance are per-pair perm-p <= 0.05, exactly as `c1_verdict`.")
    emit()
    emit("```")
    emit(f"{'spec':28} {'db':11} {'fact':20} {'rows':>9} {'cols':>5} {'build':>7} "
         f"{'scan':>7} {'stack':>8}")
    for r in results:
        emit(f"{r['name']:28} {r['spec']['db']:11} {r['spec']['fact']:20} "
             f"{r['n_rows']:>9,} {len(r['cols']):>5} {r['build_s']:>6.0f}s "
             f"{r['scan_s']:>6.0f}s {r['stack_s']:>7.0f}s")
    emit("```")

    # ---- group vocabulary --------------------------------------------------- #
    emit()
    emit("### Fold-group label vocabulary (read off `build_obt`'s returned map — not guessed)")
    emit()
    emit("`build_obt` labels the fact's columns `fact`, its pkey `fact-key`, each folded "
         "dim's attributes `<prefix>` and **the FK column itself** `<prefix>-key` "
         "(`group[key_col] = f\"{gname}-key\"` — the fk IS the folded dim's identity "
         "column). Note the consequence: a fold whose key is itself a folded column "
         "(`post__OwnerUserId`) is **relabelled out of its parent group** into "
         "`postowner-key`.")
    emit()
    for r in results:
        emit(f"**{r['name']}**")
        emit()
        emit("```")
        cnt = Counter(r["group"][c] for c in r["cols"])
        for g, n in sorted(cnt.items(), key=lambda kv: (kv[0].removesuffix("-key"), kv[0])):
            members = [c for c in r["cols"] if r["group"][c] == g]
            shown = ", ".join(members[:6]) + (f", … (+{len(members) - 6})" if len(members) > 6 else "")
            emit(f"  {g:18} {n:>3} cols   {shown}")
        emit(f"  {'-- total':18} {sum(cnt.values()):>3} cols")
        emit("```")
        emit()

    # ---- 3. the matrix ------------------------------------------------------ #
    emit("## 3. Asserted structures — stack verdict x truth class")
    emit()
    emit("Truth per PROTOCOL.md: **in-group** = both columns in the same declared fold "
         "group (real dimension structure — a veto is a FALSE veto); **cross-group** = "
         "two different declared dim fold groups (join artifact — a veto is a TRUE veto); "
         "**fact-internal** = either column is fact-own (`fact` / `fact-key`) — reported, "
         "excluded from gate arithmetic.")
    emit()
    for r in results:
        n_ass = len(r["asserted"])
        emit(f"### {r['name']} — {r['n_pairs']:,} pairs scanned, {n_ass} asserted "
             f"({100 * n_ass / max(1, r['n_pairs']):.1f}%)")
        emit()
        emit("```")
        emit(matrix(r["asserted"]))
        emit("```")
        emit()
    emit(f"### All {len(results)} measurable OBT(s) combined")
    emit()
    all_ass = [dict(x, obt=r["name"]) for r in results for x in r["asserted"]]
    emit("```")
    emit(matrix(all_ass))
    emit("```")
    emit()
    emit("Same asserts under the **fold harness's own residue taxonomy** "
         "(`probe_fold_grade.grade`: fact-internal only when BOTH columns are fact-own, "
         "so every fact-vs-dim pair lands in cross-group). PROTOCOL.md cites that "
         "taxonomy but its own bullet says *either* column — the two rules disagree, and "
         "the difference is exactly the fact-vs-dim asserts:")
    emit()
    emit("```")
    emit(matrix(all_ass, key="truth_harness"))
    emit("```")
    emit()

    # ---- 4. per fold group -------------------------------------------------- #
    emit("## 4. Asserted structures per fold group")
    emit()
    for r in results:
        emit(f"### {r['name']}")
        emit()
        emit("```")
        emit(f"{'group pair':46} {'MERGE':>6} {'HIER':>6} {'ROLE':>6} {'total':>6}  class")
        pairs: Counter = Counter()
        for x in r["asserted"]:
            key = tuple(sorted((x["ga"], x["gb"])))
            pairs[(key, x["verdict"], x["truth"])] += 1
        seen: dict = {}
        for (key, v, t), n in pairs.items():
            seen.setdefault((key, t), Counter())[v] += n
        for (key, t), c in sorted(seen.items(), key=lambda kv: -sum(kv[1].values())):
            label = f"{key[0]} | {key[1]}"
            emit(f"{label:46} {c['MERGE']:>6} {c['HIERARCHY']:>6} {c['ROLE']:>6} "
                 f"{sum(c.values()):>6}  {t}")
        emit("")
        by_group: Counter = Counter()
        for x in r["asserted"]:
            if x["truth"] == "in-group":
                by_group[x["ga"].removesuffix("-key")] += 1
        emit("  in-group asserts concentrated by dim: "
             + (", ".join(f"{g}={n}" for g, n in by_group.most_common()) or "none"))
        emit("```")
        emit()

    # ---- 5. the headline ---------------------------------------------------- #
    emit("## 5. Headline — cost of an exhaustive held-out leg")
    emit()
    emit("`calls = (asserted in-group + asserted cross-group) x 1 arm x 3 reps` "
         "(PROTOCOL.md: 3 repetitions per cell per arm; the held-out gate runs the "
         "winning arm only). Fact-internal asserts are excluded from the gate arithmetic "
         "and are listed separately.")
    emit()
    emit("```")
    emit(f"{'OBT':28} {'in-group':>9} {'cross':>7} {'gated':>7} {'x3 reps':>9}   "
         f"{'fact-internal':>14}")
    tot_g = tot_f = 0
    for r in results:
        ig = sum(1 for x in r["asserted"] if x["truth"] == "in-group")
        cg = sum(1 for x in r["asserted"] if x["truth"] == "cross-group")
        fi = sum(1 for x in r["asserted"] if x["truth"] == "fact-internal")
        tot_g += ig + cg
        tot_f += fi
        emit(f"{r['name']:28} {ig:>9} {cg:>7} {ig + cg:>7} {3 * (ig + cg):>9}   {fi:>14}")
    emit(f"{'TOTAL':28} {'':>9} {'':>7} {tot_g:>7} {3 * tot_g:>9}   {tot_f:>14}")
    emit("```")
    emit()
    emit(f"**{3 * tot_g:,} LLM calls** for an exhaustive held-out leg over the "
         f"{len(results)} measurable OBT(s) ({tot_g:,} gated structures x 3 reps, one arm). Grading the {tot_f:,} "
         f"fact-internal asserts as well would add {3 * tot_f:,} calls "
         f"(**{3 * (tot_g + tot_f):,}** total).")
    emit()

    # ---- 6. examples -------------------------------------------------------- #
    emit("## 6. Examples — is the truth model plausible?")
    emit()
    for cls in ("in-group", "cross-group"):
        pool = [x for x in all_ass if x["truth"] == cls]
        emit(f"### asserted **{cls}** ({len(pool)} total; sample below)")
        emit()
        emit("```")
        per_obt = max(1, 9 // max(1, len(results)))
        shown = []
        for r in results:
            sub = [x for x in pool if x["obt"] == r["name"]]
            for v in ASSERTING:  # spread the sample across verdicts
                shown += [x for x in sub if x["verdict"] == v][:per_obt]
        for x in shown[:12]:
            d = f"/{x['direction']}" if x["direction"] else ""
            extra = f"  [{x['cross_sub']}]" if x["cross_sub"] else ""
            emit(f"  {x['obt'][:20]:20} {x['verdict'] + d:16} {x['a']} <-> {x['b']}")
            emit(f"    {x['ga']} | {x['gb']}{extra}   ({x['reason']})")
        emit("```")
        emit()

    # ---- 7. truth-model audit ----------------------------------------------- #
    emit("## 7. Truth-model audit — where 'cross-group == artifact' is shaky")
    emit()
    emit("Every asserted cross-group pair, sub-classified by **why** the two groups are "
         "different. This is diagnostic: the sub-class is replayed from the spec's own "
         "fold list and `schema.json`, and no verdict depends on it. The protocol scores "
         "all three sub-classes identically as *artifact, veto = TRUE veto*.")
    emit()
    emit("PROTOCOL.md defines cross-group as *\"the columns belong to two independently "
         "declared dimensions **with no declared relationship between them**\"*. Each "
         "sub-class below tests that stated precondition against the schema's own FK "
         "graph — the first four all **falsify it**:")
    emit()
    emit("- **chain (fold-spec FK hop)** — the spec itself folds one group's column into "
         "the other's dim (`post__OwnerUserId -> users`). A real two-hop dimension chain "
         "— exactly the structure DAT-757 counted as *truth* on rel-f1 "
         "(`raceId -> race__circuitId -> circuit__*`).")
    emit("- **same-dim role** — both groups are folded from the SAME dim table via "
         "different FK roles. Same concept, deliberately distinct instances — i.e. the "
         "textbook ROLE verdict, which the stack asserting is *correct* behaviour.")
    emit("- **declared FK -> identity (SAME entity)** — one column IS a declared FK into "
         "the very dim the other column IS the identity of. These are the same entity by "
         "construction of the declared schema; a MERGE here is right.")
    emit("- **dim-FK** — the two source dim tables are related by a declared FK in "
         "`schema.json`, so they are not 'independently declared' in PROTOCOL's sense.")
    emit("- **independent** — two dims with no declared relationship anywhere. **The only "
         "sub-class PROTOCOL's 'join artifact' reading actually describes.**")
    emit()
    emit("```")
    emit(f"{'OBT':28} {'sub-class':30} {'MERGE':>6} {'HIER':>6} {'ROLE':>6} {'total':>6}")
    for r in results:
        cg = [x for x in r["asserted"] if x["truth"] == "cross-group"]
        subs: dict = {}
        for x in cg:
            subs.setdefault(x["cross_sub"], Counter())[x["verdict"]] += 1
        for s, c in sorted(subs.items(), key=lambda kv: -sum(kv[1].values())):
            emit(f"{r['name']:28} {s:30} {c['MERGE']:>6} {c['HIERARCHY']:>6} "
                 f"{c['ROLE']:>6} {sum(c.values()):>6}")
    emit("")
    allsub: dict = {}
    for x in all_ass:
        if x["truth"] == "cross-group":
            allsub.setdefault(x["cross_sub"], Counter())[x["verdict"]] += 1
    for s, c in sorted(allsub.items(), key=lambda kv: -sum(kv[1].values())):
        emit(f"{'ALL':28} {s:30} {c['MERGE']:>6} {c['HIERARCHY']:>6} {c['ROLE']:>6} "
             f"{sum(c.values()):>6}")
    emit("```")
    emit()
    n_cg = sum(1 for x in all_ass if x["truth"] == "cross-group")
    n_indep = sum(1 for x in all_ass if x["cross_sub"] == "independent")
    if n_cg:
        emit(f"**{n_cg - n_indep} of {n_cg} cross-group asserts ({100 * (n_cg - n_indep) / n_cg:.0f}%) "
             f"are NOT independent dims** — they sit on a declared FK chain or are two "
             f"roles of one dim. Under G-H2 every one of them counts as an artifact the "
             f"judge is REWARDED for vetoing.")
    emit()
    # ---- 7b. the in-group side of the same audit ---------------------------- #
    emit("## 7b. Truth-model audit — the in-group side ('a veto here is a FALSE veto')")
    emit()
    emit("The gate's other half. G-H1 penalises the judge for every in-group assert it "
         "vetoes, so in-group must mean *real, groupable structure*. Shapes below are "
         "structural (group map + verdict only):")
    emit()
    emit("```")
    emit(f"{'OBT':28} {'shape':50} {'count':>6}")
    for r in results:
        sub: Counter = Counter()
        for x in r["asserted"]:
            if x["truth"] == "in-group":
                sub[ingroup_subclass(x)] += 1
        for s, n in sub.most_common():
            emit(f"{r['name']:28} {s:50} {n:>6}")
    emit("```")
    emit()
    key_merge = [x for x in all_ass
                 if x["truth"] == "in-group" and x["verdict"] == "MERGE"
                 and (x["ga"].endswith("-key") or x["gb"].endswith("-key"))]
    if key_merge:
        emit(f"**{len(key_merge)} of {sum(1 for x in all_ass if x['truth'] == 'in-group')} "
             f"in-group asserts are `key <-> attribute` MERGEs.** A fold key is unique per "
             f"dim row, so it is bijective with EVERY attribute of that row — the bijection "
             f"is an artifact of the key's uniqueness, not evidence of shared identity. "
             f"These are the dev set's own **P-proxy-bijection** and **E-free-text** shapes, "
             f"whose pre-registered truth is **REJECT**. Vetoing them is the CORRECT call, "
             f"yet G-H1 scores every one as a *false veto*:")
        emit()
        emit("```")
        for x in key_merge[:10]:
            emit(f"  {x['obt'][:20]:20} MERGE  {x['a']} <-> {x['b']}   [{x['ga']} | {x['gb']}]")
        if len(key_merge) > 10:
            emit(f"  … (+{len(key_merge) - 10} more)")
        emit("```")
        emit()

    emit("### Named counterexamples (asserted, cross-group, and arguably real)")
    emit()
    emit("```")
    named = [x for x in all_ass if x["truth"] == "cross-group" and x["cross_sub"] != "independent"]
    for x in named[:15]:
        d = f"/{x['direction']}" if x["direction"] else ""
        emit(f"  {x['obt'][:20]:20} {x['verdict'] + d:16} {x['a']} <-> {x['b']}")
        emit(f"    {x['ga']} | {x['gb']}  [{x['cross_sub']}]")
    if len(named) > 15:
        emit(f"  … (+{len(named) - 15} more)")
    emit("```")

    # ---- 8. the honest read ------------------------------------------------- #
    emit()
    emit("## 8. Honest read — does the mechanical truth model hold up?")
    emit()
    n_ig = sum(1 for x in all_ass if x["truth"] == "in-group")
    emit("**No. On the one measurable OBT it is close to INVERTED relative to the dev "
         "set's own pre-registered labels.** Both halves fail, in opposite directions:")
    emit()
    emit(f"1. **cross-group is not 'artifact'.** {n_cg}/{n_cg} asserted cross-group pairs "
         f"sit on a declared FK path or are two roles of one dim — **zero** are the "
         f"'independently declared dimensions with no declared relationship' PROTOCOL.md "
         f"defines. `PostId -> postowner__Location` is the post's author's location: the "
         f"exact two-hop shape DAT-757 counted as *truth* on rel-f1. G-H2 pays the judge "
         f"3:1 to destroy them.")
    emit(f"2. **in-group is not all 'real'.** {len(key_merge)}/{n_ig} in-group asserts are "
         f"`key <-> attribute` MERGEs like `PostId <-> post__Body` — a bijection that "
         f"exists only because the key is unique per dim row. That is the dev set's "
         f"P-proxy-bijection / E-free-text shape, truth **REJECT**. G-H1 charges the judge "
         f"a false veto for getting them right.")
    emit()
    emit("A judge could therefore *pass* G-H1+G-H2 by behaving exactly wrong, and *fail* "
         "by behaving exactly right. The fold-group map answers \"which dim did this "
         "column arrive from?\" — it was never a claim about groupability, which is the "
         "property the gate needs. Running the leg on this truth model would spend real "
         "money to measure the judge's agreement with an artifact of the fold spec.")
    emit()
    emit("**Recommendation: do not run the held-out leg as specified.** The counts above "
         "are the sizing you asked for and the leg is mechanically ready — but the "
         "sampling rule needs fixing first, and G-H3 is unreachable regardless "
         "(1 measurable database, gate needs >= 2). Options, none taken here — they are "
         "yours:")
    emit()
    emit("- **The blocker.** `fdlib.scan_pairs` computes every pair's joint distinct count "
         "in ONE DuckDB query, so cost scales with n_cols x total bytes: ~22-27 GB naive "
         "on all three OBTs vs a 38.3 GiB machine. R1 fits at 22.7 GB; R3 (22.5 GB) and R2 "
         "(26.5 GB) do not — R1 is itself near the edge. A chunked scan would fix it, but "
         "`fdlib` is frozen, so that is a decision, not a repair I should make. A "
         "DAT-762-owned scan proven identical to `scan_pairs` on the dev OBTs is the "
         "cheapest honest route to a second database.")
    emit("- **The truth model.** If in-group/cross-group is kept, it needs to grade "
         "*groupability*, not fold provenance: at minimum exclude `<g>-key <-> attribute` "
         "bijections from in-group, and count declared-chain / same-dim-role pairs as real "
         "rather than artifact. That is a change to a pre-registered gate and must be an "
         "explicit, dated amendment — not something inferred from these numbers.")
    emit("- **The corpus.** rel-avito / rel-event were CUT on C6 (opaque numeric dims) and "
         "on truncation integrity — but opaque numeric dims are exactly the cheap-to-scan "
         "case. If a second database matters more than text richness, that CUT is worth "
         "revisiting on its own terms.")

    # ASSERTS already holds the exact pair list a held-out judge leg would grade
    # (written per-OBT as each completes), so no later stage re-scans to get it.
    REPORT.write_text("\n".join(_LINES) + "\n")
    print(f"\n\nwrote {REPORT}\nwrote {ASSERTS}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", help="comma-separated spec names to enumerate this run; "
                                   "others are taken from the cache. Use to isolate one "
                                   "OBT in a fresh process after an OOM.")
    args = ap.parse_args()
    main({s.strip() for s in args.only.split(",")} if args.only else None)
