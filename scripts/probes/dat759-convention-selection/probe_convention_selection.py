"""DAT-759 — convention-selection statistics: support (Wilson LCB) vs min-residual.

CLAIM UNDER TEST (to refute):
 1. REPRO — on the real clean corpus the engine criterion (min winning-pattern
    median residual across the family, ``processor.py:450``) picks the collinear
    artifact ``debit − net_amount`` over the true single ``debit`` for
    ``trial_balance.debit_balance`` (observed 2026-07-14: match 0.50), because
    support never enters selection. Expected bands: artifact wins the residual
    race on a ~half-entity voter set; ``debit`` votes broadly but loses.
 2. FIX #1 — selection by the Wilson score lower bound (95%) of the vote rate
    over the COMMON entity denominator (tie-break: median residual; arity
    tie-break: prefer the single unless the difference wins by ΔBIC > 10)
    selects the true convention for every measure, by a margin.
 3. FIX #2 — a min-over-family permutation null (Westfall–Young maxT within
    entity, Stouffer-combined across the common denominator, BH across the
    family) ranks the true convention first by q with no reliance on the
    ``FIRE_RESIDUAL_MAX`` hard threshold.

THE ATTACK:
 - the in-family collinear derivative ``net_amount = debit − credit``, so
   ``debit − net_amount ≡ credit``: statistically real wherever credit movement
   tracks the measure, semantically void for ``debit_balance`` — breadth must
   beat depth (leg a).
 - support gameability: a term present on only half the entities gives a
   convention a shrunken own-subset denominator and a perfect vote rate; the
   Wilson bound computed per-subset ranks it wrongly, the common denominator
   must not (leg b2 — the DAT-759 implementation caveat).
 - a TRUE difference (measure = gross − fees) must NOT be killed by
   single-preference (leg b1).
 - small-N (3 entities): the LCB collapses toward 0 but ORDERING must hold
   (leg b3).

Statistics: Wilson score interval (Wilson 1927), BIC (Schwarz; Kass–Raftery
ΔBIC>10 = "very strong"), Westfall–Young maxT permutation null, Stouffer
combination, Benjamini–Hochberg FDR. Engine residual/vote/disposal semantics
are IMPORTED from ``dataraum.analysis.lineage.reconcile`` — not mirrored.

Run: uv run python scripts/probes/dat759-convention-selection/probe_convention_selection.py
"""

from __future__ import annotations

import csv
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist, median

from dataraum.analysis.lineage.reconcile import (
    FIRE_RESIDUAL_MAX,
    MIN_PERIODS,
    classify_entity,
)

DATA = Path(__file__).resolve().parents[3] / "data" / "clean"
Z95 = 1.96
B_PERM = 300
RNG_SEED = 759

# ---------------------------------------------------------------- corpus load


def _read(name: str) -> list[dict[str, str]]:
    with (DATA / f"{name}.csv").open() as f:
        return list(csv.DictReader(f))


def load_event_series() -> dict[str, dict[str, dict[str, float]]]:
    """journal_lines × journal_entries → account -> month -> {col: sum}.

    Mirrors the engine's inline GROUP BY over the enriched view (the view joins
    the entry date onto the lines; monthly grain, '%Y-%m' labels).
    """
    entry_month = {r["entry_id"]: r["date"][:7] for r in _read("journal_entries")}
    sums: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(float))
    )
    for r in _read("journal_lines"):
        month = entry_month.get(r["entry_id"])
        if month is None:
            continue
        acct = r["account_id"]
        for col in ("debit", "credit", "net_amount"):
            if r[col] != "":
                sums[acct][month][col] += float(r[col])
    return {a: {m: dict(cols) for m, cols in months.items()} for a, months in sums.items()}


def load_measure_series(table: str, col: str) -> dict[str, dict[str, float]]:
    """trial_balance / balance_sheet → account -> month -> value."""
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for r in _read(table):
        if r[col] != "":
            out[r["account_id"]][r["period"]] = float(r[col])
    return dict(out)


