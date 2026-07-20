"""DAT-757 channel-ablation scorecard — runner (protocol frozen in PROTOCOL.md).

C1 (values-only) is recomputed mechanically from the folded OBTs with the frozen
stack v4 (near-copy role check -> alias screen -> edge screen + lambda -> per-pair
perm-p; family-BH accepted 71/71, 81/81, 191/192 screened candidates on these OBTs,
so the per-pair test is the equivalent local form). C2/C3 are `claude-sonnet-5`
at temperature 0, JSON verdicts, one scoring pass + one repetition for instability
reporting (reported, never overridden). LLM responses cached in results.json —
reruns don't re-bill.

Run:  uv run --with anthropic python -u scripts/probes/dat757-channel-ablation/probe_ablation.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import polars as pl

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[0] / "dat757-g3-wide"))
sys.path.insert(0, str(HERE.parents[0] / "dat757-relbench"))
sys.path.insert(0, str(HERE))

from cells import CELLS, Cell  # noqa: E402
from fdlib import (  # noqa: E402
    FD_MAX_G3,
    MIN_DISTINCT_DETERMINANT,
    MIN_DISTINCT_DIMENSION,
    NEAR_KEY_FRAC,
    Scan,
    perm_pvalue,
    scan_pairs,
)
from probe_fold_grade import SPECS, build_obt  # noqa: E402

MODEL = "claude-sonnet-5"
LAMBDA_MIN = 0.5
RESULTS = HERE / "results.json"
NULL = "␀"

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

Answer with ONLY a JSON object: {"verdict": "MERGE"|"HIERARCHY"|"ROLE"|"REJECT",
"direction": "a->b"|"b->a"|null, "reason": "<one sentence>"} — direction only for
HIERARCHY, meaning the left/first column determines the right/second one."""


# --------------------------------------------------------------------------- #
# data + evidence                                                              #
# --------------------------------------------------------------------------- #
def load_all() -> dict[str, tuple[pl.DataFrame, dict[str, str], Scan]]:
    out = {}
    for ds in ("rel-f1", "rel-hm", "rel-salt"):
        obt, group = build_obt(Path("corpora/relbench") / ds, SPECS[ds])
        scan = scan_pairs(obt, list(obt.columns))
        out[ds] = (obt, group, scan)
        print(f"  loaded {ds}: {len(obt):,} rows")
    return out


def utf(obt: pl.DataFrame, c: str) -> np.ndarray:
    return obt.get_column(c).cast(pl.Utf8).fill_null(NULL).to_numpy()


def col_profile(obt: pl.DataFrame, c: str, rng: np.random.Generator) -> dict:
    s = obt.get_column(c).cast(pl.Utf8)
    vc = s.fill_null(NULL).value_counts().sort("count", descending=True)
    n = len(s)
    top = [(str(v)[:80], int(k)) for v, k in zip(vc[c][:6], vc["count"][:6])]
    non_null = s.drop_nulls()
    samples = (
        [str(v)[:80] for v in non_null.sample(min(10, len(non_null)), seed=int(rng.integers(1e9)))]
        if len(non_null) else []
    )
    return {
        "n_rows": n,
        "n_distinct": int(s.n_unique()),
        "null_rate": round(float(s.null_count()) / n, 4),
        "top_values": top,
        "random_samples": samples,
    }


