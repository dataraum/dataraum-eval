# DataRaum Eval

Calibration harness for the DataRaum entropy system. This repo owns the **ground
truth**: it proves — fast — that every entropy measurement is *right* (a grounded
statistic), *useful* (actionable for a practitioner), and *stable* (a teach closes
it), and it drives changes to detector code and test data until they are.

**The method doc is [`entropy_eval_architecture.md`](entropy_eval_architecture.md)**
— the tiered test architecture, the measurement contract, and the catalog of every
measurement with its grounded statistic and every CUT with its reason. Read it
before designing or tuning any measurement. This file is the map; that file is
the law. Historical results and the pre-reset saga live in `docs/history.md`.

## You are a data scientist first

The product is analytical correctness, not green tests or compiling code. Hard
rules, each learned the expensive way:

- **No statistic without a name.** Every measurement is grounded in a named,
  established method (KS, Wasserstein, MI, Cramér's V, KL, JSD, PSI,
  Kruskal–Wallis, …) **before** any code is written. Boost curves, sqrt-boosts,
  and piecewise score maps are the smell of skipping this step.
- **No string heuristics where the design calls for statistics or LLM judgment.**
  Pattern-matching on names or value strings is not a detector and not a
  semantic claim.
- **No deterministic overrides of LLM judgments.** Entropy *is* disagreement;
  patching an LLM's answer (or its score) to make a test pass is Goodhart at the
  harness level. Non-determinism is handled with xfail(strict=False) and pooling,
  never with overrides.
- **Recall is ordering, not a point threshold.** Assert injected > clean + margin
  and monotonicity in severity. Never tune an injection ratio, threshold, or
  scoring curve so one fixed dataset crosses 0.3.
- **The 10-minute pipeline is never the dev loop.** Pure math is designed and
  debugged in milliseconds (Tier 1/2 below). Think first, then probe, then build.
  Tier 3 runs once per milestone as a wiring gate.
- **One statistical approach per probe, compared cleanly.** When testing
  alternatives, each gets the same fixture, the same legs, and a reported
  separation margin — not sequential hacking until something fires.

### The ground-first kill gate

No measurement leaves research until its named statistic separates the injected
family from natural variation **by a margin** in a millisecond probe on the
existing fixtures. Pass → build. Fail after **one** grounded attempt → **CUT and
record why** in the catalog. The default outcome of a research idea is CUT;
survival requires a grounded separation result up front. WIP = 1 on the spike
lane. Precedents that died here: `temporal_drift`, `outlier_rate`,
`slice_variance`, the bimodality `unit_consistency`, the DAT-459 stock/flow
trajectory signature.

## The tiered loop

| Tier | Speed | Docker | Proves | Run |
|---|---|---|---|---|
| **1 — unit** | ms | no | the statistic as a pure function over synthetic fixtures: ordering, calibration shape, edge cases, teach-closure | `uv run pytest calibration/unit -q` |
| **2 — recorded** | sec | no | the statistic over frozen real pipeline outputs — `calibration/fixtures/entropy_inputs.sqlite`, loaders in `calibration/unit/fixture.py` | same command |
| **3 — integration** | min | yes | the assembled framework end-to-end — **milestone gate, NOT the dev loop** | `make calibrate` |

Refresh the recorded fixture only when the pipeline's *output shape* changes
(schema/phase change): `python scripts/capture_fixture.py` (one docker run).

## Skills drive the work

| Intent | Skill |
|---|---|
| "would statistic X detect Y?" — any new measurement idea | `/ground` — the kill gate as a procedure |
| a detector misses, over-fires, or needs tuning | `/tune-detector` |
| new injection family, fixture, or ground-truth values | `/evolve-testdata` |
| check detector recall + financial accuracy via the direct read tools | `/investigate` |
| produce + validate a business deliverable | `/deliver` |
| product acceptance of the tool surface | `/accept` |

The MCP server the skills used to drive was retired with the product pivot
(ADR-0002; deleted in DAT-487). The skills now read the engine **as a library**
through `calibration/tools/` — `look` / `measure` / `sql`, all read-only over a
completed run's sidecar. SQL judgment (the old `query` tool's LLM) belongs to
the investigating agent itself.

