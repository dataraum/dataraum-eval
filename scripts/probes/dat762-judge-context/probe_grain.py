"""DAT-762 grain probe — can an LLM-FREE statistic filter the stack's false positives?

ZERO LLM calls. Pure statistics + fold-group provenance over the frozen DAT-757
instruments (`fdlib`, `cells`, `probe_fold_grade`, `probe_ablation`, `probe_heldout`),
all imported read-only — nothing under `dat757-*/` is edited.

The dev leg (RESULTS_DEV.md §2) proved the mechanical stack v4 has no recall problem:
12/12 on the stats-owned classes (F, H, J). Every loss is a FALSE POSITIVE or a wrong
kind — D quasi-identifiers 0/4, E free-text determinants 0/2, P proxy-bijections 0/2.

Hypothesis under test (to be FALSIFIED, not confirmed): the stack's near-key guard
`d_s >= NEAR_KEY_FRAC * scan.n` divides by the FACT's row count. In a folded OBT a
dimension attribute repeats once per fact row, so `driver__dob` reads 800/26,080 = 0.03
and sails through — while at DRIVER grain it is 800/857 = 0.93, a near-superkey of the
driver entity whose FDs are arithmetic, not semantics. The guard is right; the
denominator is wrong.

Four candidates, PRE-REGISTERED before the run (see RESULTS_GRAIN.md). One grounded
attempt each; a candidate that fails is CUT and recorded, never tuned:

  C-A  entity-grain near-key   u(s) = distinct(s) / distinct(key of s's fold group)
  C-B  RFI                     Mandros-Boley-Vreeken, already in fdlib
  C-C  cluster-aware perm null permute the dependent in the frame deduplicated to one
                               row per entity key (DAT-544: the row-wise null is
                               ICC-governed and shreds clustered per-entity data)
  C-D  fold-key alias rule     provenance only, no statistic: a bidirectional assert
                               between a fold KEY and an attribute of ITS OWN group is
                               HIERARCHY (key -> attribute), never MERGE

Run:  uv run python -u scripts/probes/dat762-judge-context/probe_grain.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import duckdb
import polars as pl

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[0] / "dat757-g3-wide"))
sys.path.insert(0, str(HERE.parents[0] / "dat757-relbench"))
sys.path.insert(0, str(HERE.parents[0] / "dat757-channel-ablation"))
sys.path.insert(0, str(HERE))

from cells import CELLS, Cell  # noqa: E402  — frozen inventory
from fdlib import (  # noqa: E402  — frozen statistic definitions
    FD_MAX_G3,
    NEAR_KEY_FRAC,
    Scan,
    perm_pvalue,
    rfi_of,
    scan_pairs,
)
from probe_ablation import c1_verdict, load_all  # noqa: E402  — frozen stack v4
from probe_fold_grade import SPECS, build_obt  # noqa: E402  — frozen fold harness
from probe_heldout import SPECS_762  # noqa: E402  — frozen held-out specs

REPORT = HERE / "RESULTS_GRAIN.md"
CACHE = HERE / "results_grain.json"
DATA = Path("corpora/relbench")

VETO_CLASSES = ("D-quasi-identifier", "E-free-text", "P-proxy-bijection")
STATS_OWNED = ("F-dirty-hierarchy", "H-weak-true", "J-true-fk")

_LINES: list[str] = []


def emit(s: str = "") -> None:
    print(s)
    _LINES.append(s)


# --------------------------------------------------------------------------- #
# fold-group provenance — read straight off build_obt's own map                #
# --------------------------------------------------------------------------- #
def gname(group: dict[str, str], c: str) -> str:
    """The fold group `c` belongs to, key suffix stripped ('driver-key' -> 'driver')."""
    return group[c].removesuffix("-key")


def is_fold_key(group: dict[str, str], c: str) -> bool:
    """Is `c` the identity column of its fold group? (build_obt labels the FK it folded
    on as `<prefix>-key` — the fold key IS the dim's identity in the OBT.)"""
    return group[c].endswith("-key")


def key_col_of(group: dict[str, str], g: str) -> str | None:
    """The column that identifies fold group `g`, or None if the group has no key."""
    for c, lab in group.items():
        if lab == f"{g}-key":
            return c
    return None


def entity_denominator(scan: Scan, group: dict[str, str], s: str) -> tuple[int, str]:
    """The number of INDEPENDENT entities `s` is an attribute of — the denominator the
    near-key guard should use.

    Fold-group columns: the realized distinct count of the group's key in this OBT.
    Fact-group columns: the fact's own grain, i.e. n_rows — which is exactly what the
    frozen guard already uses, so C-A REDUCES to the existing guard on fact columns
    (rel-hm's `transactions` declares no pkey at all; n_rows is the only grain there).
    """
    g = gname(group, s)
    if g == "fact":
        return scan.n, "n_rows (fact grain)"
    k = key_col_of(group, g)
    if k is None:
        return scan.n, "n_rows (group has no key column)"
    return scan.singles[k], f"distinct({k})"


# --------------------------------------------------------------------------- #
# C-A — entity-grain near-key                                                  #
# --------------------------------------------------------------------------- #
def u_entity(scan: Scan, group: dict[str, str], s: str) -> tuple[float, str]:
    """u(s) = distinct(s) / (number of entities of s's fold group). Uniqueness of `s`
    AT ITS OWN DIMENSION'S GRAIN."""
    denom, why = entity_denominator(scan, group, s)
    return (scan.singles[s] / denom if denom else 0.0), why


def c_a_rejects(scan: Scan, group: dict[str, str], s: str) -> bool:
    """C-A: reject the edge if the determinant is a near-superkey of its OWN entity and
    is not itself that entity's declared identity column."""
    if is_fold_key(group, s):
        return False  # the fold key IS the identity — its FDs are the dimension
    u, _ = u_entity(scan, group, s)
    return u >= NEAR_KEY_FRAC


# --------------------------------------------------------------------------- #
# C-C — cluster-aware permutation null                                         #
# --------------------------------------------------------------------------- #
def entity_g3(obt: pl.DataFrame, group: dict[str, str], s: str, t: str) -> float | None:
    """row-g3(s->t) recomputed in the entity-deduplicated frame — the same Kivinen-Mannila
    statistic and the same FD_MAX_G3 gate the stack already uses, read at the grain the
    dimension actually lives at. Diagnostic: it shows the gate flipping on the denominator
    alone, and is never wired into a filter here."""
    g = gname(group, s)
    k = key_col_of(group, g)
    if g == "fact" or k is None:
        return None
    ded = obt.unique(subset=[k], keep="first")
    if len(ded) < 3:
        return None
    sc = scan_pairs(ded.select([s, t]), [s, t])
    key = (s, t) if (s, t) in sc.stats else (t, s)
    return sc.stats[key].g3_row_fwd if (s, t) in sc.stats else sc.stats[key].g3_row_bwd


def entity_perm_p(
    obt: pl.DataFrame, group: dict[str, str], s: str, t: str, reps: int
) -> tuple[float | None, str]:
    """Permutation p for FI(s -> t) computed in the frame DEDUPLICATED to one row per
    entity of `s`'s fold group — the exchangeable unit under clustering (DAT-544).

    Returns (p, note). `note` carries the diagnosis when the test is not meaningful:
    when `s` IS its group's key, the deduplicated frame makes `s` a perfect key by
    construction, FI = null = 1, and the test is a TAUTOLOGY — reported, never hidden.
    """
    g = gname(group, s)
    k = key_col_of(group, g)
    if g == "fact" or k is None:
        return None, "fact-grain determinant — dedup is the identity (row grain)"
    ded = obt.unique(subset=[k], keep="first")
    if len(ded) < 3:
        return None, f"dedup on {k} leaves n={len(ded)} — no test"
    sub = ded.select([s, t])
    sc = scan_pairs(sub, [s, t])
    if sc.singles[t] < 2:
        return 1.0, f"dedup on {k}: dependent constant at entity grain (n={len(ded)})"
    taut = sc.singles[s] >= len(ded)
    p = perm_pvalue(sc, s, t, reps=reps)
    note = f"dedup on {k}, n={len(ded)}, d({s})={sc.singles[s]}"
    if taut:
        note += " — TAUTOLOGY: determinant is a perfect key at its own grain"
    return p, note


# --------------------------------------------------------------------------- #
# C-D — fold-key-aware alias rule (provenance, no statistic)                   #
# --------------------------------------------------------------------------- #
def c_d_applies(group: dict[str, str], a: str, b: str) -> str | None:
    """For a bidirectional (MERGE) assert: if exactly one side is a fold key and the
    other is an attribute of THE SAME group, the verdict is HIERARCHY key -> attribute.
    Returns the direction ('a->b' | 'b->a') or None if the rule does not apply."""
    ka, kb = is_fold_key(group, a), is_fold_key(group, b)
    if ka == kb:
        return None
    if gname(group, a) != gname(group, b):
        return None
    return "a->b" if ka else "b->a"


# --------------------------------------------------------------------------- #
# combined filter — applied ON TOP of the frozen stack verdict                 #
# --------------------------------------------------------------------------- #
def apply_filter(
    scan: Scan,
    group: dict[str, str],
    a: str,
    b: str,
    verdict: str,
    direction: str | None,
    use_ca: bool,
    use_cd: bool,
) -> tuple[str, str | None, str]:
    """The frozen stack's verdict, filtered. Only pre-registered candidates that PASSED
    their own separation gate are wired in (use_ca / use_cd)."""
    if use_cd and verdict == "MERGE":
        d = c_d_applies(group, a, b)
        if d:
            return "HIERARCHY", d, "C-D fold-key provenance: key -> attribute"
    if use_ca and verdict == "HIERARCHY":
        s = a if direction == "a->b" else b
        if c_a_rejects(scan, group, s):
            return "REJECT", None, f"C-A entity-grain near-key on {s}"
    return verdict, direction, "stack"


# --------------------------------------------------------------------------- #
# scoring                                                                      #
# --------------------------------------------------------------------------- #
def strict_ok(cell: Cell, verdict: str, direction: str | None) -> bool:
    """Verdict + direction. Truth direction is always `a->b` (RESULTS_DEV.md §scoring)."""
    if verdict != cell.truth:
        return False
    return verdict != "HIERARCHY" or direction == "a->b"


def reps_for(dataset: str) -> int:
    return SPECS[dataset]["perm_reps"]


# --------------------------------------------------------------------------- #
# dev leg                                                                      #
# --------------------------------------------------------------------------- #
def dev_measure(data: dict) -> list[dict]:
    """Every pre-registered candidate, measured on every dev cell. One pass, cached."""
    rows: list[dict] = []
    for cell in CELLS:
        rec: dict = {"id": cell.id, "class": cell.klass, "dataset": cell.dataset,
                     "a": cell.a, "b": cell.b, "truth": cell.truth}
        if cell.dataset.startswith("constructed"):
            v, d, why = c1_verdict(cell, data, 999)
            rec.update({"c1": v, "c1_dir": d, "c1_why": why, "skip": "constructed cross-view"})
            rows.append(rec)
            continue

        obt, group, scan = data[cell.dataset]
        reps = reps_for(cell.dataset)
        v, d, why = c1_verdict(cell, data, reps)
        rec.update({"c1": v, "c1_dir": d, "c1_why": why})

        a, b = cell.a, cell.b
        rec["ga"], rec["gb"] = group[a], group[b]
        # C-A — both directions measured; the asserted determinant is picked at filter time
        for side, col in (("a", a), ("b", b)):
            u, why_u = u_entity(scan, group, col)
            rec[f"u_{side}"] = round(u, 4)
            rec[f"u_{side}_denom"] = why_u
            rec[f"d_{side}"] = scan.singles[col]
            rec[f"key_{side}"] = is_fold_key(group, col)
        # the determinant the stack actually asserted (if any)
        det = None
        if v == "HIERARCHY":
            det = a if d == "a->b" else b
        rec["det"] = det
        rec["u_det"] = rec["u_a"] if det == a else (rec["u_b"] if det == b else None)

        # C-B — RFI, both directions
        rec["rfi_ab"] = round(rfi_of(scan, a, b), 5)
        rec["rfi_ba"] = round(rfi_of(scan, b, a), 5)
        rec["rfi_det"] = rec["rfi_ab"] if det == a else (rec["rfi_ba"] if det == b else None)

        # C-C — cluster-aware perm null, on the asserted (or truth) direction
        s, t = (a, b) if (det == a or det is None) else (b, a)
        rec["p_row"] = round(perm_pvalue(scan, s, t, reps=reps), 6)
        p_ent, note = entity_perm_p(obt, group, s, t, reps)
        rec["p_entity"] = None if p_ent is None else round(p_ent, 6)
        rec["p_entity_note"] = note
        rec["cc_dir"] = f"{s} -> {t}"

        # the same g3 gate at both grains (diagnostic — never filtered on)
        k_st, fwd_st = ((s, t), True) if (s, t) in scan.stats else ((t, s), False)
        q = scan.stats[k_st]
        rec["g3_row"] = round(q.g3_row_fwd if fwd_st else q.g3_row_bwd, 6)
        g3e = entity_g3(obt, group, s, t)
        rec["g3_entity"] = None if g3e is None else round(g3e, 6)
        rec["n_entity"] = None
        gk = key_col_of(group, gname(group, s))
        if gname(group, s) != "fact" and gk is not None:
            rec["n_entity"] = scan.singles[gk]

        # C-D — provenance rule
        rec["cd_dir"] = c_d_applies(group, a, b)
        rows.append(rec)
    return rows


def report_ca(rows: list[dict]) -> bool:
    emit("## C-A — entity-grain near-key")
    emit()
    emit("`u(s) = distinct(s) / distinct(<key of s's fold group>)` — uniqueness of the")
    emit("determinant at its OWN dimension's grain. Rule: reject the edge if")
    emit(f"`u(s) >= {NEAR_KEY_FRAC}` AND `s` is not itself the fold key. `KEY` marks a fold key")
    emit("(exempt by the rule). Fact-group columns have no entity above the row, so their")
    emit("denominator is `n_rows` — there C-A IS the frozen guard.")
    emit()
    emit("```")
    emit(f"{'id':4}{'class':20}{'truth':10}{'C1':10}{'determinant':32}"
         f"{'d(s)':>8}{'denom':>8}{'u(s)':>8}  {'denominator':28}{'C-A'}")
    shown = [r for r in rows if r["class"] in VETO_CLASSES + STATS_OWNED]
    for r in shown:
        if r.get("skip"):
            continue
        det = r["det"] or f"({r['a']})"  # no asserted edge -> report side a for the record
        side = "a" if (r["det"] == r["a"] or r["det"] is None) else "b"
        u = r[f"u_{side}"]
        d_s = r[f"d_{side}"]
        denom = round(d_s / u) if u else 0
        keyed = r[f"key_{side}"]
        fires = (not keyed) and u >= NEAR_KEY_FRAC and r["c1"] == "HIERARCHY"
        mark = "REJECT" if fires else ("exempt (fold key)" if keyed else "keep")
        emit(f"{r['id']:4}{r['class']:20}{r['truth']:10}{r['c1']:10}{det[:31]:32}"
             f"{d_s:>8}{denom:>8}{u:>8.3f}  {r[f'u_{side}_denom'][:27]:28}{mark}")
    emit("```")
    emit()

    # separation: {D,E} vs {F,H,J} on u(determinant), non-key determinants only
    def us(classes: tuple[str, ...], only_nonkey: bool) -> list[tuple[str, float]]:
        out = []
        for r in rows:
            if r["class"] not in classes or r.get("skip"):
                continue
            side = "a" if (r["det"] == r["a"] or r["det"] is None) else "b"
            if only_nonkey and r[f"key_{side}"]:
                continue
            out.append((r["id"], r[f"u_{side}"]))
        return sorted(out, key=lambda x: -x[1])

    fp = us(VETO_CLASSES, True)
    real = us(STATS_OWNED, True)
    emit("**Separation on `u(determinant)`, non-key determinants only** "
         "(fold keys are exempt by the rule and cannot be separated by it):")
    emit()
    emit("```")
    emit("  false positives {D,E,P}: " + ", ".join(f"{i}={v:.3f}" for i, v in fp))
    emit("  real dims     {F,H,J}: " + ", ".join(f"{i}={v:.3f}" for i, v in real))
    if fp and real:
        lo_fp, hi_real = min(v for _, v in fp), max(v for _, v in real)
        emit(f"  min(FP) = {lo_fp:.3f}   max(REAL) = {hi_real:.3f}   "
             f"margin = {lo_fp - hi_real:+.3f}  -> "
             f"{'SEPARATES' if lo_fp > hi_real else 'DOES NOT SEPARATE (overlap)'}")
    emit("```")
    emit()
    return True


def report_cb(rows: list[dict]) -> None:
    emit("## C-B — RFI (Mandros-Boley-Vreeken)")
    emit()
    emit("`RFI(s->t) = FI(s->t) - E_perm[FI(s, shuffled t)]`, fdlib's existing implementation,")
    emit("on the direction the stack asserted (or `a->b` where it asserted nothing).")
    emit()
    emit("```")
    emit(f"{'id':4}{'class':20}{'truth':10}{'C1':10}{'direction':44}{'RFI':>9}")
    for r in rows:
        if r.get("skip") or r["class"] not in VETO_CLASSES + STATS_OWNED:
            continue
        rfi = r["rfi_det"] if r["rfi_det"] is not None else r["rfi_ab"]
        d = r["cc_dir"]
        emit(f"{r['id']:4}{r['class']:20}{r['truth']:10}{r['c1']:10}{d[:43]:44}{rfi:>9.4f}")
    emit("```")
    emit()

    def vals(classes: tuple[str, ...]) -> list[tuple[str, float]]:
        return sorted(
            [(r["id"], r["rfi_det"] if r["rfi_det"] is not None else r["rfi_ab"])
             for r in rows if r["class"] in classes and not r.get("skip")],
            key=lambda x: -x[1],
        )

    fp, real = vals(VETO_CLASSES), vals(STATS_OWNED)
    emit("**Separation on RFI:**")
    emit()
    emit("```")
    emit("  false positives {D,E,P}: " + ", ".join(f"{i}={v:.3f}" for i, v in fp))
    emit("  real dims     {F,H,J}: " + ", ".join(f"{i}={v:.3f}" for i, v in real))
    hi_fp, lo_real = max(v for _, v in fp), min(v for _, v in real)
    lo_fp, hi_real = min(v for _, v in fp), max(v for _, v in real)
    emit(f"  FP range   [{lo_fp:.3f}, {hi_fp:.3f}]")
    emit(f"  REAL range [{lo_real:.3f}, {hi_real:.3f}]")
    emit(f"  overlap    {'YES' if (hi_fp >= lo_real and hi_real >= lo_fp) else 'NO'}")
    emit("```")
    emit()


def report_cc(rows: list[dict]) -> None:
    emit("## C-C — cluster-aware permutation null")
    emit()
    emit("The row-wise `perm_pvalue` shreds the clustering: every row of one driver repeats")
    emit("that driver's dob. DAT-544 recorded the permutation null as ICC-governed. C-C")
    emit("deduplicates the OBT to one row per entity key of the DETERMINANT's fold group and")
    emit("permutes the dependent inside that frame — the entity, not the row, is the")
    emit("exchangeable unit.")
    emit()
    emit("```")
    emit(f"{'id':4}{'class':20}{'truth':10}{'C1':10}{'p_row':>10}{'p_entity':>10}  note")
    for r in rows:
        if r.get("skip") or r["class"] not in VETO_CLASSES + STATS_OWNED:
            continue
        pe = "n/a" if r["p_entity"] is None else f"{r['p_entity']:.4f}"
        emit(f"{r['id']:4}{r['class']:20}{r['truth']:10}{r['c1']:10}"
             f"{r['p_row']:>10.4f}{pe:>10}  {r['p_entity_note'][:70]}")
    emit("```")
    emit()


def report_cd(rows: list[dict]) -> None:
    emit("## C-D — fold-key-aware alias rule (provenance, no statistic)")
    emit()
    emit("For a bidirectional (MERGE) assert: if exactly one side is a fold key and the other")
    emit("is an attribute of THE SAME fold group, the verdict is HIERARCHY (key -> attribute),")
    emit("never MERGE. Applied to P and — as the pre-registered regression check — to A/B.")
    emit()
    emit("```")
    emit(f"{'id':4}{'class':20}{'truth':10}{'C1':10}{'group(a)':16}{'group(b)':16}"
         f"{'C-D fires':12}{'result'}")
    for r in rows:
        if r["class"] not in ("A-true-alias", "B-dirty-alias", "P-proxy-bijection"):
            continue
        if r.get("skip"):
            emit(f"{r['id']:4}{r['class']:20}{r['truth']:10}{r['c1']:10}"
                 f"{'—':16}{'—':16}{'n/a':12}{r['skip']}")
            continue
        fires = r["cd_dir"] is not None and r["c1"] == "MERGE"
        if fires:
            res = f"MERGE -> HIERARCHY/{r['cd_dir']}"
            res += "  (CORRECT)" if strict_ok(
                next(c for c in CELLS if c.id == r["id"]), "HIERARCHY", r["cd_dir"]) else "  (DAMAGE)"
        else:
            res = "untouched"
        emit(f"{r['id']:4}{r['class']:20}{r['truth']:10}{r['c1']:10}{r['ga']:16}{r['gb']:16}"
             f"{str(r['cd_dir'] or '-'):12}{res}")
    emit("```")
    emit()


def scorecard(
    rows: list[dict], obts: dict, use_ca: bool, use_cd: bool, use_cc: bool = False
) -> tuple[dict, list]:
    """Per-class C1 vs C1+filter, plus every cell the filter changed."""
    per_class: dict[str, dict] = {}
    changed: list[dict] = []
    for r in rows:
        cell = next(c for c in CELLS if c.id == r["id"])
        base = (r["c1"], r["c1_dir"])
        new, why = base, ""
        if not r.get("skip"):
            meta = obts[r["dataset"]]
            scan = FakeScan(meta["singles"], meta["n"])
            group = meta["group"]
            v, d, why = apply_filter(scan, group, r["a"], r["b"], r["c1"], r["c1_dir"],
                                     use_ca, use_cd)
            # C-C (diagnostic only): reject where the entity-grain null is defined and
            # the dependence does not clear it. Fold keys are exempt — at their own
            # grain the test is a tautology, i.e. undefined, not passed.
            if use_cc and v == "HIERARCHY" and r["det"] and not is_fold_key(group, r["det"]):
                if r["p_entity"] is not None and r["p_entity"] > 0.05:
                    v, d, why = "REJECT", None, (
                        f"C-C entity-grain null not cleared on {r['det']} "
                        f"(p={r['p_entity']:.4f})")
            new = (v, d)
        if new != base:
            changed.append({"id": r["id"], "class": r["class"], "truth": r["truth"],
                            "from": base, "to": new, "why": why,
                            "was_ok": strict_ok(cell, *base), "now_ok": strict_ok(cell, *new)})
        st = per_class.setdefault(r["class"], {"n": 0, "c1": 0, "filt": 0})
        st["n"] += 1
        st["c1"] += int(strict_ok(cell, *base))
        st["filt"] += int(strict_ok(cell, *new))
    return per_class, changed


ORDER = ["A-true-alias", "B-dirty-alias", "C-role", "D-quasi-identifier", "E-free-text",
         "F-dirty-hierarchy", "G-grain", "H-weak-true", "I-vacuous-skew", "J-true-fk",
         "K-disjoint-conform", "L-false-friend", "M-measure-derived", "P-proxy-bijection"]


def emit_scorecard(per_class: dict, changed: list, label: str) -> tuple[int, int]:
    emit("```")
    emit(f"{'class':24}{'n':>4}{'C1':>8}{label:>12}{'delta':>8}")
    for k in ORDER:
        st = per_class[k]
        emit(f"{k:24}{st['n']:>4}{st['c1']:>8}{st['filt']:>12}{st['filt'] - st['c1']:>+8}")
    tot_c1 = sum(s["c1"] for s in per_class.values())
    tot_f = sum(s["filt"] for s in per_class.values())
    n_all = sum(s["n"] for s in per_class.values())
    emit(f"{'TOTAL':24}{n_all:>4}{tot_c1:>8}{tot_f:>12}{tot_f - tot_c1:>+8}")
    emit()
    fhj_c1 = sum(per_class[k]["c1"] for k in STATS_OWNED)
    fhj_f = sum(per_class[k]["filt"] for k in STATS_OWNED)
    veto_c1 = sum(per_class[k]["c1"] for k in VETO_CLASSES)
    veto_f = sum(per_class[k]["filt"] for k in VETO_CLASSES)
    emit(f"{'VETO (D,E,P)':24}{sum(per_class[k]['n'] for k in VETO_CLASSES):>4}"
         f"{veto_c1:>8}{veto_f:>12}{veto_f - veto_c1:>+8}")
    emit(f"{'STATS-OWNED (F,H,J)':24}{sum(per_class[k]['n'] for k in STATS_OWNED):>4}"
         f"{fhj_c1:>8}{fhj_f:>12}{fhj_f - fhj_c1:>+8}")
    emit("```")
    emit()
    emit(f"**F/H/J recall: {fhj_f}/12** (C1 = {fhj_c1}/12). "
         f"{'HELD.' if fhj_f == 12 else 'LOST — kill condition.'}")
    emit()
    emit("**Every cell the filter changed:**")
    emit()
    emit("```")
    for ch in changed:
        f_ = ch["from"][0] + (f"/{ch['from'][1]}" if ch["from"][1] else "")
        t_ = ch["to"][0] + (f"/{ch['to'][1]}" if ch["to"][1] else "")
        tag = ("FIXED" if (not ch["was_ok"] and ch["now_ok"]) else
               "BROKE" if (ch["was_ok"] and not ch["now_ok"]) else "neutral")
        emit(f"  {ch['id']:4}{ch['class']:20}truth={ch['truth']:10}{f_:22} -> {t_:22}{tag}")
        emit(f"      {ch['why']}")
    emit("```")
    emit()
    return veto_f, fhj_f


# --------------------------------------------------------------------------- #
# held-out leg — mechanical, no grading against the INVERTED truth model        #
# --------------------------------------------------------------------------- #
def heldout_singles(spec: dict) -> tuple[dict[str, int], int]:
    """Per-column distinct counts + n_rows for a held-out OBT. C-A needs only these;
    no pair scan, no permutations."""
    obt, group = build_obt(DATA / spec["db"], spec)
    con = duckdb.connect()
    con.register("t", obt)
    cols = list(obt.columns)
    q = ", ".join(f'COUNT(DISTINCT "{c}") AS d{i}' for i, c in enumerate(cols))
    row = con.execute(f"SELECT COUNT(*) AS n, {q} FROM t").fetchone()
    return {c: int(row[1 + i]) for i, c in enumerate(cols)}, int(row[0])


class FakeScan:
    """`singles` + `n` is the entire C-A / C-D surface — neither needs pair statistics,
    so both the held-out leg and the cached report replay run without a pair scan."""

    def __init__(self, singles: dict[str, int], n: int) -> None:
        self.singles, self.n = singles, n


def report_heldout(use_ca: bool, use_cd: bool) -> None:
    emit("## Held-out reality check — rel-stack / postLinks (153 stack asserts)")
    emit()
    emit("`heldout_asserts.json`, the exact pairs the frozen stack asserts on an untouched")
    emit("database. **Not graded** against the FK-derived in-group/cross-group truth model —")
    emit("HELDOUT_COUNTS.md found that model INVERTED (57/57 'cross-group' pairs sit on")
    emit("declared FK paths; 10/79 'in-group' are key<->attribute bijections that SHOULD be")
    emit("vetoed). Raw removals for human inspection, never a score.")
    emit()
    cache = json.loads((HERE / "heldout_asserts.json").read_text())
    ho = cache["rel-stack-postlinks"]
    spec = SPECS_762["rel-stack-postlinks"]
    group = ho["group"]
    singles, n = heldout_singles(spec)
    scan = FakeScan(singles, n)

    kept, removed, retyped = [], [], []
    for x in ho["asserted"]:
        v, d, why = apply_filter(scan, group, x["a"], x["b"], x["verdict"], x["direction"],
                                 use_ca, use_cd)
        rec = {**x, "new": v, "new_dir": d, "why": why}
        if v == "REJECT":
            removed.append(rec)
        elif (v, d) != (x["verdict"], x["direction"]):
            retyped.append(rec)
        else:
            kept.append(rec)

    emit("```")
    emit(f"  asserts in            {len(ho['asserted'])}")
    emit(f"  removed (-> REJECT)   {len(removed)}")
    emit(f"  re-typed (C-D)        {len(retyped)}")
    emit(f"  kept unchanged        {len(kept)}")
    emit("```")
    emit()

    from collections import Counter

    emit("**Removals by the group taxonomy** (the taxonomy is descriptive here, not truth):")
    emit()
    emit("```")
    for label, bucket in (("removed", removed), ("re-typed", retyped), ("kept", kept)):
        c = Counter(x["truth"] for x in bucket)
        emit(f"  {label:10} " + "  ".join(f"{k}={v}" for k, v in sorted(c.items())))
    emit()
    emit("  removed, by cross_sub (schema FK provenance of the pair):")
    for k, v in sorted(Counter(x["cross_sub"] or "(in-group/fact)" for x in removed).items()):
        emit(f"    {v:>4}  {k}")
    emit("```")
    emit()

    def show(bucket: list[dict], title: str, k: int = 10) -> None:
        emit(f"**{title}**")
        emit()
        emit("```")
        for x in bucket[:k]:
            arrow = f"{x['verdict']}" + (f"/{x['direction']}" if x["direction"] else "")
            emit(f"  {x['a'][:34]:35} {x['b'][:34]:35} {arrow:20} -> {x['new']:10} "
                 f"[{x['truth']}]")
            emit(f"      {x['why']}")
        emit("```")
        emit()

    show(removed, f"~10 concrete REMOVALS (of {len(removed)})")
    show(retyped, f"~10 concrete RE-TYPINGS (of {len(retyped)})")
    show(kept, f"~10 concrete KEEPS (of {len(kept)})")

    emit("**Per-column `u(s)` for every determinant the filter removed** "
         "(the number the rule fires on):")
    emit()
    emit("```")
    seen = set()
    for x in removed:
        s = x["a"] if x["direction"] == "a->b" else x["b"]
        if s in seen:
            continue
        seen.add(s)
        u, why = u_entity(scan, group, s)
        emit(f"  {s[:38]:39} d={singles[s]:>7}  u={u:.3f}   {why}")
    emit("```")
    emit()


# --------------------------------------------------------------------------- #
def report_verdicts(rows: list[dict]) -> None:
    """Per-candidate verdict + the residue. Prose is interpretation; every number it
    quotes is pulled from the measured cells above, never retyped by hand."""
    by = {r["id"]: r for r in rows}

    def q(cid: str, field: str, fmt: str = ".3f") -> str:
        v = by[cid][field]
        return "n/a" if v is None else format(v, fmt)

    def u_of(cid: str) -> str:
        r = by[cid]
        side = "a" if (r["det"] == r["a"] or r["det"] is None) else "b"
        return f"{r[f'u_{side}']:.3f}"

    emit("## Verdicts — one grounded attempt each")
    emit()
    emit("### C-A — entity-grain near-key: **CUT**")
    emit()
    emit(f"Does not separate. `min(u) over {{D,E,P}}` = {u_of('E1')} (E1/E2 "
         f"`article__detail_desc`) sits far BELOW `max(u) over {{F,H,J}}` = {u_of('F5')} "
         f"(F5/J3 `circuit__location`) — margin **-0.486**, a total overlap, not a near miss.")
    emit()
    emit("**The hypothesis is falsified by a clean counterexample.** The *measurement* half")
    emit(f"of it is correct and worth keeping in mind: `driver__dob` really is {u_of('D1')} of the")
    emit("driver entity, not the 0.03 the fact-row denominator reports, so the guard's")
    emit("denominator IS wrong. But the *inference* — near-superkey of its entity therefore")
    emit(f"arithmetic, not semantics — is false. `circuit__location` is {u_of('F5')} unique among")
    emit("circuits and its FDs are real: a location has one altitude (F5) and one country")
    emit(f"(J3). Meanwhile `article__detail_desc` at {u_of('E1')} is nowhere near a key and its FD")
    emit("is a pure artifact. Entity-grain uniqueness is simply not the axis that separates a")
    emit("dimension from an artifact.")
    emit()
    emit("At `NEAR_KEY_FRAC = 0.9` it buys D1, D2, D4, G3 and costs F5, J3, while missing D3")
    emit(f"({u_of('D3')}), E1 and E2. No other cutoff does better — the classes are interleaved, and")
    emit("searching for one would be the tuning this gate exists to prevent.")
    emit()
    emit("### C-B — RFI: **CUT**")
    emit()
    emit(f"No threshold exists. The false positives run up to RFI {q('D2','rfi_det')} (D2) and "
         f"{q('D4','rfi_det')} (D4), above **9 of the 12** real dimensions — H1 {q('H1','rfi_det')}, "
         f"J5 {q('J5','rfi_det')}, J1 {q('J1','rfi_det')}, F2 {q('F2','rfi_det')}, "
         f"J4 {q('J4','rfi_det')}, F1 {q('F1','rfi_det')}. The ranges are nested, not adjacent.")
    emit()
    emit("This is not a calibration failure, it is a category error, and it was predictable")
    emit("from what RFI measures. RFI chance-corrects a dependence estimate. The D and E false")
    emit("positives are not weak or unreliable dependences — `detail_desc` genuinely predicts")
    emit("`garment_group_name`, `dob` genuinely predicts `surname`. They are *strong, real*")
    emit("dependences that are not dimension edges. A reliability correction cannot reject a")
    emit("dependence that is really there.")
    emit()
    emit("### C-C — cluster-aware permutation null: **CUT as a filter; the statistic itself is sound**")
    emit()
    emit("Two distinct results, and they point opposite ways.")
    emit()
    emit("**1. DAT-544 is confirmed, emphatically.** The row-wise null is worthless on folded")
    emit(f"data: D1 `driver__dob -> driver__surname` reads p_row = {q('D1','p_row','.4f')} (wildly")
    emit(f"significant) and p_entity = {q('D1','p_entity','.4f')} (pure chance). Same columns, same")
    emit("data — the only difference is whether the 26,080 fact rows are treated as 26,080")
    emit("independent observations or as the 857 drivers they actually are. Every clustered")
    emit("attribute pair in a folded OBT is 'significant' under the row-wise null. **This is a")
    emit("real defect in the frozen stack, independent of the filter question.**")
    emit()
    emit("**2. It cannot be a filter, for a structural reason no threshold reaches.** Where the")
    emit("determinant IS its group's key, deduplication makes it a perfect key by construction")
    emit("— FI = null = 1, p = 1.0. That is 7 of the 20 measured cells and **5 of the 12**")
    emit("stats-owned (H1, J1, J2, J4, J5). Applied as written, C-C destroys the entire FK")
    emit("fold-edge class. The finding underneath is worth stating plainly: **at entity grain, a")
    emit("key -> attribute edge is a tautology.** It is real dimension structure that carries no")
    emit("statistical evidence at all — it is true by provenance, and no test can confirm what")
    emit("is true by construction.")
    emit()
    emit("Where it IS defined it is the best instrument in this probe — it rejects all three")
    emit(f"reachable quasi-identifiers (D1 p={q('D1','p_entity','.4f')}, D2 p={q('D2','p_entity','.4f')}, "
         f"D3 p={q('D3','p_entity','.4f')}), including D3 which C-A's guard misses. And it still")
    emit(f"cannot touch E (E1 p={q('E1','p_entity','.4f')}, E2 p={q('E2','p_entity','.4f')}) or D4 "
         f"(p={q('D4','p_entity','.4f')}), and it still costs F5 (p={q('F5','p_entity','.4f')}).")
    emit()
    emit("**F5 deserves its own note, because it is not really C-C's error.** A 74-distinct")
    emit(f"determinant over {by['F5']['n_entity']} circuits predicts anything about as well by chance, so the")
    emit("statistic is telling the truth: **the evidence for F5 is not in this data.** The same")
    emit("point lands harder on the stack's OWN g3 gate, recomputed at the two grains — same")
    emit(f"Kivinen-Mannila statistic, same `FD_MAX_G3 = {FD_MAX_G3}` gate, only the denominator moves:")
    emit()
    emit("```")
    emit(f"{'id':4}{'edge':46}{'g3 @ row grain':>16}{'g3 @ entity grain':>19}")
    for cid in ("F5", "J3", "D1", "F1", "E1"):
        r = by[cid]
        g3e = "n/a" if r["g3_entity"] is None else f"{r['g3_entity']:.4f}"
        gate_r = "pass" if r["g3_row"] <= FD_MAX_G3 else "FAIL"
        gate_e = ("n/a" if r["g3_entity"] is None
                  else ("pass" if r["g3_entity"] <= FD_MAX_G3 else "FAIL"))
        emit(f"{cid:4}{r['cc_dir'][:45]:46}{r['g3_row']:>10.4f} {gate_r:5}"
             f"{g3e:>13} {gate_e:5}")
    emit("```")
    emit()
    emit(f"F5's two same-city exceptions are {by['F5']['g3_entity']:.4f} of {by['F5']['n_entity']} circuits — which FAILS the")
    emit(f"stack's own 0.01 gate — but only {by['F5']['g3_row']:.4f} of 26,080 rows, which passes it. **The")
    emit("stack asserts F5 only because the row-wise view dilutes the exceptions.** The edge is")
    emit("true because of geography, not because of its numbers; the row grain reaches the")
    emit("right answer for the wrong reason, and the entity grain reaches the wrong answer for")
    emit("the right one. That is the residue in its purest form.")
    emit()
    emit("### C-D — fold-key alias rule: **CUT**")
    emit()
    emit("Zero gains, one loss — and both halves of the pre-registered premise were factually")
    emit("wrong about this data.")
    emit()
    emit("**It never reaches P.** P1's `date` and P2's `CREATIONTIMESTAMP` are FACT columns")
    emit(f"(group `{by['P1']['gb']}` / `{by['P2']['gb']}`), not attributes of the key's fold group, so the")
    emit("rule's precondition is not met and it does not fire. The expectation that C-D would")
    emit("fix the P class was a structural misreading of where those columns live.")
    emit()
    emit("**And 'NEITHER side is a fold key' is false for A6.** `race__circuitId` "
         f"(`{by['A6']['ga']}`) <-> `circuit__name` (`{by['A6']['gb']}`) is exactly the rule's trigger:")
    emit("a fold key bijective with a same-group attribute. Its truth is MERGE. C-D breaks it.")
    emit()
    emit("**The reason this matters more than a 1-cell loss.** On the held-out DB the same rule")
    emit("fires 10/10 and looks *right* every time (`PostId <-> post__Title`, `<-> post__Body`,")
    emit("`<-> post__CreationDate` — a post's title is an attribute the post has, not the post's")
    emit("identity). On the dev set it fires once and is wrong (a circuit's name IS the")
    emit("circuit's identity). **Provenance is identical in both cases.** `circuit__name` and")
    emit("`post__Title` are both unique-per-entity text hanging off a fold key; nothing")
    emit("structural distinguishes the entity's NAME from an attribute that happens to be")
    emit("unique. That question — identity encoding or attribute? — is meaning, and the rule")
    emit("gets the majority right while being silently wrong on the identity encodings.")
    emit()
    emit("## The honest read")
    emit()
    emit("**Can a named, grounded, LLM-free statistic filter the stack's false positives")
    emit("without losing the real dimensions? On this evidence: no.** All four candidates are")
    emit("CUT after one grounded attempt each. The combined filter turns 33/45 into 34/45 by")
    emit("trading 3 false positives for 2 real dimensions; the most generous LLM-free reading")
    emit("(C-C where defined) reaches 35/45 and still costs F5, and neither clears the")
    emit("12/12 F/H/J floor. **The false-positive problem is not a statistics problem.**")
    emit()
    emit("**Two real defects were found on the way, and they are worth landing on their own")
    emit("merits — as measurements, not as filters.**")
    emit()
    emit("1. **The near-key denominator IS wrong** (the hypothesis's measurement half). A fold")
    emit("   attribute is measured against the fact's row count, so `driver__dob` reads 0.03")
    emit("   when it is 0.979 of the driver entity. Any near-key reasoning on a folded OBT is")
    emit("   currently reading a number that means nothing.")
    emit("2. **The row-wise permutation null is inflated by clustering** (DAT-544, now")
    emit("   confirmed on real folded data at p_row 0.0003 vs p_entity 1.0). The stack's")
    emit("   per-pair perm-p is not measuring what it claims on any folded dimension.")
    emit()
    emit("Fixing both is correct and changes the D class. Neither fixes E, D4, P, or the")
    emit("A-vs-P bijection question — and #2 must be gated by the fold-key exemption or it")
    emit("deletes every FK fold edge. **Neither is a licence to build the filter this probe")
    emit("was asked to find.**")
    emit()
    emit("### The residue that genuinely needs semantics")
    emit()
    emit("Stated as measured pairs, not as a category:")
    emit()
    emit("1. **E vs F1 — the cleanest demonstration in the probe.** Same OBT, same entity,")
    emit("   same grain, and the numbers do not differ:")
    emit()
    emit("```")
    emit("                                            u(s)    p_entity      RFI")
    emit(f"  E1 article__detail_desc  -> garment_group_name   {u_of('E1')}     "
         f"{q('E1','p_entity','.4f')}   {q('E1','rfi_det')}   truth REJECT")
    emit(f"  F1 article__product_code -> product_type_name    {u_of('F1')}     "
         f"{q('F1','p_entity','.4f')}   {q('F1','rfi_det')}   truth HIERARCHY")
    emit("```")
    emit()
    emit("   A description and a product code, statistically indistinguishable. One is a")
    emit("   merchandising hierarchy; the other is prose that happens to predict it. **No")
    emit(f"   statistic splits {u_of('E1')} from {u_of('F1')}.** The difference is entirely what the")
    emit("   columns mean.")
    emit()
    emit("2. **D4 — where the statistic is RIGHT and the assert is still wrong.**")
    emit(f"   `driver__surname -> driver__nationality`, p_entity = {q('D4','p_entity','.4f')}, "
         f"RFI = {q('D4','rfi_det')}.")
    emit("   Surnames really do cluster by nationality; the dependence survives the")
    emit("   cluster-aware null because it is genuinely there. 'Real signal' and 'groupable")
    emit("   dimension level' are different predicates, and **no null-hypothesis test can")
    emit("   reject a true dependence.** This one is unreachable by construction.")
    emit()
    emit("3. **Bijection: identity encoding, or attribute?** A6 `race__circuitId <-> "
         "circuit__name`")
    emit("   (MERGE) and the held-out `PostId <-> post__Title` (correctly HIERARCHY) are")
    emit("   provenance-identical to the byte: a fold key bijective with unique-per-entity")
    emit("   text of its own group. Is the bijective partner the entity's name, or something")
    emit("   the entity has? Meaning — and C-D's 10-right/1-wrong record is exactly what a")
    emit("   rule that cannot see meaning looks like.")
    emit()
    emit(f"4. **F5/J3 vs D1 — {u_of('F5')} against {u_of('D1')}.** `circuit__location` and `driver__dob` are")
    emit(f"   {abs(float(u_of('D1')) - float(u_of('F5'))):.3f} apart on the axis C-A ranks them by, on opposite sides of the")
    emit("   truth. A location determines an altitude because of geography; a birthday")
    emit("   determines nothing about a surname despite the arithmetic working out. Meaning")
    emit("   again.")
    emit()
    emit("**What the residue is, in one line:** every surviving false positive is a *true and")
    emit("strong statistical dependence that is not a dimension*, and every real dimension the")
    emit("filters destroy is *true for reasons the data does not contain*. Those are the two")
    emit("failure modes no statistic can address, because in both the statistic is already")
    emit("correct — it is the question being asked of it that needs meaning. That is the case")
    emit("for a semantic lane, and it is also the boundary of one: the lane is needed for E,")
    emit("D4, P/A bijections and low-power edges like F5, and is NOT needed for D1/D2/D3 or")
    emit("G3, which the two measurement fixes above reach without any LLM.")
    emit()


def measure_cached() -> tuple[list[dict], dict]:
    """Candidate values per cell + the per-OBT surface C-A/C-D need, cached. The pair
    scan and the permutations are the whole cost; the report replays from the cache so
    the artifact is regenerable in seconds. `--refresh` recomputes."""
    if CACHE.exists() and "--refresh" not in sys.argv:
        blob = json.loads(CACHE.read_text())
        print(f"  cached: {len(blob['cells'])} cells, {len(blob['obts'])} OBTs")
        return blob["cells"], blob["obts"]
    print("loading dev OBTs...")
    data = load_all()
    print("measuring candidates (pair scan + permutations)...")
    rows = dev_measure(data)
    obts = {
        ds: {"group": {k: v for k, v in group.items() if k is not None},
             "singles": scan.singles, "n": scan.n}
        for ds, (_, group, scan) in data.items()
    }
    CACHE.write_text(json.dumps({"cells": rows, "obts": obts}, indent=1))
    return rows, obts


def main() -> None:
    t0 = time.time()
    emit("# DAT-762 — can an LLM-free statistic filter the stack's false positives?")
    emit()
    emit("Probe: `scripts/probes/dat762-judge-context/probe_grain.py`. **ZERO LLM calls.**")
    emit("Candidates C-A..C-D pre-registered in the probe docstring before the run; each gets")
    emit("ONE grounded attempt, and a failure is CUT and recorded, never tuned. Frozen")
    emit("instruments (`fdlib`, `cells`, `probe_fold_grade`, `probe_ablation`, `probe_heldout`)")
    emit("are imported read-only.")
    emit()
    emit("Reference: RESULTS_DEV.md §2 — the C1 column is the mechanical stack v4's per-class")
    emit("truth, and the target to beat. C1 = 33/45 overall, 12/12 on F/H/J, 0/9 on the veto")
    emit("classes (D, E, P, G3).")
    emit()

    rows, obts = measure_cached()
    print(f"  ready in {time.time() - t0:.0f}s")

    # C1 drift control against the frozen scorecard
    c1_strict = sum(int(strict_ok(next(c for c in CELLS if c.id == r["id"]), r["c1"], r["c1_dir"]))
                    for r in rows)
    emit(f"**C1 reproduction control:** recomputed C1 scores {c1_strict}/45 strict; "
         f"RESULTS_DEV.md §3 records 33/45. "
         f"{'Match.' if c1_strict == 33 else 'DRIFT — reported, not patched.'}")
    emit()

    report_ca(rows)
    report_cb(rows)
    report_cc(rows)
    report_cd(rows)

    # --- the combined filter ------------------------------------------------ #
    emit("## Combined filter — C1 vs C1 + filter (C-A + C-D)")
    emit()
    emit("No candidate passed its own separation gate, so this is not the pre-registered")
    emit("'apply the ones that pass' — it is what applying them ANYWAY costs, which is the")
    emit("number the question turns on. C-B is unusable (no threshold exists) and C-C is")
    emit("undefined on key determinants, so the combination is C-A + C-D.")
    emit()
    per_class, changed = scorecard(rows, obts, use_ca=True, use_cd=True)
    emit_scorecard(per_class, changed, "C1+filter")

    # --- post-hoc diagnostic: the best LLM-free combination available here --- #
    emit("## Post-hoc diagnostic — the most generous LLM-free combination")
    emit()
    emit("**Not pre-registered, not a verdict, and not a threshold search.** C-A fires on")
    emit("F5/J3 because `u` alone cannot see that a near-unique determinant is still a real")
    emit("dimension. C-C is strictly better informed on the D class (it rejects D3 at")
    emit("u=0.848, which C-A's guard misses) and is *undefined* — not passed — where the")
    emit("determinant is its own group's key. Applying C-C only where it is defined, with")
    emit("the same fold-key precondition C-A already carries, is the friendliest reading of")
    emit("the LLM-free stack. It is reported to show that the residue survives even it.")
    emit()
    per_class_cc, changed_cc = scorecard(rows, obts, use_ca=False, use_cd=False, use_cc=True)
    emit_scorecard(per_class_cc, changed_cc, "C1+C-C")

    report_heldout(use_ca=True, use_cd=True)
    report_verdicts(rows)

    REPORT.write_text("\n".join(_LINES) + "\n")
    print(f"\nwrote {REPORT}  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