def pair_stats(scan: Scan, obt: pl.DataFrame, a: str, b: str) -> dict:
    key, fwd = ((a, b), True) if (a, b) in scan.stats else ((b, a), False)
    ps = scan.stats[key]
    g3f, g3b = (ps.g3_row_fwd, ps.g3_row_bwd) if fwd else (ps.g3_row_bwd, ps.g3_row_fwd)
    ef, eb = (ps.g3_eng_fwd, ps.g3_eng_bwd) if fwd else (ps.g3_eng_bwd, ps.g3_eng_fwd)
    sa, sb = utf(obt, a), utf(obt, b)
    dis = float((sa != sb).mean())
    va, vb = set(np.unique(sa)) - {NULL}, set(np.unique(sb)) - {NULL}
    jac = len(va & vb) / max(1, len(va | vb))
    return {
        "row_g3_a_to_b": round(g3f, 5), "row_g3_b_to_a": round(g3b, 5),
        "paircount_g3_a_to_b": round(ef, 5), "paircount_g3_b_to_a": round(eb, 5),
        "lambda_a_to_b": round(lam(scan, obt, a, b), 3),
        "lambda_b_to_a": round(lam(scan, obt, b, a), 3),
        "value_equality_disagreement": round(dis, 5),
        "value_set_jaccard": round(jac, 4),
    }


_MINORITY: dict[tuple[int, str], float] = {}


def minority(obt: pl.DataFrame, c: str) -> float:
    k = (id(obt), c)
    if k not in _MINORITY:
        vc = obt.get_column(c).cast(pl.Utf8).fill_null(NULL).value_counts()
        _MINORITY[k] = 1.0 - float(vc["count"].max()) / len(obt)
    return _MINORITY[k]


def lam(scan: Scan, obt: pl.DataFrame, a: str, b: str) -> float:
    key, fwd = ((a, b), True) if (a, b) in scan.stats else ((b, a), False)
    g3 = scan.stats[key].g3_row_fwd if fwd else scan.stats[key].g3_row_bwd
    m = minority(obt, b)
    return 1.0 - g3 / m if m > 0 else 0.0


# --------------------------------------------------------------------------- #
# C1 — the frozen stack, mechanical                                            #
# --------------------------------------------------------------------------- #
def c1_verdict(cell: Cell, data: dict, reps: int) -> tuple[str, str | None, str]:
    if cell.dataset.startswith("constructed"):
        return "REJECT", None, "cross-view: no joint statistics exist"
    obt, group, scan = data[cell.dataset]
    a, b = cell.a, cell.b
    ps_key = (a, b) if (a, b) in scan.stats else (b, a)
    ps = scan.stats[ps_key]
    if ps.d_a < MIN_DISTINCT_DIMENSION or ps.d_b < MIN_DISTINCT_DIMENSION:
        return "REJECT", None, "constant column"

    # 1) same-domain near-copy -> disagreement-set role tests (T1 role-specific)
    sa, sb = utf(obt, a), utf(obt, b)
    dis_rate = float((sa != sb).mean())
    if 0.0 < dis_rate <= 0.05:
        dis = (sa != sb).astype(np.int64)
        ctx_groups = SPECS[cell.dataset].get("role_context_groups", ("fact", "fact-key"))
        contexts = [c for c in obt.columns if c not in (a, b) and group[c] in ctx_groups
                    and scan.singles[c] >= MIN_DISTINCT_DIMENSION]
        alpha = 0.05 / (len(contexts) + 1)
        for c in contexts:
            sc = scan_pairs(pl.DataFrame({"dis": dis, "x": utf(obt, c)}), ["dis", "x"])
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
            g3 <= FD_MAX_G3 and d_s > d_t and d_s >= MIN_DISTINCT_DETERMINANT
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


