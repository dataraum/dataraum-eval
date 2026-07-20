"""DAT-762 attempt 2 — grading. Per GATE.md, and only per GATE.md.

Written before the results landed, so the rules could not be shaped by them.

THE GATE (PASS/FAIL), computed per arm, separately:
  G1  P(correct|high) - P(correct|low) >= 0.25, monotone through medium
  G2  P(correct|high) >= 0.80

REPORTED, no bar attached: precision/recall on `meaningful` (overall, per table),
the confidently-wrong rate (the headline), the confidence distribution and
abstain rate, VH - V on everything, the support strata, and the per-table split.

Two units of analysis, both reported, because GATE.md uses both words:
  * POOLED (per call) — "errors at high confidence / all HIGH CALLS" is per-call
    language, and "non-determinism handled by pooling". This is the primary
    reading for G1/G2.
  * MAJORITY (per candidate x arm) — "majority-of-3". Reported alongside as a
    robustness check. If the two disagree, that is itself a finding.

Error markers are EXCLUDED from every rate and COUNTED in the report.
Ties are reported explicitly and never broken silently.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import judge2  # noqa: E402
import rwd  # noqa: E402

HERE = Path(__file__).parent
CACHE_JSON = HERE / "results_rwd.json"
CACHE_WAL = HERE / "results_rwd.jsonl"

ARMS = ("V", "VH")
CONF_ORDER = ("low", "medium", "high")
CONF_RANK = {c: i for i, c in enumerate(CONF_ORDER)}

THIN = 1000  # n_rows < THIN is the thin stratum. A data fact, fixed before the run.

BASELINE_PRECISION = 0.323  # keep-all
BASELINE_RECALL = 1.000


# ---------------------------------------------------------------- load


def load_results() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if CACHE_JSON.exists():
        out.update(json.loads(CACHE_JSON.read_text()))
    if CACHE_WAL.exists():
        for line in CACHE_WAL.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            out[rec["key"]] = rec
    return out


def pct(x: float) -> str:
    return f"{x:6.1%}"


def ratio(num: int, den: int) -> str:
    return f"{num}/{den}" if den else "—"


# ---------------------------------------------------------------- metrics


def prf(calls: list[dict]) -> tuple[float, float, int, int, int]:
    """Precision/recall on the POSITIVE class `meaningful`."""
    tp = sum(1 for r in calls if r["pred"] and r["truth"])
    fp = sum(1 for r in calls if r["pred"] and not r["truth"])
    fn = sum(1 for r in calls if not r["pred"] and r["truth"])
    p = tp / (tp + fp) if (tp + fp) else float("nan")
    rec = tp / (tp + fn) if (tp + fn) else float("nan")
    return p, rec, tp, fp, fn


def calibration(calls: list[dict]) -> dict:
    """P(correct | confidence) per bucket + the gate arithmetic."""
    out = {}
    for c in CONF_ORDER:
        sub = [r for r in calls if r["confidence"] == c]
        n = len(sub)
        ok = sum(1 for r in sub if r["pred"] == r["truth"])
        out[c] = {"n": n, "correct": ok, "p": ok / n if n else float("nan")}
    hi, mid, lo = out["high"], out["medium"], out["low"]

    g1_gap = hi["p"] - lo["p"] if hi["n"] and lo["n"] else float("nan")
    # Monotone: high >= medium >= low. An empty medium cannot violate it.
    mono = True
    if hi["n"] and mid["n"] and hi["p"] < mid["p"]:
        mono = False
    if mid["n"] and lo["n"] and mid["p"] < lo["p"]:
        mono = False

    out["g1_gap"] = g1_gap
    out["g1_monotone"] = mono
    out["g1_pass"] = bool(g1_gap >= 0.25) and mono if g1_gap == g1_gap else False
    out["g2_pass"] = bool(hi["p"] >= 0.80) if hi["n"] else False
    out["confidently_wrong"] = (hi["n"] - hi["correct"]) / hi["n"] if hi["n"] else float("nan")
    out["cw_count"] = hi["n"] - hi["correct"]
    out["abstain"] = lo["n"] / len(calls) if calls else float("nan")
    out["non_high"] = (lo["n"] + mid["n"]) / len(calls) if calls else float("nan")
    return out


def report_calibration(name: str, calls: list[dict]) -> dict:
    cal = calibration(calls)
    print(f"\n  {name}  (n={len(calls)})")
    for c in ("high", "medium", "low"):
        b = cal[c]
        print(
            f"    P(correct|{c:<6}) = {pct(b['p']) if b['n'] else '     —'}"
            f"   [{ratio(b['correct'], b['n'])}]"
        )
    print(f"    G1  gap high-low = {cal['g1_gap']:+.3f}  (>= 0.25)   monotone={cal['g1_monotone']}"
          f"   -> {'PASS' if cal['g1_pass'] else 'FAIL'}")
    print(f"    G2  P(correct|high) = {pct(cal['high']['p']) if cal['high']['n'] else '—'}"
          f"  (>= 0.80)             -> {'PASS' if cal['g2_pass'] else 'FAIL'}")
    print(f"    confidently-wrong = {pct(cal['confidently_wrong'])}  "
          f"[{cal['cw_count']}/{cal['high']['n']} high calls]   <- the headline")
    print(f"    abstain (low) = {pct(cal['abstain'])}   non-high = {pct(cal['non_high'])}")
    return cal


# ---------------------------------------------------------------- main


def main() -> None:
    res = load_results()
    cands = rwd.exact_candidates()
    truth = {(c["table"], c["lhs"], c["rhs"]): c["meaningful"] for c in cands}

    n_rows = {}
    for c in cands:
        f = judge2.facts(c["table"], c["lhs"], c["rhs"])
        n_rows[(c["table"], c["lhs"], c["rhs"])] = f.n_rows

    expected = len(cands) * len(ARMS) * 3
    errors = [r for r in res.values() if "error" in r]
    valid = [r for r in res.values() if "error" not in r]

    print("=" * 78)
    print("DAT-762 attempt 2 — RWD held-out gate")
    print("=" * 78)
    print(f"expected calls : {expected}")
    print(f"records        : {len(res)}")
    print(f"valid verdicts : {len(valid)}")
    print(f"ERROR MARKERS  : {len(errors)}  (excluded from every rate below)")
    if errors:
        kinds = Counter(r["error"].split(":")[0] for r in errors)
        for k, v in kinds.most_common():
            print(f"    {k}: {v}")
    missing = expected - len(res)
    if missing:
        print(f"MISSING        : {missing}  (never attempted)")

    # ---- pooled per-call view
    calls_by_arm: dict[str, list[dict]] = {a: [] for a in ARMS}
    for r in valid:
        k = (r["table"], r["lhs"], r["rhs"])
        if k not in truth:
            continue
        calls_by_arm[r["arm"]].append(
            {
                **r,
                "pred": r["meaningful"],
                "truth": truth[k],
                "n_rows": n_rows[k],
            }
        )

    # ---- majority per (candidate, arm)
    by_ca: dict[tuple, list[dict]] = defaultdict(list)
    for r in valid:
        by_ca[(r["table"], r["lhs"], r["rhs"], r["arm"])].append(r)

    maj_by_arm: dict[str, list[dict]] = {a: [] for a in ARMS}
    ties: list[tuple] = []
    partial: list[tuple] = []
    conf_3way: list[tuple] = []
    for (t, l, rh, arm), reps in by_ca.items():
        k = (t, l, rh)
        if k not in truth:
            continue
        votes = [r["meaningful"] for r in reps]
        n_true, n_false = sum(votes), len(votes) - sum(votes)
        if len(reps) < 3:
            partial.append((t, l, rh, arm, len(reps)))
        if n_true == n_false:  # only reachable when an error removed a rep
            ties.append((t, l, rh, arm, len(reps)))
            continue
        pred = n_true > n_false

        # Confidence: majority label; all-distinct -> median (the middle rank).
        cc = Counter(r["confidence"] for r in reps)
        top, topn = cc.most_common(1)[0]
        if topn == 1 and len(cc) == 3:
            conf_3way.append((t, l, rh, arm))
            conf = sorted(reps, key=lambda r: CONF_RANK[r["confidence"]])[len(reps) // 2]["confidence"]
        else:
            conf = top
        maj_by_arm[arm].append(
            {"table": t, "lhs": l, "rhs": rh, "arm": arm, "pred": pred,
             "truth": truth[k], "confidence": conf, "n_rows": n_rows[k]}
        )

    print(f"\nties (verdict split, excluded)      : {len(ties)}")
    for t in ties:
        print(f"    {t}")
    print(f"partial (<3 valid reps, kept)       : {len(partial)}")
    print(f"3-way-distinct confidence (medianed): {len(conf_3way)}")

    # ================================================================ THE GATE
    print("\n" + "=" * 78)
    print("THE GATE — calibration. PASS requires G1 AND G2, per arm.")
    print("=" * 78)
    print("\n--- PRIMARY: pooled per call ---")
    gate = {}
    for a in ARMS:
        gate[a] = report_calibration(f"arm {a}", calls_by_arm[a])

    print("\n--- ROBUSTNESS: per candidate, majority-of-3 ---")
    gate_maj = {}
    for a in ARMS:
        gate_maj[a] = report_calibration(f"arm {a}", maj_by_arm[a])

    print("\n" + "-" * 78)
    for a in ARMS:
        p = gate[a]["g1_pass"] and gate[a]["g2_pass"]
        pm = gate_maj[a]["g1_pass"] and gate_maj[a]["g2_pass"]
        print(f"  {a:<3} pooled: {'PASS' if p else 'FAIL'}    majority: {'PASS' if pm else 'FAIL'}")

    # ================================================================ REPORTED
    print("\n" + "=" * 78)
    print("REPORTED — no bar attached")
    print("=" * 78)

    print("\nprecision / recall on `meaningful` (majority-of-3 per candidate)")
    print(f"  baseline keep-all: precision {BASELINE_PRECISION:.3f}  recall {BASELINE_RECALL:.3f}")
    for a in ARMS:
        p, r, tp, fp, fn = prf(maj_by_arm[a])
        acc = sum(1 for x in maj_by_arm[a] if x["pred"] == x["truth"]) / len(maj_by_arm[a])
        print(f"  {a:<3} precision {p:.3f}  recall {r:.3f}  accuracy {acc:.3f}"
              f"   [tp={tp} fp={fp} fn={fn}]  n={len(maj_by_arm[a])}")

    # ---- confidence distribution
    print("\nconfidence distribution (pooled per call)")
    for a in ARMS:
        cc = Counter(r["confidence"] for r in calls_by_arm[a])
        n = len(calls_by_arm[a])
        dist = "  ".join(f"{c}={cc[c]:>4} ({cc[c] / n:5.1%})" for c in ("high", "medium", "low"))
        print(f"  {a:<3} {dist}")

    # ---- VH - V on everything
    print("\nVH - V (pooled per call)")
    for label, fn_ in (
        ("accuracy", lambda cs: sum(1 for r in cs if r["pred"] == r["truth"]) / len(cs)),
        ("precision", lambda cs: prf(cs)[0]),
        ("recall", lambda cs: prf(cs)[1]),
        ("P(correct|high)", lambda cs: calibration(cs)["high"]["p"]),
        ("confidently-wrong", lambda cs: calibration(cs)["confidently_wrong"]),
        ("abstain (low)", lambda cs: calibration(cs)["abstain"]),
        ("G1 gap", lambda cs: calibration(cs)["g1_gap"]),
    ):
        v, vh = fn_(calls_by_arm["V"]), fn_(calls_by_arm["VH"])
        print(f"  {label:<20} V={v:+.3f}  VH={vh:+.3f}   VH-V={vh - v:+.3f}")

    # ---- support strata
    print("\n" + "=" * 78)
    print(f"STRATIFIED BY SUPPORT — n_rows < {THIN} (thin) vs >= {THIN}")
    print("=" * 78)
    thin_n = sum(1 for c in cands if n_rows[(c["table"], c["lhs"], c["rhs"])] < THIN)
    print(f"  thin: {thin_n}/{len(cands)} candidates   thick: {len(cands) - thin_n}/{len(cands)}")
    print("  On the thin stratum the honest verdict is LOW CONFIDENCE — whether the")
    print("  judge produces it is the point.")
    for stratum, keep in (("THIN  (n_rows < 1000)", lambda r: r["n_rows"] < THIN),
                          ("THICK (n_rows >= 1000)", lambda r: r["n_rows"] >= THIN)):
        print(f"\n--- {stratum} ---")
        for a in ARMS:
            sub = [r for r in calls_by_arm[a] if keep(r)]
            if not sub:
                continue
            cal = report_calibration(f"arm {a}", sub)
            msub = [r for r in maj_by_arm[a] if keep(r)]
            if msub:
                p, r_, tp, fp, fn = prf(msub)
                base = sum(1 for x in msub if x["truth"]) / len(msub)
                print(f"    precision {p:.3f}  recall {r_:.3f}  (base rate {base:.3f}, n={len(msub)})")
            _ = cal

    # ---- per table
    print("\n" + "=" * 78)
    print("PER TABLE — never pooled into a headline")
    print("=" * 78)
    print("  TRAPS named by GATE.md: hospital 22/22 all-meaningful (always-yes scores")
    print("  100%); t_biocase_gathering 44/0 none-meaningful (always-no scores 100%).")
    print("  A judge that merely learned the domain shows up here.\n")
    tables = sorted({c["table"] for c in cands})
    print(f"  {'table':<44} {'n':>3} {'base':>5} | "
          + " | ".join(f"{a:<28}" for a in ARMS))
    print(f"  {'':<44} {'':>3} {'':>5} | " + " | ".join(f"{'acc  prec  rec   P(c|hi)':<28}" for a in ARMS))
    for t in tables:
        tc = [c for c in cands if c["table"] == t]
        base = sum(1 for c in tc if c["meaningful"]) / len(tc)
        cells = []
        for a in ARMS:
            sub = [r for r in maj_by_arm[a] if r["table"] == t]
            if not sub:
                cells.append(f"{'—':<28}")
                continue
            acc = sum(1 for x in sub if x["pred"] == x["truth"]) / len(sub)
            p, r_, *_ = prf(sub)
            pooled = [r for r in calls_by_arm[a] if r["table"] == t]
            cal = calibration(pooled)
            phi = cal["high"]["p"]
            cells.append(
                f"{acc:.2f}  {p if p == p else float('nan'):.2f}  "
                f"{r_ if r_ == r_ else float('nan'):.2f}  "
                f"{phi if phi == phi else float('nan'):.2f}".ljust(28)
            )
        print(f"  {t[:44]:<44} {len(tc):>3} {base:5.2f} | " + " | ".join(cells))
    print("\n  (nan = that cell is undefined: no positives predicted, or no calls in the bucket)")


if __name__ == "__main__":
    main()