**Probes are disposable.** They live in `scripts/probes/<ticket-or-slug>/`, never
at the repo root, and are deleted once the verdict (BUILD, or CUT + why) is
recorded in the catalog. No `output_*.log` files at the repo root — logs go under
`output/`.

## Three repos

| Repo | Role | Editable from here |
|---|---|---|
| `vendor/dataraum-testdata` | generates data with known injections → `entropy_map.yaml`, `ground_truth.yaml` | yes |
| `vendor/dataraum-context` | the engine — pipeline, detectors, teach system | yes |
| `dataraum-eval` (this) | strategies, calibration tests, runner | yes |

When editing engine code, the engine's rules apply: read
`vendor/dataraum-context/CLAUDE.md` and `packages/engine/CLAUDE.md` first, and
**read the subsystem you're changing from code — not from memory or this file —
before designing**. Feature branches inside the submodule, commit green work,
update `.claude/handoff.md` there for detector changes. The engine's e2e tests
make real LLM calls — never run them as an iteration loop.

## Running calibration (Tier 3)

The pipeline runs as a Temporal workflow (DAT-344/DAT-370): `calibration.stack`
brings up Postgres + Temporal from the vendor compose as an **isolated docker
project** (`-p dataraum-eval`, remapped host ports via
`calibration/compose.eval-ports.yml`, own volume — it coexists with the shared
cockpit `infra` stack and never touches it; DAT-445). `calibration.worker` runs
the engine worker as a host subprocess (live working-tree code, host `data/` →
host `lake_data/`), and `calibration.runner.run_pipeline` triggers
`addSourceWorkflow` as a Temporal client and awaits the result.

**One runner** — `calibration.run` brings the stack up ONCE (idempotent, **never**
`down -v` in a run), runs each selected strategy in its own workspace, kills any leaked
worker, then asserts. It is the single front door; the old generate/pipeline/run/test
make matrix is gone.

```bash
uv run python -m calibration.run -s detection-v1,clean   # run these, build, assert
uv run python -m calibration.run --all                   # every strategy
uv run python -m calibration.run -s detection-v1 --no-assert
uv run python -m calibration.run --list                  # strategies
uv run python -m calibration.run --reset                 # the ONLY `down -v`; then exit

make calibrate [STRATEGY=<name>]       # thin wrapper → run clean + STRATEGY, assert
make clean                             # local dirs (data/ output/ lake_data/ workspace/)
make reset                             # eval project's PG/Temporal state (the down -v)
```

Library functions (`calibration.runner.generate` / `.run_pipeline`) still exist — the
runner and conftest compose them; the multi-seed clean-bands sweep stays in
`scripts/sweep_clean_seeds.py`.

- Strategy YAML in `strategies/` defines injections (injector, table,
  `detector_id`, params); testdata writes `entropy_map.yaml` listing exactly what
  was injected, and tests assert against it.
- Scores come from `measure_entropy()` aggregation in `conftest.py`
  (`(table, column, detector_id) → score`) — never from PhaseLog.
- Detectors whose phase isn't wired into the current workflow slice are skipped
  via `OUT_OF_SLICE_REASON` in `test_detector_recall.py`; move ids into
  `CURRENT_SLICE_DETECTORS` as phases land.
- `make reset` (≡ `calibration.run --reset`) wipes only the isolated eval project's
  Postgres + Temporal volume; the shared cockpit stack is a separate docker project and
  is untouched — safe to run anytime. It is the ONLY `down -v`; never inside a run.
- Long pipeline runs go to the background — line up other work while they run;
  don't idle.

## Where things live

- Method + measurement catalog (every measure, every CUT and why): `entropy_eval_architecture.md`
- Historical record (pre-reset results, slice log, old learnings): `docs/history.md`
- Active epic state: Jira (DAT-442 and children) + session memory — not this file
- Deliverable specs with tolerances: `deliverables/`
- Engine→eval handoff: `vendor/dataraum-context/.claude/handoff.md`