# ------------------------------------------------------- family + alignment


def conventions(cols: list[str]) -> list[tuple[str, tuple[str, ...]]]:
    """The engine's hypothesis family (processor._conventions): singles + ordered diffs."""
    out: list[tuple[str, tuple[str, ...]]] = [(c, (c,)) for c in cols]
    out.extend((f"{a} - {b}", (a, b)) for a in cols for b in cols if a != b)
    return out


def convention_value(period_sums: dict[str, float], terms: tuple[str, ...]) -> float | None:
    if any(t not in period_sums for t in terms):
        return None
    return period_sums[terms[0]] - period_sums[terms[1]] if len(terms) == 2 else period_sums[terms[0]]


def aligned(
    measure: dict[str, dict[str, float]],
    event: dict[str, dict[str, dict[str, float]]],
    terms: tuple[str, ...],
) -> dict[str, tuple[list[float], list[float]]]:
    """Pair by (entity, month) — processor._aligned_series over the CSV substrate."""
    by_entity: dict[str, tuple[list[float], list[float]]] = {}
    for acct in sorted(set(measure) & set(event)):
        ys, ms = [], []
        for month in sorted(set(measure[acct]) & set(event[acct])):
            m = convention_value(event[acct][month], terms)
            if m is None:
                continue
            ys.append(measure[acct][month])
            ms.append(m)
        if ys:
            by_entity[acct] = (ys, ms)
    return by_entity


# ------------------------------------------------------------- the criteria


@dataclass
class Candidate:
    name: str
    terms: tuple[str, ...]
    votes: int  # entities whose winning residual clears the engine vote gate
    n_common: int  # the COMMON denominator (fixed across the family)
    residuals: dict[str, float]  # entity -> winning residual (inf = not evaluable)
    pattern_votes: dict[str, str | None]  # entity -> voted label

    @property
    def vote_rate(self) -> float:
        return self.votes / self.n_common if self.n_common else 0.0

    @property
    def lcb(self) -> float:
        return wilson_lcb(self.votes, self.n_common)

    @property
    def median_voter_residual(self) -> float:
        r = [v for e, v in self.residuals.items() if self.pattern_votes.get(e)]
        return median(r) if r else float("inf")


def wilson_lcb(v: int, n: int, z: float = Z95) -> float:
    """Wilson score interval lower bound for v/n."""
    if n == 0:
        return 0.0
    p = v / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return max(0.0, (centre - margin) / denom)


def evaluate_family(
    measure: dict[str, dict[str, float]],
    event: dict[str, dict[str, dict[str, float]]],
    cols: list[str],
) -> tuple[list[Candidate], list[str]]:
    """Run every convention through the ENGINE's classify_entity on a common universe."""
    fam = conventions(cols)
    # Common denominator: entities with a live measure series of >= MIN_PERIODS
    # aligned months (alignment months are convention-independent on this corpus).
    probe_terms = (cols[0],)
    base = aligned(measure, event, probe_terms)
    universe = sorted(
        e for e, (ys, _) in base.items() if len(ys) >= MIN_PERIODS and any(ys)
    )
    out: list[Candidate] = []
    for name, terms in fam:
        by_entity = aligned(measure, event, terms)
        residuals: dict[str, float] = {}
        labels: dict[str, str | None] = {}
        votes = 0
        for e in universe:
            if e not in by_entity:
                residuals[e] = float("inf")
                labels[e] = None
                continue
            ys, ms = by_entity[e]
            rec = classify_entity(ys, ms)
            residuals[e] = min(rec.r_flow, rec.r_stock)
            labels[e] = rec.label
            if rec.label is not None:
                votes += 1
        out.append(
            Candidate(
                name=name,
                terms=terms,
                votes=votes,
                n_common=len(universe),
                residuals=residuals,
                pattern_votes=labels,
            )
        )
    return out, universe


