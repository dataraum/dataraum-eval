"""DAT-744: generate the lever-grid corpora for P5.

RUN FROM THE REPO ROOT ENV (python >=3.14, has testdata):

    uv run python tfm/phase2/generate_lever_corpora.py

Design: price_level lever at period_k=36 of 48 months, factor grid spanning
a support region plus far out-of-support probes. Same-seed baselines are the
exact counterfactuals (RNG-stream identity proven in testdata
tests/test_generators.py::test_price_level_lever_is_exact_counterfactual).

- support grid (context worlds for the what-if leg): 0.85..1.20
- held-out in-support query world: 1.10 (interior, never in context)
- out-of-support query worlds: 0.50, 1.50 (far outside the observed range)
- baselines: factor absent (lever=None), same seeds — these double as the
  P5 forecast-leg counterfactuals.
"""

from __future__ import annotations

from pathlib import Path

from testdata.scenarios.runner import run_scenario

TFM_DATA = Path(__file__).resolve().parents[2] / "data" / "tfm"

SEEDS = (42, 43)
MONTHS = 48
PERIOD_K = 36
SUPPORT = (0.85, 0.90, 0.95, 1.05, 1.15, 1.20)
HELD_OUT_IN = (1.10,)
OUT_OF_SUPPORT = (0.50, 1.50)


def main() -> None:
    for seed in SEEDS:
        base = TFM_DATA / f"p5-base-s{seed}"
        print(f"[gen] baseline seed={seed} -> {base}")
        run_scenario(
            "month-end-close", strategy_name="clean", seed=seed, months=MONTHS, output_dir=base
        )
        for factor in (*SUPPORT, *HELD_OUT_IN, *OUT_OF_SUPPORT):
            out = TFM_DATA / f"p5-f{factor:.2f}-s{seed}"
            print(f"[gen] lever factor={factor} k={PERIOD_K} seed={seed} -> {out}")
            run_scenario(
                "month-end-close",
                strategy_name="clean",
                seed=seed,
                months=MONTHS,
                output_dir=out,
                lever={"type": "price_level", "period_k": PERIOD_K, "factor": factor},
            )
    print("[gen] done")


if __name__ == "__main__":
    main()
