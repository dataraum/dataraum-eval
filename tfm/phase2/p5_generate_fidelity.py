"""DAT-744 Part 3: generate() fidelity gate for app #3 (scenario row generation).

Pre-registered kill gate (fail once -> CUT, per the ground-first rule):
TabICLUnsupervised.generate() must produce journal-line rows whose

  (a) per-column marginals sit within 2x the natural seed-to-seed distance
      (KS for numerics, JSD for categoricals) of held-out real rows, on
      >= 80% of columns, AND
  (b) ledger structure holds: net_amount = debit - credit within 1% of |net|
      on >= 90% of rows, and debit/credit mutual exclusivity (exactly one
      side zero, as in every clean row) on >= 90% of rows.

Rows violating ledger identities are useless for cycle-grain scenario
simulation, hence (b) is structural, not cosmetic.

Setup: fit on 2,000 clean journal_lines rows (p3-clean-s42; columns
account_id, debit, credit, net_amount, cost_center — keys dropped), generate
2,000 rows. Yardstick: distance(real s43, held-out s42) — what natural
variation looks like between two worlds of the same DGP.

    cd tfm/phase1 && uv run python ../phase2/p5_generate_fidelity.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps

PHASE1 = Path(__file__).resolve().parents[1] / "phase1"
sys.path.insert(0, str(PHASE1))

import data  # noqa: E402
import engines as eng  # noqa: E402
import results as rs  # noqa: E402

PROBE = "p5_generate_fidelity"
SEED = 42
N = 2000
COLS = ["account_id", "debit", "credit", "net_amount", "cost_center"]


def sample(corpus: str, n: int, offset: int) -> pd.DataFrame:
    df = data.load_table(corpus, "journal_lines")[COLS]
    rng = np.random.default_rng(SEED + offset)
    idx = rng.choice(len(df), size=min(n, len(df)), replace=False)
    return df.iloc[idx].reset_index(drop=True)


def marginal_distances(a: pd.DataFrame, b: pd.DataFrame) -> dict[str, float]:
    out: dict[str, float] = {}
    for col in a.columns:
        if pd.api.types.is_numeric_dtype(a[col]):
            x = a[col].astype(float).dropna().to_numpy()
            y = b[col].astype(float).dropna().to_numpy()
            out[col] = float(sps.ks_2samp(x, y).statistic)
        else:
            cats = sorted(set(a[col].dropna()) | set(b[col].dropna()))
            p = a[col].value_counts(normalize=True).reindex(cats).fillna(0).to_numpy()
            q = b[col].value_counts(normalize=True).reindex(cats).fillna(0).to_numpy()
            out[col] = float(sps.entropy((p + q) / 2) - (sps.entropy(p) + sps.entropy(q)) / 2)  # JSD
    return out


def structure(df: pd.DataFrame) -> dict[str, float]:
    debit = pd.to_numeric(df["debit"], errors="coerce").fillna(0).to_numpy(dtype=float)
    credit = pd.to_numeric(df["credit"], errors="coerce").fillna(0).to_numpy(dtype=float)
    net = pd.to_numeric(df["net_amount"], errors="coerce").to_numpy(dtype=float)
    resid = np.abs(net - (debit - credit))
    tol = np.maximum(np.abs(net) * 0.01, 0.01)
    formula_ok = float(np.mean(resid <= tol))
    exclusive = float(np.mean((debit == 0) ^ (credit == 0)))
    return {"formula_ok": formula_ok, "exclusivity": exclusive}


def main() -> None:
    fit = sample("p3-clean-s42", N, offset=0)
    holdout = sample("p3-clean-s42", N, offset=1)  # disjoint w.h.p. from 25k rows
    other_world = sample("p3-clean-s43", N, offset=2)

    from tabicl import TabICLUnsupervised

    Xn, _, vocab = eng.encode_for_density(fit)
    uns = TabICLUnsupervised(device=eng.DEVICE)
    with rs.timed() as t:
        uns.fit(Xn)
        synth_enc = uns.generate(n_samples=N)
    synth = eng.decode_from_density(np.asarray(synth_enc), fit.iloc[: len(synth_enc)], vocab)
    synth.columns = fit.columns

    yardstick = marginal_distances(other_world, holdout)
    measured = marginal_distances(synth, holdout)
    ratios = {c: round(measured[c] / max(yardstick[c], 1e-6), 2) for c in COLS}
    within = sum(1 for c in COLS if measured[c] <= 2 * yardstick[c])

    struct_real = structure(holdout)
    struct_synth = structure(synth)

    gate_a = within >= 0.8 * len(COLS)
    gate_b = struct_synth["formula_ok"] >= 0.9 and struct_synth["exclusivity"] >= 0.9
    verdict = "PASS" if (gate_a and gate_b) else "CUT"

    rs.record(
        PROBE, "tabicl2",
        {"n": N, "cols": COLS},
        {
            "verdict": verdict,
            "marginal_ratio_vs_yardstick": ratios,
            "cols_within_2x": f"{within}/{len(COLS)}",
            "structure_synth": struct_synth,
            "structure_real_reference": struct_real,
            "yardstick": {k: round(v, 4) for k, v in yardstick.items()},
            "measured": {k: round(v, 4) for k, v in measured.items()},
        },
        latency_s=t["s"],
    )
    print(f"\nVERDICT: {verdict} (gate_a marginals={gate_a}, gate_b structure={gate_b})")


if __name__ == "__main__":
    main()