def engine_winner(cands: list[Candidate]) -> Candidate | None:
    """The current criterion: min median voter residual among firing candidates.

    Mirrors processor.py:450 (residual comparison across verdicts; a candidate
    needs >= 2 voters to have a verdict at all).
    """
    firing = [c for c in cands if c.votes >= 2]
    return min(firing, key=lambda c: c.median_voter_residual) if firing else None


def lcb_winner(
    cands: list[Candidate], qvals: dict[str, float] | None = None
) -> tuple[Candidate | None, str]:
    """FIX #1 selector (optionally gated by FIX #2 significance).

    Max Wilson LCB over the common denominator. Among LCB ties, the arity
    tie-break is SYMMETRIC (Kass–Raftery): start from the lowest-arity tied
    candidate; a difference displaces a single only when it wins by ΔBIC > 10.
    When q-values are supplied (FIX #2), they act as the FIRE GATE (q <= 0.05
    replaces FIRE_RESIDUAL_MAX's role at the verdict level) — never as the
    selector: exact collinear twins (``debit − net_amount ≡ credit``) are
    numerically identical, so no data statistic can order them; only breadth
    (same) and description length (arity) can.
    """
    firing = [c for c in cands if c.votes >= 2]
    if qvals is not None:
        firing = [c for c in firing if qvals.get(c.name, 1.0) <= 0.05]
    if not firing:
        return None, "no candidate fires"
    best_lcb = max(c.lcb for c in firing)
    tied = sorted(
        (c for c in firing if abs(c.lcb - best_lcb) < 1e-12),
        key=lambda c: (len(c.terms), c.median_voter_residual),
    )
    top, note = tied[0], ""
    for challenger in tied[1:]:
        if len(challenger.terms) > len(top.terms):
            delta = bic(top) - bic(challenger)  # >0 favours the challenger
            if delta > 10.0:
                note = f"ΔBIC={delta:.1f}>10 → {challenger.name!r} over {top.name!r}"
                top = challenger
    if not note and len(tied) > 1:
        note = f"LCB tie ({len(tied)}) → arity/ΔBIC kept {top.name!r}"
    return top, note


def bic(c: Candidate) -> float:
    """BIC over the pooled voter residual mass; k = arity (movement terms)."""
    # Residuals are already scale-free per entity; pool |resid| mass as RSS proxy.
    voters = [e for e in c.residuals if c.pattern_votes.get(e)]
    if not voters:
        return float("inf")
    n = len(voters)
    rss = max(sum(c.residuals[e] ** 2 for e in voters), 1e-12)
    return n * math.log(rss / n) + len(c.terms) * math.log(n)


# ------------------------------------------------- FIX #2: permutation null


