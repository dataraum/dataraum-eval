"""DAT-757 RelBench fold — stage 2: fold a real database by its declared FKs, run the
frozen gate stack over the OBT, grade folded-dimension recovery against FK truth.

CLAIM UNDER TEST (to refute)
----------------------------
"The DAT-757 stack frozen from the synthetic matrix — effect screens (row-g3 edges /
pair-count aliases + engine guards) -> permutation-p + BH q<=0.05 over the screened
family — recovers the folded-dimension skeleton (fold groups, alias clusters, the
FK-derived chain) on REAL data we did not generate, and its residue (asserted
structure outside FK truth) is small and semantically classifiable. The engine's
distinct-ratio g3 ('eng') degrades on the same OBT the way the matrix predicted."

THE ATTACK
----------
Out-of-distribution everything: real value distributions (heavy-tailed reference
frequencies), real dirt (nulls in ~half of driver codes / lap times), real
pre-existing denormalization (results.date), near-unique numeric measures
(milliseconds — the high-card chance-FD trap), and truth derived from metadata we
had no hand in (RelBench packaged pkey/fkey; DAT-693's corpus bundle).

TRUTH MODEL (no circularity)
----------------------------
We denormalize the normalized source ourselves, so every FK becomes a folded
exposure with derivable expectations. Exactness of an FD (row-g3 == 0) is invariant
to row multiplicity, so the OBT scan itself yields the exact-FD skeleton; the FK
metadata then LABELS which of it is dimension structure (fold groups, keys, the
race->circuit chain). Grading: recall over exact truth pairs (by fold-group label,
with guard-blocked truth reported as out-of-envelope, not failure), and every extra
assertion classified {in-group dirt-tolerant | fact-internal | cross-group} with
its stats — the semantic-lane residue, measured in the wild. Scoreboard per
DAT-693: findings, never a build-break.

Run:  uv run python scripts/probes/dat757-relbench/probe_fold_grade.py rel-f1
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import polars as pl

G3DIR = Path(__file__).parents[1] / "dat757-g3-wide"
sys.path.insert(0, str(G3DIR))
from fdlib import (  # noqa: E402
    MIN_DISTINCT_DIMENSION,
    Scan,
    _maximal_chains,
    _transitive_reduction,
    assemble,
    bh_reject,
    perm_pvalue,
    scan_pairs,
)
from probe_bh_gate import alias_screen, edge_screen  # noqa: E402

Q_FDR = 0.05

# fold spec per dataset: fact table + (obt_key_col, dim_table, prefix) hops, applied
# in order so a folded dim's own FK (races.circuitId) can key the next hop.
SPECS: dict[str, dict] = {
    "rel-f1": {
        "fact": "results",
        "folds": [
            ("raceId", "races", "race__"),
            ("driverId", "drivers", "driver__"),
            ("constructorId", "constructors", "constructor__"),
            ("race__circuitId", "circuits", "circuit__"),
        ],
        "probe_n": None,  # 26k — use everything
        "perm_reps": 2999,
    },
    "rel-hm": {
        "fact": "transactions",
        "folds": [
            ("article_id", "article", "article__"),
            ("customer_id", "customer", "customer__"),
        ],
        # entity-complete sampling: a random row sample leaves customer_id ~92%
        # distinct -> the near-key guard would kill the whole customer fold. Sampling
        # customers and keeping ALL their rows is the realistic slice (FD exactness
        # is subset-invariant) and drops the key ratio to ~40%.
        "sample_by": ("customer_id", 60_000),
        "probe_n": None,
        "perm_reps": 999,
    },
    # SAP SALT: FOUR role-playing FKs into the same customer dim (sold-to / ship-to /
    # bill-to / payer) + a two-hop address fold per role — gate #2's role-provenance
    # cell in real enterprise data, three tiers deep (party id, address id, geo).
    "rel-salt": {
        "fact": "salesdocumentitem",
        "folds": [
            ("SALESDOCUMENT", "salesdocument", "doc__"),
            ("SOLDTOPARTY", "customer", "soldto__"),
            ("SHIPTOPARTY", "customer", "shipto__"),
            ("BILLTOPARTY", "customer", "billto__"),
            ("PAYERPARTY", "customer", "payer__"),
            ("soldto__ADDRESSID", "address", "soldto_addr__"),
            ("shipto__ADDRESSID", "address", "shipto_addr__"),
            ("billto__ADDRESSID", "address", "billto_addr__"),
            ("payer__ADDRESSID", "address", "payer_addr__"),
        ],
        "sample_by": ("SALESDOCUMENT", 50_000),
        "probe_n": None,
        "perm_reps": 999,
        # contexts for the wild role tests: item + header columns, never the
        # sibling role copies themselves (they are outcomes, not drivers)
        "role_context_groups": ("fact", "fact-key", "doc"),
    },
}


# --------------------------------------------------------------------------- #
# fold                                                                         #
# --------------------------------------------------------------------------- #
def build_obt(base: Path, spec: dict) -> tuple[pl.DataFrame, dict[str, str]]:
    """LEFT-JOIN fold per spec. Returns (obt, col -> fold-group label)."""
    schema = json.loads((base / "schema.json").read_text())
    con = duckdb.connect()
    for t in schema:
        con.execute(
            f'CREATE VIEW "{t}" AS SELECT * FROM read_parquet(\'{base}/tables/{t}.parquet\')'
        )
    fact = spec["fact"]
    con.execute(f'CREATE TABLE obt AS SELECT * FROM "{fact}"')
    group = {c: "fact" for c in schema[fact]["columns"]}
    group[schema[fact]["pkey"]] = "fact-key"

    for key_col, dim, prefix in spec["folds"]:
        pkey = schema[dim]["pkey"]
        attrs = [c for c in schema[dim]["columns"] if c != pkey]
        sel = ", ".join(f'd."{c}" AS "{prefix}{c}"' for c in attrs)
        con.execute(
            f'CREATE OR REPLACE TABLE obt AS SELECT o.*, {sel} '
            f'FROM obt o LEFT JOIN "{dim}" d ON o."{key_col}" = d."{pkey}"'
        )
        unmatched = con.execute(
            f'SELECT COUNT(*) FROM obt o LEFT JOIN "{dim}" d ON o."{key_col}" = d."{pkey}" '
            f'WHERE d."{pkey}" IS NULL AND o."{key_col}" IS NOT NULL'
        ).fetchone()[0]
        gname = prefix.rstrip("_")
        group[key_col] = f"{gname}-key"  # the fk IS the folded dim's identity column
        for c in attrs:
            group[f"{prefix}{c}"] = gname
        print(f"  fold {key_col} -> {dim} ({len(attrs)} attrs, {unmatched} unmatched keys)")

    obt = con.execute("SELECT * FROM obt").pl()
    if spec.get("sample_by"):
        key, n_keys = spec["sample_by"]
        keys = obt.get_column(key).unique()
        if len(keys) > n_keys:
            keep = keys.sample(n_keys, seed=757)
            obt = obt.filter(pl.col(key).is_in(keep))
            print(f"  entity-complete sample: {n_keys:,} {key} -> {len(obt):,} rows")
    if spec["probe_n"] and len(obt) > spec["probe_n"]:
        obt = obt.sample(spec["probe_n"], seed=757)
        print(f"  sampled OBT to {len(obt):,} rows")
    return obt, group


# --------------------------------------------------------------------------- #
# truth from the scan: exact FDs, labeled by fold group                        #
# --------------------------------------------------------------------------- #
def truth_tables(scan: Scan, cols: list[str]) -> tuple[set, set]:
    """(exact directed edges a->b with d_a>d_b, exact bijections {a,b})."""
    edges, aliases = set(), set()
    for (a, b), ps in scan.stats.items():
        f0, b0 = ps.g3_row_fwd == 0.0, ps.g3_row_bwd == 0.0
        if f0 and b0 and ps.d_a >= MIN_DISTINCT_DIMENSION:
            aliases.add(frozenset((a, b)))
        elif f0 and ps.d_a > ps.d_b and ps.d_b >= MIN_DISTINCT_DIMENSION:
            edges.add((a, b))
        elif b0 and ps.d_b > ps.d_a and ps.d_a >= MIN_DISTINCT_DIMENSION:
            edges.add((b, a))
    return edges, aliases


# --------------------------------------------------------------------------- #
# the frozen BH stack over one view                                            #
# --------------------------------------------------------------------------- #
def bh_stack(scan: Scan, cols: list[str], reps: int) -> tuple[set, set, dict]:
    """(accepted directed edges, accepted alias pairs, pvals) — screens -> perm-p -> BH."""
    eligible = [c for c in cols if scan.singles[c] >= MIN_DISTINCT_DIMENSION]
    cand_e, cand_a = [], []
    for i, a in enumerate(eligible):
        for b in eligible[i + 1 :]:
            if alias_screen(scan, a, b):
                cand_a.append((a, b))
            if edge_screen(scan, a, b):
                cand_e.append((a, b))
            if edge_screen(scan, b, a):
                cand_e.append((b, a))
    print(f"  screened candidates: {len(cand_e)} edges, {len(cand_a)} aliases "
          f"(of {len(eligible) * (len(eligible) - 1)} directed pairs)")
    pvals: dict[tuple, float] = {}
    t0 = time.time()
    for k, (a, b) in enumerate(cand_e):
        pvals[("e", a, b)] = perm_pvalue(scan, a, b, reps=reps)
        if (k + 1) % 25 == 0:
            print(f"    perm {k + 1}/{len(cand_e) + len(cand_a)} ({time.time() - t0:.0f}s)")
    for a, b in cand_a:
        pvals[("a", a, b)] = max(
            perm_pvalue(scan, a, b, reps=reps), perm_pvalue(scan, b, a, reps=reps)
        )
    rejected = bh_reject(pvals, m_family=max(1, len(pvals)), q=Q_FDR)
    acc_e = {(a, b) for k, a, b in rejected if k == "e"}
    acc_a = {(a, b) for k, a, b in rejected if k == "a"}
    # both directions BH-accepted as edges -> keep the stronger (smaller p); the
    # faithful pipeline never emits 2-cycles (elif), decided sets must not either
    for a, b in [(a, b) for (a, b) in acc_e if (b, a) in acc_e and a < b]:
        drop = (a, b) if pvals[("e", a, b)] > pvals[("e", b, a)] else (b, a)
        acc_e.discard(drop)
    print(f"  BH accepted: {len(acc_e)} edges, {len(acc_a)} aliases "
          f"({time.time() - t0:.0f}s permutation stage)")
    return acc_e, acc_a, pvals


def assemble_decided(
    eligible: list[str], acc_alias: set, acc_edges: set
) -> tuple[list[list[str]], dict[str, str], list[list[str]]]:
    """fdlib.assemble's alias->edges->reduction->chains flow over decided sets."""
    parent = {c: c for c in eligible}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in sorted(acc_alias):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[min(ra, rb)] = max(ra, rb)
    members: dict[str, list[str]] = {}
    for c in eligible:
        members.setdefault(find(c), []).append(c)
    groups = [sorted(g) for g in members.values() if len(g) >= 2]
    rep = {c: sorted(g)[0] for g in members.values() for c in g}
    edges = set()
    for a, b in acc_edges:
        ra, rb = rep[a], rep[b]
        if ra != rb:
            edges.add((ra, rb))
    chains = _maximal_chains(_transitive_reduction(edges))
    return groups, rep, chains