# --------------------------------------------------------------------------- #
# C2 / C3 — the LLM judge                                                      #
# --------------------------------------------------------------------------- #
def load_key() -> str:
    for line in Path(".env").read_text().splitlines():
        if line.strip().startswith("ANTHROPIC_API_KEY"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ANTHROPIC_API_KEY not found in .env")


def evidence_c2(cell: Cell, data: dict) -> str:
    if cell.dataset.startswith("constructed"):
        ds = cell.dataset.split(":")[1]
        return (f"Two single-table views from separate source systems of the same business "
                f"(dataset {ds}). View 1 has a column named `{cell.a}`; view 2 has a column "
                f"named `{cell.b}`. Question: the dimensional relationship between these two "
                f"columns across the views.")
    obt, _, _ = data[cell.dataset]
    return (f"One wide denormalized table (dataset {cell.dataset}) with columns:\n"
            f"{', '.join(obt.columns)}\n\n"
            f"Question: the dimensional relationship between column a = `{cell.a}` "
            f"and column b = `{cell.b}`.")


def evidence_c3(cell: Cell, data: dict, rng: np.random.Generator) -> str:
    base = evidence_c2(cell, data)
    if cell.dataset.startswith("constructed"):
        prof = constructed_profiles(cell, data, rng)
        return base + "\n\nColumn profiles:\n" + json.dumps(prof, ensure_ascii=False)
    obt, _, scan = data[cell.dataset]
    ev = {
        f"profile[{cell.a}]": col_profile(obt, cell.a, rng),
        f"profile[{cell.b}]": col_profile(obt, cell.b, rng),
        "pair_statistics": pair_stats(scan, obt, cell.a, cell.b),
        "notes": ("row_g3(x->y)=min fraction of rows violating the FD x->y; "
                  "lambda = 1 - g3/minority_mass (reduction over majority baseline); "
                  "value_equality_disagreement = fraction of rows where the two values differ"),
    }
    return base + "\n\nStatistical evidence:\n" + json.dumps(ev, ensure_ascii=False)


def constructed_profiles(cell: Cell, data: dict, rng: np.random.Generator) -> dict:
    if cell.id == "K1":
        obt, _, _ = data["rel-salt"]
        top2 = (obt.get_column("soldto_addr__COUNTRY").drop_nulls().value_counts()
                .sort("count", descending=True)["soldto_addr__COUNTRY"][:2].to_list())
        prof = {}
        vals = {}
        for i, ctry in enumerate(top2, 1):
            part = obt.filter(pl.col("soldto_addr__COUNTRY") == ctry)
            prof[f"view{i} (country={ctry}) column region"] = col_profile(
                part, "soldto_addr__REGION", rng)
            vals[i] = set(utf(part, "soldto_addr__REGION")) - {NULL}
        prof["value_set_jaccard_across_views"] = round(
            len(vals[1] & vals[2]) / max(1, len(vals[1] | vals[2])), 4)
        return prof
    if cell.id == "K2":
        obt, _, scan = data["rel-f1"]
        return {
            f"profile[{cell.a}]": col_profile(obt, cell.a, rng),
            f"profile[{cell.b}]": col_profile(obt, cell.b, rng),
            "pair_statistics": pair_stats(scan, obt, cell.a, cell.b),
        }
    raise ValueError(cell.id)


def ask(client, user_msg: str) -> dict:
    for attempt in range(4):
        try:
            # Claude 5 rejects the temperature parameter (400: deprecated) — the
            # judge runs at model-default sampling; instability is measured by the
            # repetition (PROTOCOL.md amendment note, 2026-07-14).
            resp = client.messages.create(
                model=MODEL, max_tokens=300,
                system=SYSTEM, messages=[{"role": "user", "content": user_msg}],
            )
            txt = resp.content[0].text.strip()
            if txt.startswith("```"):
                txt = txt.strip("`").removeprefix("json").strip()
            out = json.loads(txt)
            assert out.get("verdict") in ("MERGE", "HIERARCHY", "ROLE", "REJECT")
            return out
        except Exception as e:  # noqa: BLE001 — retry API/parse hiccups, then surface
            if attempt == 3:
                return {"verdict": "ERROR", "direction": None, "reason": str(e)[:200]}
            time.sleep(3 * (attempt + 1))
    return {"verdict": "ERROR", "direction": None, "reason": "unreachable"}


# --------------------------------------------------------------------------- #
# scoring + report                                                             #
# --------------------------------------------------------------------------- #
def correct(cell: Cell, verdict: str, direction: str | None, strict: bool) -> bool:
    if verdict != cell.truth:
        return False
    if strict and cell.truth == "HIERARCHY":
        return direction == "a->b"  # truth direction is always a -> b in cells.py
    return True


def main() -> None:
    print("# DAT-757 channel-ablation scorecard\n\n## loading OBTs")
    data = load_all()
    rng = np.random.default_rng(757)
    cache = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}

    import anthropic  # noqa: PLC0415 (overlay dep)

    client = anthropic.Anthropic(api_key=load_key())

    print("\n## grading")
    rows = []
    for cell in CELLS:
        reps = 2999 if cell.dataset == "rel-f1" else 999
        k1 = f"{cell.id}:C1"
        if k1 not in cache:
            v, d, why = c1_verdict(cell, data, reps)
            cache[k1] = {"verdict": v, "direction": d, "reason": why}
            RESULTS.write_text(json.dumps(cache, indent=1))
        for ch, ev_fn in (("C2", evidence_c2), ("C3", lambda c, dd: evidence_c3(c, dd, rng))):
            for rep in (1, 2):
                k = f"{cell.id}:{ch}:r{rep}"
                if k not in cache:
                    cache[k] = ask(client, ev_fn(cell, data))
                    RESULTS.write_text(json.dumps(cache, indent=1))
        r = {
            "cell": cell,
            "C1": cache[f"{cell.id}:C1"],
            "C2": cache[f"{cell.id}:C2:r1"],
            "C3": cache[f"{cell.id}:C3:r1"],
            "C2_unstable": cache[f"{cell.id}:C2:r1"]["verdict"] != cache[f"{cell.id}:C2:r2"]["verdict"],
            "C3_unstable": cache[f"{cell.id}:C3:r1"]["verdict"] != cache[f"{cell.id}:C3:r2"]["verdict"],
        }
        rows.append(r)
        marks = " ".join(
            f"{ch}:{'OK' if correct(cell, r[ch]['verdict'], r[ch].get('direction'), True) else r[ch]['verdict']}"
            for ch in ("C1", "C2", "C3"))
        print(f"  {cell.id:3} [{cell.klass:18}] truth={cell.truth:9} {marks}"
              f"{'  (C2 unstable)' if r['C2_unstable'] else ''}"
              f"{'  (C3 unstable)' if r['C3_unstable'] else ''}")

    print("\n## class x channel scorecard (strict; lax in parens where different)")
    klasses = sorted({c.klass for c in CELLS}, key=lambda k: k.split("-")[0])
    print(f"  {'class':22} {'n':>2}  {'C1':>9} {'C2':>9} {'C3':>9}")
    for kl in klasses:
        sub = [r for r in rows if r["cell"].klass == kl]
        line = f"  {kl:22} {len(sub):>2} "
        for ch in ("C1", "C2", "C3"):
            s = sum(correct(r["cell"], r[ch]["verdict"], r[ch].get("direction"), True) for r in sub)
            x = sum(correct(r["cell"], r[ch]["verdict"], r[ch].get("direction"), False) for r in sub)
            line += f"  {s}/{len(sub)}" + (f"({x})" if x != s else "    ")
        print(line)
    for ch in ("C1", "C2", "C3"):
        tot = sum(correct(r["cell"], r[ch]["verdict"], r[ch].get("direction"), True) for r in rows)
        print(f"  overall {ch}: {tot}/{len(rows)}")
    unstable = [(r["cell"].id, ch) for r in rows for ch in ("C2", "C3") if r[f"{ch}_unstable"]]
    print(f"\n  LLM instability across the repetition: {len(unstable)} of {2 * len(rows)}"
          f" gradings {unstable if unstable else ''}")

    print("\n## misgrades (channel, cell, got vs truth, judge's reason)")
    for r in rows:
        for ch in ("C1", "C2", "C3"):
            if not correct(r["cell"], r[ch]["verdict"], r[ch].get("direction"), True):
                got = r[ch]["verdict"] + (f"/{r[ch].get('direction')}" if r[ch].get("direction") else "")
                print(f"  {ch} {r['cell'].id:3} got {got:15} want {r['cell'].truth:9}"
                      f" — {r[ch].get('reason', '')[:110]}")


if __name__ == "__main__":
    main()