def perm_family_q(
    measure: dict[str, dict[str, float]],
    event: dict[str, dict[str, dict[str, float]]],
    cols: list[str],
    universe: list[str],
    cands: list[Candidate],
) -> dict[str, float]:
    """min-over-family maxT permutation null → per-convention BH q.

    Within each entity, the event-side per-month tuples are shuffled jointly
    (cross-column structure like net = debit − credit is preserved; only the
    TIME ALIGNMENT breaks). The null statistic is the FAMILY MINIMUM winning
    residual — each convention's observed residual is compared against the best
    the whole family achieves on scrambled time, which prices the search
    freedom (Westfall–Young maxT). Per-entity p's are Stouffer-combined over
    the common denominator (breadth wins), then BH across the family.
    """
    rng = random.Random(RNG_SEED)
    fam = conventions(cols)
    # Pre-extract per entity: y series and the per-month event tuples.
    per_entity: dict[str, tuple[list[float], list[dict[str, float]]]] = {}
    for e in universe:
        months = sorted(set(measure.get(e, {})) & set(event.get(e, {})))
        ys = [measure[e][m] for m in months]
        tuples = [event[e][m] for m in months]
        if len(ys) >= MIN_PERIODS and any(ys):
            per_entity[e] = (ys, tuples)

    # Null distribution per entity: B draws of min-over-family winning residual.
    null_min: dict[str, list[float]] = {}
    for e, (ys, tuples) in per_entity.items():
        draws: list[float] = []
        for _ in range(B_PERM):
            perm = tuples[:]
            rng.shuffle(perm)
            best = float("inf")
            for _name, terms in fam:
                ms = [convention_value(t, terms) for t in perm]
                if any(v is None for v in ms):
                    continue
                rec = classify_entity(ys, [float(v) for v in ms])  # type: ignore[arg-type]
                best = min(best, rec.r_flow, rec.r_stock)
            draws.append(best)
        null_min[e] = draws

    nd = NormalDist()
    p_floor = 1.0 / (B_PERM + 1)
    combined: dict[str, float] = {}
    for c in cands:
        zs: list[float] = []
        for e in per_entity:
            r_obs = c.residuals.get(e, float("inf"))
            draws = null_min[e]
            p = (1 + sum(1 for d in draws if d <= r_obs)) / (B_PERM + 1)
            p = min(max(p, p_floor), 1 - p_floor)
            zs.append(nd.inv_cdf(1 - p))
        z = sum(zs) / (len(zs) ** 0.5) if zs else 0.0
        combined[c.name] = 1 - nd.cdf(z)
    return bh(combined)