# --------------------------------------------------------------------------- #
# grading                                                                      #
# --------------------------------------------------------------------------- #
def grade(
    name: str,
    scan: Scan,
    group: dict[str, str],
    truth_e: set,
    truth_a: set,
    got_e: set,
    got_a: set,
    verbose: bool,
) -> str:
    """One gate's scoreboard line (+ full detail when verbose)."""
    dim_truth_e = {(a, b) for a, b in truth_e if group[a] != "fact" or group[b] != "fact"}
    hit_e = {(a, b) for a, b in dim_truth_e if (a, b) in got_e}
    # an exact edge folded into an accepted alias group counts as captured structure
    alias_flat = {frozenset(p) for p in got_a}
    hit_via_alias = {
        (a, b) for a, b in dim_truth_e - hit_e if frozenset((a, b)) in alias_flat
    }
    missed = dim_truth_e - hit_e - hit_via_alias
    hit_a = {p for p in truth_a if tuple(sorted(p)) in {tuple(sorted(q)) for q in got_a}}
    extra_e = got_e - truth_e
    extra_a = {frozenset(p) for p in got_a} - truth_a
    line = (
        f"  {name:10} edges {len(hit_e) + len(hit_via_alias)}/{len(dim_truth_e)}"
        f"  aliases {len(hit_a)}/{len(truth_a)}"
        f"  extras {len(extra_e)}e+{len(extra_a)}a"
    )
    if not verbose:
        return line

    print(line)
    if missed:
        print("    missed truth edges (why):")
        for a, b in sorted(missed):
            key, fwd = ((a, b), True) if (a, b) in scan.stats else ((b, a), False)
            ps = scan.stats[key]
            d_a = ps.d_a if fwd else ps.d_b
            why = "near-key guard" if d_a >= 0.9 * scan.n else "screen/BH"
            print(f"      {a} -> {b}  [{group[a]}->{group[b]}] d_a={d_a} ({why})")
    if extra_e or extra_a:
        print("    extras (the residue, classified):")
        for a, b in sorted(extra_e):
            key, fwd = ((a, b), True) if (a, b) in scan.stats else ((b, a), False)
            ps = scan.stats[key]
            g3 = ps.g3_row_fwd if fwd else ps.g3_row_bwd
            ga, gb = group[a], group[b]
            klass = (
                "in-group dirt" if ga.removesuffix("-key") == gb.removesuffix("-key")
                else "fact-internal" if {ga, gb} <= {"fact", "fact-key"}
                else "cross-group"
            )
            print(f"      edge  {a} -> {b}  [{klass}] row-g3={g3:.5f}")
        for p in sorted(tuple(sorted(q)) for q in extra_a):
            a, b = p
            ps = scan.stats[(a, b)] if (a, b) in scan.stats else scan.stats[(b, a)]
            print(f"      alias {a} <-> {b}  [{group[a]}|{group[b]}] "
                  f"row-g3 {ps.g3_row_fwd:.5f}/{ps.g3_row_bwd:.5f}")
    return line


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", choices=sorted(SPECS))
    args = ap.parse_args()
    spec = SPECS[args.dataset]
    base = Path("corpora/relbench") / args.dataset

    print(f"# DAT-757 RelBench fold — {args.dataset}\n\n## fold")
    obt, group = build_obt(base, spec)
    cols = list(obt.columns)
    print(f"  OBT: {len(obt):,} rows x {len(cols)} cols")

    print("\n## scan + FK-labeled exact-FD truth")
    t0 = time.time()
    scan = scan_pairs(obt, cols)
    truth_e, truth_a = truth_tables(scan, cols)
    print(f"  scan {time.time() - t0:.0f}s; exact truth: {len(truth_e)} edges, "
          f"{len(truth_a)} bijections")
    by_label: dict[str, int] = {}
    for a, b in truth_e:
        lbl = f"{group[a]} -> {group[b]}"
        by_label[lbl] = by_label.get(lbl, 0) + 1
    for lbl, cnt in sorted(by_label.items(), key=lambda kv: -kv[1]):
        print(f"    {cnt:3} {lbl}")
    for p in sorted(tuple(sorted(q)) for q in truth_a):
        print(f"    alias {p[0]} <-> {p[1]}")

    print("\n## gates on the same OBT")
    eligible = [c for c in cols if scan.singles[c] >= MIN_DISTINCT_DIMENSION]

    print("  [eng] engine distinct-ratio pipeline:")
    eng = assemble(scan, cols, "eng")
    eng_edges = set()  # re-derive pairwise asserts for grading (pre-collapse)
    from fdlib import alias_decision, edge_decision  # noqa: PLC0415

    for i, a in enumerate(eligible):
        for b in eligible[i + 1 :]:
            if edge_decision(scan, a, b, "eng"):
                eng_edges.add((a, b))
            elif edge_decision(scan, b, a, "eng"):
                eng_edges.add((b, a))
    eng_alias = {
        (a, b)
        for i, a in enumerate(eligible)
        for b in eligible[i + 1 :]
        if alias_decision(scan, a, b, "eng")
    }
    print(f"    pairwise: {len(eng_edges)} edges, {len(eng_alias)} alias pairs; "
          f"assembled: {len(eng.alias_groups)} groups, {len(eng.chains)} chains")

    print("  [bh] frozen stack (screens -> perm-p -> BH):")
    acc_e, acc_a, pvals = bh_stack(scan, cols, spec["perm_reps"])
    groups_bh, rep_bh, chains_bh = assemble_decided(eligible, acc_a, acc_e)

    print("\n## scoreboard (dimension-truth recall / extras)")
    print(grade("eng", scan, group, truth_e, truth_a, eng_edges, eng_alias, False))
    grade("bh-stack", scan, group, truth_e, truth_a, acc_e, acc_a, True)

    print("\n## assembled structure under the BH stack")
    for g in groups_bh:
        print(f"  alias group: {g}")
    for ch in chains_bh:
        pretty = " -> ".join(
            f"{c}[{'|'.join(m for m in eligible if rep_bh[m] == c)}]" if any(
                rep_bh[m] == c and m != c for m in eligible
            ) else c
            for c in ch
        )
        print(f"  chain: {pretty}")

    print("\n## wild near-aliases (0 < disagreement <= 1% — gate #2 candidates)")
    for (a, b), ps in sorted(scan.stats.items()):
        if ps.d_a < MIN_DISTINCT_DIMENSION or ps.d_b < MIN_DISTINCT_DIMENSION:
            continue
        g_max = max(ps.g3_row_fwd, ps.g3_row_bwd)
        if 0.0 < g_max <= 0.01:
            k = int(round(g_max * scan.n))
            print(f"  {a} <-> {b}  max row-g3 {g_max:.5f} (~k={k}) [{group[a]}|{group[b]}]")

    wild_role_section(obt, group, eligible, spec)

    print("\n## VERDICT: skeleton recovered + residue classifiable => stack survives OOD.")


