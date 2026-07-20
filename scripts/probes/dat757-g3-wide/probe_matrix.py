"""DAT-757 dimension-universe matrix — families F1-F14 x structural regimes, one OBT.

CLAIM UNDER TEST (to refute)
----------------------------
"The engine's g3 pipeline (alias union -> determinant guards -> directed edges ->
transitive reduction -> chains, hierarchies/processor.py) correctly recovers folded
dimensions across the WHOLE universe of dimension families — not just the account/ID
archetypes probed so far — once DAT-757 widens the candidate set."

THE ATTACK
----------
Every family gets its diagnostic regimes (the ~65-cell matrix approved 2026-07-14):
heavy tails under the near-key guard, SCD-dirty true FDs (pair-count inflation), null
contamination (left-join misses), near-duplicate role-playing columns, measure->band
derivation, exact-but-semantically-void FDs (ids/text), the unguarded alias path
(independent full keys), Zipf frequencies on true chains, ragged hierarchies.

Scoring: per-cell decisions under three gates (eng = engine today; row = classic row-g3
swapped in; row+rfi = row-g3 AND RFI reliability) vs the planted expectation, with a
`lane` column naming the fix when NO structural gate can be correct (null-policy /
additivity / abstain / concept). Then the ASSEMBLED pipeline per gate: true chains
recovered, spurious structures asserted.

Design choices (logged, not silent): the pipeline pass runs on the clean set + attack
columns; deliberate variant columns (dirty/nully/role-duplicate copies) are scored at
pair level only, so chain recovery isn't contaminated by planted near-copies. DATE
routing (F2), cross-fact concept identity (F14), tag fan-out grain (F13), and smart-code
segment parsing (F12) are design/e2e/concept-lane cells — logged as untestable in pure
math, not scored as passes.

Run:  uv run python scripts/probes/dat757-g3-wide/probe_matrix.py     (repo root, ~10 s)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from fdlib import (  # noqa: E402
    Scan,
    _row_g3,
    alias_decision,
    assemble,
    codes_of,
    edge_decision,
    scan_pairs,
)

RNG = np.random.default_rng(20260714)
N = 20_000
N_B = 12_000
GATES = ["eng", "row", "row+rfi", "mixed"]


# --------------------------------------------------------------------------- #
# fixtures                                                                     #
# --------------------------------------------------------------------------- #
def build_fact_a(rng: np.random.Generator | None = None, n: int = N) -> pl.DataFrame:
    rng = rng if rng is not None else RNG
    # F1 geo: exact nested chain zip(600)->city(120)->state(24)->country(8)->region(4)
    zip_ = rng.integers(0, 600, n)
    city = zip_ // 5
    state = city // 5
    country = state // 3
    region = country // 2
    # F1 variants: SCD dirt (3 rows) + left-join-miss nulls (10% / 40%)
    state_scd = state.copy()
    dirty_idx = rng.choice(n, 3, replace=False)
    state_scd[dirty_idx] = (state_scd[dirty_idx] + 1) % 24
    null10 = rng.random(n) < 0.10
    null40 = rng.random(n) < 0.40

    # F2 temporal: month48 -> {year(4), moy(12) -> quarter(4)}; date_col routed by type
    month48 = rng.integers(0, 48, n)
    year = month48 // 12
    moy = month48 % 12
    quarter = moy // 3

    # F3 product under Zipf frequencies: sku(2000)->product(400)->subcat(40)->cat(8)
    ranks = np.arange(1, 2001)
    p = (1.0 / ranks**1.05) / (1.0 / ranks**1.05).sum()
    sku = rng.choice(2000, n, p=p)
    product = sku // 5
    subcat = product // 10
    cat = subcat // 5

    # F4 org: emp(300)->mgr(50)->dept(10); ragged team(60) with 25% nulls
    emp = rng.integers(0, 300, n)
    mgr = emp // 6
    dept = mgr // 5
    team = emp // 5
    team_null = rng.random(n) < 0.25

    # F5/F12 account: acct(30)->acct_type(4); name + smart gl_code both 1:1 with acct
    acct = rng.integers(0, 30, n)
    acct_type = acct // 8
    acct_name = np.array([f"ACCT_{v:03d}" for v in acct])
    gl_code = np.array([f"{t}xx-{v:03d}" for t, v in zip(acct_type, acct)])

    # F6 role-playing: bill_city + ship variants at 5% / 0.1% / 1-row disagreement
    bill_city = rng.integers(0, 120, n)
    ship_city_lo = bill_city.copy()
    lo_idx = rng.random(n) < 0.05
    ship_city_lo[lo_idx] = rng.integers(0, 120, int(lo_idx.sum()))
    ship_city_hi = bill_city.copy()
    hi_idx = rng.choice(n, 20, replace=False)
    ship_city_hi[hi_idx] = rng.integers(0, 120, 20)
    ship_city_dup = bill_city.copy()
    ship_city_dup[int(rng.integers(0, n))] = 119 - ship_city_dup[int(rng.integers(0, n))]

    # F7 enums: true derived FD 5->3; independent same-domain; boolean flags + dup
    ord_status = rng.integers(0, 5, n)
    pay_status_true = ord_status // 2
    pay_status_ind = rng.integers(0, 5, n)
    f1, f2, f3, f4 = (rng.integers(0, 2, n) for _ in range(4))
    f_dup = f1.copy()

    # F8 qualifiers
    currency = rng.choice(3, n, p=[0.6, 0.25, 0.15])
    scenario = rng.integers(0, 3, n)

    # F9 band: heavy-repeat revenue (card ~0.35) + exact quartile tier
    popular = np.round(rng.lognormal(4.0, 0.8, 800), 2)
    is_pop = rng.random(n) < 0.7
    revenue = np.where(is_pop, rng.choice(popular, n), np.round(rng.lognormal(4.0, 0.8, n), 4))
    tier = np.digitize(revenue, np.quantile(revenue, [0.25, 0.5, 0.75]))

    # F10 numeric boundary: store dim; independent rating; rate with disjoint ranges
    store = rng.integers(0, 96, n)
    store_region = store // 12
    rating = rng.integers(0, 5, n)
    base = np.array([1.0, 0.92, 1.25])[currency]
    rate = np.round(np.where(currency == 0, 1.0, base + rng.normal(0, 0.008, n)), 4)

    # F11 ids & text
    line_key = np.arange(n)
    uuid_col = rng.permutation(n)
    doc_no = np.arange(n).astype(np.int64)  # 65% unique + 10 bulk codes (thread 1)
    bulk_idx = rng.choice(n, int(0.35 * n), replace=False)
    doc_no[bulk_idx] = -rng.integers(1, 11, len(bulk_idx))
    templates = [f"tmpl {t}" for t in range(10)]
    desc = np.array([templates[rng.integers(0, 10)] if rng.random() < 0.6 else f"txn {i}" for i in range(n)])
    names = [f"pop name {t}" for t in range(20)]
    name_col = np.array([names[rng.integers(0, 20)] if rng.random() < 0.3 else f"person {i}" for i in range(n)])
    entry_key = rng.integers(0, 10_000, n)
    desc_entry = np.array([f"entry text {v}" for v in entry_key])

    # F13 multi-valued tags (comma lists over 10 tags)
    tagset = np.array(["alpha", "beta", "gamma", "delta", "eps", "zeta", "eta", "theta", "iota", "kappa"])
    tags = np.array([",".join(sorted(rng.choice(tagset, rng.integers(1, 4), replace=False))) for _ in range(n)])

    df = pl.DataFrame(
        {
            "zip": zip_, "city": city, "state": state, "country": country, "region": region,
            "state_scd": state_scd, "state_nul10": state, "state_nul40": state,
            "month48": month48, "year": year, "moy": moy, "quarter": quarter,
            "sku": sku, "product": product, "subcat": subcat, "cat": cat,
            "emp": emp, "mgr": mgr, "dept": dept, "team": team,
            "acct": acct, "acct_name": acct_name, "gl_code": gl_code, "acct_type": acct_type,
            "bill_city": bill_city, "ship_city_lo": ship_city_lo,
            "ship_city_hi": ship_city_hi, "ship_city_dup": ship_city_dup,
            "ord_status": ord_status, "pay_status_true": pay_status_true,
            "pay_status_ind": pay_status_ind,
            "f1": f1, "f2": f2, "f3": f3, "f4": f4, "f_dup": f_dup,
            "currency": currency, "scenario": scenario,
            "revenue": revenue, "tier": tier,
            "store": store, "store_region": store_region, "rating": rating, "rate": rate,
            "line_key": line_key, "uuid_col": uuid_col, "doc_no": doc_no,
            "desc": desc, "name_col": name_col,
            "entry_key": entry_key, "desc_entry": desc_entry,
            "tags": tags,
        }
    )
    nul10 = pl.Series(null10)
    nul40 = pl.Series(null40)
    tnul = pl.Series(team_null)
    return df.with_columns(
        pl.when(nul10).then(None).otherwise(pl.col("state_nul10")).alias("state_nul10"),
        pl.when(nul40).then(None).otherwise(pl.col("state_nul40")).alias("state_nul40"),
        pl.when(tnul).then(None).otherwise(pl.col("team")).alias("team"),
    )


def build_fact_b(rng: np.random.Generator | None = None, n: int = N_B) -> pl.DataFrame:
    rng = rng if rng is not None else RNG
    city_b = rng.integers(0, 120, n)
    state_b = city_b // 5
    region_b = state_b // 6
    city_eu = rng.integers(0, 60, n)
    eu_names = np.array(["DACH", "Nordics", "Benelux", "France", "Iberia", "Italy"])
    region_eu = eu_names[city_eu // 10]
    subcat_b = rng.integers(0, 40, n)
    cat_b = subcat_b // 5
    status_b = rng.integers(0, 5, n)  # same domain as fact_a ord_status (false friend)
    return pl.DataFrame(
        {"city_b": city_b, "state_b": state_b, "region_b": region_b,
         "city_eu": city_eu, "region_eu": region_eu,
         "subcat_b": subcat_b, "cat_b": cat_b, "status_b": status_b}
    )


# --------------------------------------------------------------------------- #
# the cell matrix                                                              #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Cell:
    id: str
    family: str
    kind: str  # edge | alias
    a: str
    b: str
    expect: bool  # edge: assert a->b ; alias: merge a<->b
    lane: str  # structural | null-policy | additivity | abstain | concept
    note: str
    fact: str = "a"


CELLS: list[Cell] = [
    # F1 geographic
    Cell("f1-zip-city", "F1 geo", "edge", "zip", "city", True, "structural", "deep-chain link"),
    Cell("f1-city-state", "F1 geo", "edge", "city", "state", True, "structural", "deep-chain link"),
    Cell("f1-country-region", "F1 geo", "edge", "country", "region", True, "structural", "coarse link"),
    Cell("f1-scd-dirty", "F1 geo", "edge", "city", "state_scd", True, "structural",
         "TRUE FD, 3 dirty rows — pair-count FN trap"),
    Cell("f1-null10", "F1 geo", "edge", "city", "state_nul10", True, "null-policy", "10% join-miss nulls"),
    Cell("f1-null40", "F1 geo", "edge", "city", "state_nul40", True, "null-policy", "40% join-miss nulls"),
    # F2 temporal-folded
    Cell("f2-month-year", "F2 time", "edge", "month48", "year", True, "structural", "int year retained"),
    Cell("f2-moy-quarter", "F2 time", "edge", "moy", "quarter", True, "structural", "month->quarter"),
    # F3 product (Zipf)
    Cell("f3-sku-product", "F3 product", "edge", "sku", "product", True, "structural", "Zipf freq on true chain"),
    Cell("f3-subcat-cat", "F3 product", "edge", "subcat", "cat", True, "structural", "taxonomy link"),
    # F4 org
    Cell("f4-emp-mgr", "F4 org", "edge", "emp", "mgr", True, "structural", "recursive-as-chain"),
    Cell("f4-mgr-dept", "F4 org", "edge", "mgr", "dept", True, "structural", ""),
    Cell("f4-ragged-team", "F4 org", "edge", "emp", "team", True, "null-policy", "ragged: 25% null team"),
    Cell("f4-team-dept", "F4 org", "edge", "team", "dept", True, "null-policy", "null determinant"),
    # F5 account
    Cell("f5-acct-type", "F5 account", "edge", "acct", "acct_type", True, "structural", ""),
    Cell("f5-name-alias", "F5 account", "alias", "acct", "acct_name", True, "structural", "true code<->name 1:1"),
    # F6 role-playing
    Cell("f6-role-lo", "F6 roles", "alias", "bill_city", "ship_city_lo", False, "structural", "5% disagreement"),
    Cell("f6-role-hi", "F6 roles", "alias", "bill_city", "ship_city_hi", False, "structural", "0.1% disagreement"),
    Cell("f6-role-dup", "F6 roles", "alias", "bill_city", "ship_city_dup", False, "concept",
         "near-exact duplicate roles — no statistical separation exists"),
    # F7 status/enum/flags
    Cell("f7-enum-fd", "F7 enums", "edge", "ord_status", "pay_status_true", True, "structural", "derived 5->3"),
    Cell("f7-false-friend", "F7 enums", "alias", "ord_status", "pay_status_ind", False, "structural",
         "same domain, independent"),
    Cell("f7-bool-alias", "F7 enums", "alias", "f1", "f_dup", True, "structural", "true boolean 1:1"),
    Cell("f7-bool-indep", "F7 enums", "alias", "f1", "f2", False, "structural", ""),
    # F8 qualifiers
    Cell("f8-qual-ctrl", "F8 qualifier", "edge", "currency", "scenario", False, "structural", "control"),
    # F9 banded
    Cell("f9-band", "F9 band", "edge", "revenue", "tier", False, "additivity",
         "EXACT derived FD from a mid-card measure — only the dim/measure gate can reject"),
    # F10 numeric boundary
    Cell("f10-store", "F10 numeric", "edge", "store", "store_region", True, "structural",
         "folded numeric dim retained"),
    Cell("f10-rate-currency", "F10 numeric", "edge", "rate", "currency", False, "additivity",
         "continuous measure exactly determines its qualifier"),
    Cell("f10-rating-ctrl", "F10 numeric", "edge", "cat", "rating", False, "structural", "control"),
    # F11 identifiers & text
    Cell("f11-id-status", "F11 ids/text", "edge", "doc_no", "ord_status", False, "structural",
         "heavy-tail id (card .65) — thread-1 hole"),
    Cell("f11-id-geo", "F11 ids/text", "edge", "doc_no", "country", False, "structural",
         "id inserts itself above the geo chain"),
    Cell("f11-text-desc", "F11 ids/text", "edge", "desc", "ord_status", False, "structural",
         "10 heavy templates + unique tail"),
    Cell("f11-text-name", "F11 ids/text", "edge", "name_col", "region", False, "structural",
         "Zipf person names (card .70)"),
    Cell("f11-id-uniform", "F11 ids/text", "edge", "entry_key", "region", False, "structural",
         "uniform mid-card id — safe control"),
    Cell("f11-key-alias", "F11 ids/text", "alias", "line_key", "uuid_col", False, "structural",
         "two independent FULL KEYS — the unguarded alias path"),
    Cell("f11-void-alias", "F11 ids/text", "alias", "entry_key", "desc_entry", False, "abstain",
         "statistically TRUE 1:1 (id<->text) — semantically void as a dimension"),
    # F12 smart codes (structural half; segment parsing = concept lane, logged)
    Cell("f12-code-alias", "F12 codes", "alias", "acct", "gl_code", True, "structural",
         "gl_code IS the account — merge correct; parsing stays a teach"),
    # F13 multi-valued (structural control; fan-out grain = e2e lane, logged)
    Cell("f13-tags-ctrl", "F13 tags", "edge", "tags", "cat", False, "structural", "control"),
    # F14 cross-fact structural prerequisites (identity itself = concept lane, logged)
    Cell("f14-city-state", "F14 x-fact", "edge", "city_b", "state_b", True, "structural", "fact_b chain", "b"),
    Cell("f14-eu-region", "F14 x-fact", "edge", "city_eu", "region_eu", True, "structural",
         "disjoint-value domain, per-fact recovery", "b"),
    Cell("f14-grain", "F14 x-fact", "edge", "subcat_b", "cat_b", True, "structural",
         "coarser-grain fold of fact_a's taxonomy", "b"),
]

LOGGED_LANES = [
    ("F2", "DATE/TIMESTAMP columns route to the temporal lane by TYPE (DAT-730) — design assertion, no math to score"),
    ("F7/F14", "cross-fact false friend (status vs status_b): per-view g3 never compares them; the risk lives entirely in the identity/concept stage"),
    ("F12", "smart-code SEGMENT parsing (gl_code -> type segment): teach-lane per DAT-620 (confident-mislabel risk), never a structural assert"),
    ("F13", "tag fan-out grain verification: enriched-view row-count check, e2e-only (is_grain_verified)"),
    ("F14", "folded<->referenced same-concept: needs the 2b partial-inline generator feature (scoped, not built)"),
    ("F14", "disjoint-value / grain-mismatch cross-fact IDENTITY: concept-lane (structural prerequisite scored above)"),
]

# planted truth for the assembled-pipeline pass (fact_a, clean set + attackers)
PIPE_COLS = [
    "zip", "city", "state", "country", "region",
    "month48", "year", "moy", "quarter",
    "sku", "product", "subcat", "cat",
    "emp", "mgr", "dept",
    "acct", "acct_name", "gl_code", "acct_type",
    "store", "store_region", "rating",
    "ord_status", "pay_status_true", "pay_status_ind",
    "f1", "f2", "f3", "f4", "f_dup",
    "currency", "scenario",
    "revenue", "tier", "rate",
    "doc_no", "desc", "name_col", "line_key", "uuid_col", "entry_key", "desc_entry",
    "bill_city", "ship_city_lo", "tags",
]
PLANTED_CHAINS = {
    ("zip", "city", "state", "country", "region"),
    ("month48", "moy", "quarter"),
    ("month48", "year"),
    ("sku", "product", "subcat", "cat"),
    ("emp", "mgr", "dept"),
    ("acct", "acct_type"),
    ("store", "store_region"),
    ("ord_status", "pay_status_true"),
}
PLANTED_ALIASES = {frozenset({"acct", "acct_name", "gl_code"}), frozenset({"f1", "f_dup"})}
VOID_ALIAS = frozenset({"desc_entry", "entry_key"})


# --------------------------------------------------------------------------- #
# scoring + report                                                             #
# --------------------------------------------------------------------------- #
def decide(scan: Scan, cell: Cell, gate: str) -> bool:
    if cell.kind == "edge":
        return edge_decision(scan, cell.a, cell.b, gate)
    return alias_decision(scan, cell.a, cell.b, gate)


def main() -> None:
    df_a, df_b = build_fact_a(), build_fact_b()
    cols_a = [c for c in df_a.columns]  # date routing: no DATE col enters candidates
    scan_a = scan_pairs(df_a, cols_a)
    scan_b = scan_pairs(df_b, df_b.columns)
    print(f"# DAT-757 dimension-universe matrix  (fact_a n={N} x {len(cols_a)} cols, "
          f"fact_b n={N_B} x {df_b.width} cols)\n")

    # ---- cell matrix ----
    print(f"{'cell':20} {'pair':30} {'want':>5} {'eng':>4} {'row':>4} {'+rfi':>5} {'mixd':>5}  lane")
    results: dict[str, dict[str, bool]] = {}
    fam_seen: set[str] = set()
    for cell in CELLS:
        if cell.family not in fam_seen:
            fam_seen.add(cell.family)
            print(f"-- {cell.family}")
        scan = scan_a if cell.fact == "a" else scan_b
        marks = {}
        for gate in GATES:
            got = decide(scan, cell, gate)
            marks[gate] = got == cell.expect
        results[cell.id] = marks
        want = ("assert" if cell.expect else "reject") if cell.kind == "edge" else (
            "merge" if cell.expect else "no-mrg")
        sym = {g: ("ok" if marks[g] else "XX") for g in GATES}
        rel = "" if cell.kind == "edge" else " (alias)"
        print(f"{cell.id:20} {cell.a + '->' + cell.b + rel:30} {want:>6} "
              f"{sym['eng']:>4} {sym['row']:>4} {sym['row+rfi']:>5} {sym['mixed']:>5}  "
              f"[{cell.lane}] {cell.note}")

    # ---- gate summary by lane ----
    print("\n## gate summary")
    structural = [c for c in CELLS if c.lane == "structural"]
    lanes = [c for c in CELLS if c.lane != "structural"]
    for gate in GATES:
        ok = sum(results[c.id][gate] for c in structural)
        print(f"  {gate:8}: structural-lane cells correct {ok}/{len(structural)}")
    lane_required = [c for c in lanes if not any(results[c.id][g] for g in GATES)]
    print(f"  lane cells where NO structural gate is correct: {len(lane_required)}/{len(lanes)}"
          f"  ({', '.join(c.id + '->' + c.lane for c in lane_required)})")

    # ---- null-policy rescue demo (pairwise deletion) ----
    print("\n## null-policy: pairwise-deletion row-g3 on the null/ragged TRUE FDs")
    for a, b in [("city", "state_nul10"), ("city", "state_nul40"), ("emp", "team"), ("team", "dept")]:
        sub = df_a.select(a, b).drop_nulls()
        g3 = _row_g3(codes_of(sub.get_column(a)), codes_of(sub.get_column(b)))
        print(f"  {a}->{b:14} rows kept {sub.height:>6}/{N}  row-g3(pairwise-del) = {g3:.5f} "
              f"-> {'RESCUED' if g3 <= 0.01 else 'still lost'}")

    # ---- assembled pipeline per gate ----
    print("\n## assembled pipeline (clean set + attackers; variant columns excluded, logged)")
    for gate in GATES:
        res = assemble(scan_a, PIPE_COLS, gate)
        chains = {tuple(ch) for ch in res.chains}
        # chains on reps: map planted chains through this gate's alias reps
        planted = {tuple(res.rep.get(c, c) for c in ch) for ch in PLANTED_CHAINS}
        planted = {tuple(dict.fromkeys(ch)) for ch in planted}  # collapse alias-equal levels
        planted = {ch for ch in planted if len(ch) >= 2}
        recovered = planted & chains
        spurious_chains = sorted(chains - planted)
        groups = {frozenset(g) for g in res.alias_groups}
        true_alias = groups & PLANTED_ALIASES
        void_alias = groups & {VOID_ALIAS}
        spurious_alias = groups - PLANTED_ALIASES - {VOID_ALIAS}
        print(f"\n  gate={gate}: true chains {len(recovered)}/{len(planted)} | "
              f"spurious chains {len(spurious_chains)} | alias: true {len(true_alias)}/2, "
              f"void {len(void_alias)}, spurious {len(spurious_alias)}")
        for ch in sorted(planted - recovered):
            print(f"    MISSING chain: {' -> '.join(ch)}")
        for ch in spurious_chains:
            print(f"    SPURIOUS chain: {' -> '.join(ch)}")
        for g in sorted(spurious_alias):
            print(f"    SPURIOUS alias: {{{', '.join(sorted(g))}}}")
        if void_alias:
            print(f"    void-but-true alias kept: {{{', '.join(sorted(VOID_ALIAS))}}} (abstain lane)")

    # ---- logged lanes ----
    print("\n## logged (untestable in pure math — no silent pass)")
    for fam, msg in LOGGED_LANES:
        print(f"  [{fam}] {msg}")


if __name__ == "__main__":
    main()