def bh(pvals: dict[str, float]) -> dict[str, float]:
    """Benjamini–Hochberg q-values."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    qs: dict[str, float] = {}
    prev = 1.0
    for rank in range(m, 0, -1):
        name, p = items[rank - 1]
        prev = min(prev, p * m / rank)
        qs[name] = prev
    return qs


# ------------------------------------------------------------------ report


def report(
    title: str,
    truth: str,
    cands: list[Candidate],
    qvals: dict[str, float] | None,
) -> tuple[str | None, str | None, str | None]:
    eng = engine_winner(cands)
    fix1, note = lcb_winner(cands)
    composite, cnote = (lcb_winner(cands, qvals) if qvals else (None, ""))
    print(f"\n=== {title}   (truth: {truth}) ===")
    print(f"{'convention':<24}{'votes':>7}{'rate':>7}{'LCB':>7}{'med.res':>9}{'q':>10}")
    for c in sorted(cands, key=lambda c: -c.lcb):
        q = f"{qvals[c.name]:.4f}" if qvals else "-"
        mr = c.median_voter_residual
        mr_s = f"{mr:.3f}" if mr != float("inf") else "inf"
        print(
            f"{c.name:<24}{c.votes:>4}/{c.n_common:<3}{c.vote_rate:>6.2f}"
            f"{c.lcb:>7.3f}{mr_s:>9}{q:>10}"
        )
    print(
        f"engine (min-residual): {eng.name if eng else None}"
        f"   | FIX#1 (Wilson LCB): {fix1.name if fix1 else None}"
        + (f" [{note}]" if note else "")
        + (
            f"   | FIX#1+#2 (q<=0.05 gate): {composite.name if composite else None}"
            + (f" [{cnote}]" if cnote else "")
            if qvals
            else ""
        )
    )
    return (
        eng.name if eng else None,
        fix1.name if fix1 else None,
        composite.name if composite else None,
    )


def leg_a_real() -> list[tuple[str, str, str | None, str | None, str | None]]:
    print("\n" + "=" * 74)
    print("LEG (a) REAL — clean corpus, event = journal_lines over accounts, monthly")
    print("=" * 74)
    event = load_event_series()
    cols = ["credit", "debit", "net_amount"]  # sorted, engine order
    rows = []
    for table, col, truth in (
        ("trial_balance", "debit_balance", "debit"),
        ("trial_balance", "credit_balance", "credit"),
        ("balance_sheet", "ending_balance", "net_amount (stock)"),
    ):
        measure = load_measure_series(table, col)
        cands, universe = evaluate_family(measure, event, cols)
        qv = perm_family_q(measure, event, cols, universe, cands)
        picks = report(f"{table}.{col}", truth, cands, qv)
        rows.append((f"{table}.{col}", truth, *picks))
    return rows


def leg_b_synthetic() -> None:
    print("\n" + "=" * 74)
    print("LEG (b) SYNTHETIC attacks")
    print("=" * 74)
    rng = random.Random(42)
    months = [f"2025-{m:02d}" for m in range(1, 13)]

    # b1 — TRUE difference: measure = gross − fees (+1% noise). Must survive #1.
    event: dict[str, dict[str, dict[str, float]]] = {}
    measure: dict[str, dict[str, float]] = {}
    for i in range(12):
        e = f"E{i:02d}"
        event[e], measure[e] = {}, {}
        for m in months:
            gross = rng.uniform(500, 5000)
            fees = gross * rng.uniform(0.05, 0.15)
            other = rng.uniform(50, 200)
            event[e][m] = {"gross": gross, "fees": fees, "other": other}
            measure[e][m] = (gross - fees) * (1 + rng.gauss(0, 0.01))
    cands, universe = evaluate_family(measure, event, ["fees", "gross", "other"])
    qv = perm_family_q(measure, event, ["fees", "gross", "other"], universe, cands)
    report("b1 true-difference (12 entities)", "gross - fees", cands, qv)

    # b2 — support gameability: 'partial' term exists on half the entities only.
    event, measure = {}, {}
    for i in range(20):
        e = f"E{i:02d}"
        event[e], measure[e] = {}, {}
        for m in months:
            base = rng.uniform(500, 5000)
            row = {"base": base, "noise": rng.uniform(50, 200)}
            if i < 10:  # the trap term is only ever present on 10/20 entities
                row["partial"] = base * (1 + rng.gauss(0, 0.001))
            event[e][m] = row
            measure[e][m] = base * (1 + rng.gauss(0, 0.01))
    cands, universe = evaluate_family(measure, event, ["base", "noise", "partial"])
    part = next(c for c in cands if c.name == "partial")
    own_n = sum(1 for e, r in part.residuals.items() if r != float("inf"))
    own_lcb = wilson_lcb(part.votes, own_n)
    print(
        f"\n=== b2 support gameability ===\n"
        f"  'partial' own-subset denominator: {part.votes}/{own_n} → LCB {own_lcb:.3f} "
        f"(would rank at/near the top — GAMEABLE)\n"
        f"  'partial' common denominator:     {part.votes}/{part.n_common} → LCB {part.lcb:.3f}"
    )
    report("b2 (common denominator ranking)", "base", cands, None)

    # b3 — small N: 3 entities, ordering must hold though the LCB is wide.
    event, measure = {}, {}
    for i in range(3):
        e = f"E{i}"
        event[e], measure[e] = {}, {}
        for m in months:
            debit = rng.uniform(500, 5000)
            credit = rng.uniform(500, 5000)
            event[e][m] = {"debit": debit, "credit": credit, "net_amount": debit - credit}
            measure[e][m] = debit * (1 + rng.gauss(0, 0.02))
    cands, universe = evaluate_family(measure, event, ["credit", "debit", "net_amount"])
    report("b3 small-N (3 entities)", "debit", cands, None)


def main() -> None:
    print(f"engine constants: MIN_PERIODS={MIN_PERIODS} FIRE_RESIDUAL_MAX={FIRE_RESIDUAL_MAX}")
    rows = leg_a_real()
    leg_b_synthetic()
    print("\n" + "=" * 74)
    print("LEG (c) GAP — verdict per real measure (engine vs FIX#1 vs composite vs truth)")
    print("=" * 74)
    for name, truth, eng, f1, f2 in rows:
        print(f"  {name:<32} truth={truth:<20} engine={eng}  fix1={f1}  fix1+2={f2}")


if __name__ == "__main__":
    main()