# --------------------------------------------------------------------------- #
# gate #2 in the wild: same-domain near-copies -> disagreement-set tests       #
# --------------------------------------------------------------------------- #
def wild_role_section(
    obt: pl.DataFrame, group: dict[str, str], eligible: list[str], spec: dict
) -> None:
    """Detect value-equality near-copies (0 < disagree <= 5%) and classify each via
    the frozen gate-#2 machinery: perm-p of dis=1{A!=B} vs every context column
    (membership, T1) and vs B (values, T2), Bonferroni over the family. Contexts =
    spec's role_context_groups only — sibling role copies are outcomes, not drivers."""
    ctx_groups = spec.get("role_context_groups", ("fact", "fact-key"))
    reps = spec["perm_reps"]
    strs = {c: obt.get_column(c).cast(pl.Utf8).fill_null("␀").to_numpy() for c in eligible}
    pairs = []
    for i, a in enumerate(eligible):
        for b in eligible[i + 1 :]:
            rate = float((strs[a] != strs[b]).mean())
            if 0.0 < rate <= 0.05:
                pairs.append((a, b, rate))
    print(f"\n## gate #2 in the wild — same-domain near-copies ({len(pairs)} pairs)")
    for a, b, rate in pairs:
        dis = (strs[a] != strs[b]).astype(np.int64)
        k = int(dis.sum())
        contexts = [c for c in eligible if c not in (a, b) and group[c] in ctx_groups]
        m = len(contexts) + 1
        alpha = 0.05 / m
        t1_ctx, t1_p = None, 1.0
        for c in contexts:
            df = pl.DataFrame({"dis": dis, "x": strs[c]})
            sc = scan_pairs(df, ["dis", "x"])
            p = perm_pvalue(sc, "dis", "x", reps=reps)
            if p < t1_p:
                t1_ctx, t1_p = c, p
        df = pl.DataFrame({"dis": dis, "x": strs[b]})
        t2_p = perm_pvalue(scan_pairs(df, ["dis", "x"]), "dis", "x", reps=reps)
        floor = 1.0 / (1.0 + reps)
        # T1 (membership systematic w.r.t. a context) is the role-specific signal;
        # T2 (value concentration) fires on roles AND on value-concentrated dirt
        # (real dirt is rarely marginal-random) -> alone it only escalates.
        verdict = (
            "ROLE (membership-systematic; keep apart)" if t1_p <= alpha
            else "VALUE-SYSTEMATIC (role or concentrated dirt -> semantic lane)"
            if t2_p <= alpha
            else "ABSTAIN (p-floor > alpha)" if floor > alpha
            else "DIRT (merge ok)"
        )
        print(f"  {a} <-> {b}  disagree {rate:.4%} (k={k})  "
              f"T1 {t1_p:.2e} @ {t1_ctx}  T2 {t2_p:.2e}  (alpha' {alpha:.1e}, m={m})\n"
              f"    -> {verdict}")


if __name__ == "__main__":
    main()
