"""DAT-743 Phase 1: generate the probe corpora.

RUN FROM THE REPO ROOT ENV (python >=3.14, has testdata):

    uv run python tfm/phase1/generate_corpora.py

Not a tfm-env module — testdata is not installed there. Corpora are
regenerable artifacts (data/ is disposable); this script is the recipe.

- P1/P4 substrate: clean strategy, 48 months, seeds 42-46 (5 replicate
  histories; 27 accounts x 48 monthly periods each). Longer histories are
  config-only per the design doc (section 8).
- P3 substrate: the vendor's own severity ladder clean/low/medium/high at
  default 12 months, seeds 42-43, entropy_map.yaml row labels included.
"""

from __future__ import annotations

from pathlib import Path

from testdata.scenarios.runner import run_scenario

TFM_DATA = Path(__file__).resolve().parents[2] / "data" / "tfm"

P1_SEEDS = (42, 43, 44, 45, 46)
P3_SEEDS = (42, 43)
P3_STRATEGIES = ("clean", "low", "medium", "high")


def main() -> None:
    for seed in P1_SEEDS:
        out = TFM_DATA / f"clean-48m-s{seed}"
        print(f"[gen] clean months=48 seed={seed} -> {out}")
        run_scenario(
            "month-end-close",
            strategy_name="clean",
            seed=seed,
            months=48,
            output_dir=out,
        )

    for strategy in P3_STRATEGIES:
        for seed in P3_SEEDS:
            out = TFM_DATA / f"p3-{strategy}-s{seed}"
            print(f"[gen] {strategy} months=12 seed={seed} -> {out}")
            run_scenario(
                "month-end-close",
                strategy_name=strategy,
                seed=seed,
                months=12,
                output_dir=out,
            )

    print(f"[gen] done -> {TFM_DATA}")


if __name__ == "__main__":
    main()
