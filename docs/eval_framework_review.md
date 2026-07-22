# DataRaum Eval — Framework Architecture Review

*A decision doc. Not the method law (`entropy_eval_architecture.md`) and not the charter
(`CLAUDE.md`) — this is a step back to look at the **harness as software**: what it is,
where it's ad-hoc, how the field builds this, and what to do next. Grounded in the
DAT-680 "Eval 2.0" epic.*

Status: draft for decision · 2026-07-22

---

## 0. Why this exists

Recent work (the Phase-4 detector nets, the wild lane, the scoreboard) was all built
**inside** the existing harness, taking its shape as fixed. That is execution, not
architecture. The gaps that never got touched:

- **One vertical** (finance), hard-wired; a second exists only as a hand-authored map for wild data.
- **No injection / run / result-caching strategy** — every Tier-3 run is all-or-nothing from scratch; the one cache is a 22 MB committed SQLite.
- **No architecture design** — the seams (attack / detector-run / oracle) exist only as convention; nothing enforces them.
- **Dead code** — confirmed below: two orphan runners, a non-test "test", orphan strategies, a whole research subproject, 12 probe dirs.

This doc maps the as-built system honestly, scans how the field builds this kind of
harness, and lays out options — so the next move is a decision, not more accretion.

### The verdict up front

**The harness is not throwaway, but its plumbing is.** The hard, domain-specific part —
named-statistic injections with ground truth on *relational, cross-table finance data* —
is genuinely ahead of most public benchmarks; that is the asset. What's missing is
**generic harness plumbing** (versioned detectors/oracles, an immutable results store,
content-addressed caching + replay, disciplined non-determinism handling, vertical
generalization) — every piece of which is solved in existing open-source tools.

So the recommendation is neither "keep hacking" nor "rewrite": **design the target
architecture as an assembly of borrowed patterns, then migrate the plumbing in bounded
steps while keeping the assertion grammar and the injection asset intact.** And the one
DAT-680 principle to revisit is *"no new framework"* — it was right about assertions and
wrong about plumbing, and conflating the two is why the plumbing never got built (§4).

---

## 1. What we have (as-built)

### 1.1 The three tiers — enforced by convention, not by a gate

| Tier | Cost | Runs | Where |
|---|---|---|---|
| **1 — unit** | ms, no docker | the statistic as a pure function over synthetic rows; loader/ledger/scoreboard logic; CUT pins | `calibration/unit/test_*.py` (pure) |
| **2 — recorded** | sec, no docker | the statistic over frozen real pipeline outputs | `calibration/unit/test_*_recorded.py` over `fixtures/entropy_inputs.sqlite` |
| **3 — integration** | min, docker+Temporal+**LLM** | the assembled framework end-to-end | `calibration/test_*.py` (24 files), LLM ones marked `@pytest.mark.llm` |

**There is no tier marker or automatic tier gate.** `pyproject.toml` defines only `llm`
and `slow` markers and `testpaths=["calibration"]`. Tier membership is *directory
placement* plus a soft self-skip: a Tier-3 oracle with no completed run **skips** (via
`conftest._require_pipeline_run`) rather than being excluded. `plain pytest calibration/`
collects everything; the expensive tests quietly stand down. The only hard guard is
`unit/test_no_pipeline_from_tests.py` (a test must never drive a pipeline) — that protects
the *token budget*, not tier integrity.

### 1.2 The Tier-3 data flow

`run.py` (the single front door) brings the isolated docker project up **once**
(`-p dataraum-eval`, remapped ports, own volume; never `down -v` in a run), then per
strategy:

1. **generate** — `runner.generate` → testdata writes `data/<s>/*.csv` + `entropy_map.yaml` (recall truth) + `ground_truth.yaml` (financial values) + `metadata_truth.yaml` (agent-layer truth).
2. **drive** — `runner._drive_workflows` runs three Temporal workflows on one host worker: `addSourceWorkflow` (import→type→table/source detectors) → `beginSessionWorkflow` (relationships, `semantic_per_table`, promotes the catalog head) → `operatingModelWorkflow` (validation SQL → `operating_model_detect` → cycles → metrics). An OM failure is **recorded, not aborted**, so earlier results survive.
3. **sidecar** — writes `output/<s>/calibration_run.json` (run_id + source_ids): the only file linking the pytest pass to Postgres state.
4. **assert** — shells `pytest calibration/ --strategy <s>`; `conftest` reads **head-resolved** rows from the `current_entropy_objects` view (never max over raw rows, so a teach re-run's score *drop* is visible), keeps MEASURED rows only (abstention split, DAT-853), buckets by target into `DetectorScores`. (`measure_entropy()` is gone — DAT-399/408 — though docstrings still name it.)
5. **summary** — folds `oracle_coverage.json` + the fire-rate scoreboard into a printed report.

### 1.3 The pieces

- **Attack** — `strategies/*.yaml` (20) → testdata injectors (`break_referential_integrity`, `corrupt_types`, `inject_stock_flow_probes`, …) → the three truth files.
- **Oracles** — 24 Tier-3 `test_*.py` (recall, precision, teach-closure, agent-label, roles, relationships, cycles, metrics, grounding, bus-matrix) + ~19 Tier-1/2 `unit/test_*.py`.
- **Support** — `scoreboard.py` (wild fire-rate grade), `coverage.py` + `oracle_coverage.json` (per-oracle ledger + baseline diff), `findings.py` + `graduate_finding.py` + `docs/generator_backlog.yaml` (the authenticity loop), `corpora.py` + `corpus_registry.yaml` (wild `(corpus→vertical)` map).
- **Engine-as-library reads** — `tools/look|measure|sql` over a completed run (the post-MCP surface; MCP retired ADR-0002/DAT-487, only docstrings remain).

### 1.4 Caching / run economy — the honest picture

**One durable cache exists:** `fixtures/entropy_inputs.sqlite` (22 MB, git-tracked),
built by `capture_fixture.py` from one docker run — it snapshots the engine's
measurement-input/output Postgres tables + raw CSV values across 5 strategies. Every
Tier-2 test reads it. `--raw-only` rebuilds just the raw values with no docker (this is
what made the Phase-4 nets free).

**Everything else is all-or-nothing.** A re-run re-drives the *entire*
addSource→beginSession→operatingModel chain and re-scores from scratch — **no phase-level
memoization, no content-addressed cache, no incremental execution.** Pipeline outputs live
in the eval project's Postgres + DuckLake/S3 and survive only until `--reset`. The token
budget is enforced **socially** (charter rules), not by the harness. The only "reuse" is
(a) head-resolution picking the latest promoted head so a teach *re-run* exposes a drop,
and (b) the assert pass *reading* a completed run instead of re-driving it.

### 1.5 Verticals

**Finance is hard-wired** — `vertical="finance"` is the default on every workflow input and
teach primitive; finance concepts live in the engine ontology, so the synthetic lane needs
no framing. **A second vertical exists only for wild data**, via
`frame_wild_vertical.VERTICALS = {"rel-f1": MOTORSPORT}` — 12 hand-written concept dicts
read off the corpus schema, written as `Concept` rows into the workspace, **explicitly
product config, not ground truth** (nothing is graded against it). Adding a vertical today
= fetch corpus + hand-author its concept list + register the pairing + derive structural
truth. The synthetic side is deliberately finance-only (`entropy_eval_architecture.md`
forbids a second synthetic vertical — DAT-690/691 cancelled as "same-designer bias").

---

## 2. The four gaps, with evidence

### 2.1 One vertical, hand-authored
The `Finding` model is vertical-scoped, so the *data model* isn't finance-only — but every
generator, every truth file, and the only synthetic ontology are finance. A new vertical is
hand-authored concept-by-concept. This is **DAT-689 (P2 vertical protocol), status
Backlog** — the unexecuted core of the gap. The field's answer is *profiling-to-suggest*
(§3, pattern 6): profile a domain's clean data → propose checks → human ratifies, instead of
hand-writing each.

### 2.2 No injection / run / cache strategy
- **Injections** are static one-per-line YAML. "Comprehensive" strategies (`detection-v1`) inject everything at once, which **confounds signals** (the cross-table net had to reckon with benford + temporal-drift + payment-break all hitting the same reconciliation). No parameterized severity sweeps, no per-defect-type isolation, no recall-vs-rate curves.
- **Runs** are all-or-nothing (§1.4). No caching of intermediate pipeline artifacts; no replay; re-running a strategy re-executes every phase.
- **Result caching** is one frozen fixture + social budget discipline. There is no results store, so "did this regress?" is not a query — it depends on a human re-running and remembering.

### 2.3 No architecture — the seams are implicit
The three real seams — **attack** (injection/fixture), **detector-run** (replay at T1/2 vs
pipeline at T3), **oracle** (score→verdict) — are enforced only by convention. `measure_entropy()`
is the compute leg, but the *threshold/verdict* leg is inlined into each `test_*.py`, so a
threshold change lives next to detector-specific assertion code instead of behind a stable
interface. There is no detector/oracle **version**, no immutable **run record**, no
**scoreboard store** — the scoreboard is recomputed and printed, never retained.

### 2.4 Dead code (confirmed, evidence in Appendix A)
Two orphan runners (`phase_contract.py`, `batch.py` — zero importers), a non-test "test"
(`test_report.py` — no `def test_`), 5 orphan strategies (`baseline`, `tfm-*`), a whole
standalone research subproject (`tfm/`), 12 disposable probe dirs (2 untracked), and stale
report YAMLs. None is imported by the harness. This is a same-day cleanup, independent of
the big decision.

---

## 3. Prior art — how the field builds this

Structurally, our harness is **ADBench / REIN** (inject *named defect types* into clean
relational data; measure per-type recall/precision **curves**) **fused with UK AISI Inspect**
(a tiered *dataset → solver → scorer* harness that must economize expensive, non-deterministic
LLM calls). Nobody ships exactly that combination — which is why it's home-grown — but every
missing plumbing piece is solved elsewhere. The borrowable patterns, in priority order:

1. **Dataset → Solver → Scorer as the immovable contract** (Inspect; deepchecks' Check/Condition/Suite). Split the oracle into *compute-the-statistic* / *threshold-verdict* / *aggregate-scoreboard* so a threshold change can never reach detector code — exactly the charter's "a red result is a finding, never a relaxed oracle," enforced structurally.
2. **Versioned detectors/oracles + an immutable, diffable results store** (lm-eval task VERSIONs with stability unit-tests; Braintrust experiments; Deequ Metrics Repository). "Did it regress?" becomes a query against history; a statistic/threshold change is *visibly a new version* and never silently invalidates a scoreboard. This is the principled replacement for a hand-maintained findings backlog.
3. **Content-addressed caching, replay-by-default** (Inspect caches on hash of full input + gen-config + epoch; promptfoo disk-caches by default with an explicit bust). Generalize the Tier-2 fixture: hash the full input of every expensive step *keyed on engine version*, serve from cache unless `--refresh`. Makes "never re-run the pipeline as a loop" mechanical, not social.
4. **Non-determinism via epochs + a score reducer, never overrides** (Inspect). Run the LLM leg N times, combine with a named reducer (mean/median/vote), and treat *reducer variance as a reported statistic* — the disciplined home for our `xfail(strict=False)` + pooling, and the honest place to quantify the ~25% 1:1-FK-orientation flips.
5. **Declarative per-detector example cases as the Tier-1 substrate** (Great Expectations ships `{input, params, expected}` cases run across backends, gated by a maturity ladder; pandera *synthesizes* boundary data from a schema). Pair with **recall-vs-injection-rate curves (REIN)** and **per-anomaly-type grading (ADBench: local/global/dependency/cluster)** so recall is asserted as *ordering + monotonicity*, matching the charter.
6. **Profiling-to-suggest for new verticals** (Deequ Constraint Suggestion, GX Profiler — profile *clean* data → propose checks → human ratifies). This is the concrete mechanism behind "every wild break graduates into a synthetic injection + oracle": profile-suggest gives the candidate oracle, the injection makes it known-answer.

Two cautions from the literature: **(a)** define each injection relative to a *constraint*
(FD / denial constraint) so the constraint doubles as the oracle, and label which injections
are guaranteed-detectable (BART's detectability) so a by-construction-undetectable miss isn't
scored as a failure. **(b)** pattern-injected errors are "too clean" (arXiv 2507.10934) —
which is exactly why the two-tier policy (synthetic backbone + wild frontier) is right and
should stay.

Sources: Inspect (inspect.aisi.org.uk), lm-evaluation-harness, promptfoo, Braintrust, Great
Expectations, pandera, Deequ, deepchecks, Evidently, Soda; benchmarks BART (VLDB'16), Jenga
(EDBT'21), REIN (EDBT'23), ADBench (NeurIPS'22).

---

## 4. The decision that unlocks the rest: revisit "no new framework"

DAT-680's first design principle is **"No new framework. Every assertion reuses the existing
grammar."** That principle is **half-right, and the half that's wrong is why we're here.**

- **Right about assertions.** Ordering + margin, measured clean bands, `xfail(strict=False)`, pooling C/U, named statistics — that grammar is good and should not be reinvented. Keep it.
- **Wrong about plumbing.** "No new framework" was read as "no new *anything*," so the harness plumbing — versioning, a results store, a cache layer, seam enforcement, a vertical protocol — was never designed. But that plumbing *is* the framework, and it's the thing the field has already solved (§3).

So the reframe that moves us forward: **freeze the assertion grammar, build the missing
plumbing.** That is not a contradiction of DAT-680 — it's the correction that lets DAT-680's
P1/P2/P3 actually land on solid ground instead of accreting more `test_*.py` onto convention.

---

## 5. Options

**Option A — Status quo (keep hacking).** Add oracles/nets inside the current harness.
*Cost:* every new strategy risks confounded signals; regressions are caught only by whoever
re-runs; dead code and convention-seams keep growing; the vertical gap never closes. This is
the path that prompted this doc.

**Option B — Bounded refactor + plumbing (recommended).** Keep the assertion grammar and the
injection asset; extract the three seams; add the six patterns incrementally; land the
vertical protocol; delete dead code. Concretely, sequenced:
  1. **Same-day:** delete dead code (Appendix A); fix the `test_ground_truth` VARCHAR crash surfaced today (an oracle that blows up on a type-corruption strategy).
  2. **Seam + store:** make the *threshold-verdict* leg a separate versioned object; add an immutable run-record + scoreboard store (patterns 1, 2). Small, high-leverage — turns "did it regress?" into a query.
  3. **Cache:** content-address the expensive steps keyed on engine version, replay-by-default (pattern 3). Directly attacks the run-economy pain.
  4. **Injection strategy:** per-defect-type isolated strategies + severity sweeps → recall-vs-rate curves (pattern 5); retire confounded "comprehensive" strategies from the graded set.
  5. **Vertical protocol:** profiling-to-suggest for a second vertical (pattern 6) — this is DAT-689, finally on a foundation that supports it.

**Option C — Rewrite on Inspect (or similar).** Adopt an off-the-shelf harness wholesale.
*Cost:* large migration; Inspect is built for model evals, not a docker+Temporal data
pipeline with cross-table relational ground truth — we'd fight its assumptions. The domain
asset (relational injections + ground truth) doesn't come from Inspect anyway. **Not
recommended** — borrow its *patterns* (Option B), not its runtime.

**Recommendation: Option B, in that sequence.** It redeems the sunk work (the assertion
grammar and injections survive), fixes the economics (cache + store) before adding scope, and
puts the vertical protocol on a foundation instead of a hand-authored map.

---

## 6. Target architecture (sketch, for the decision — not a build order)

```
  ATTACK (dataset)            DETECTOR-RUN (solver)         ORACLE (scorer)
  ────────────────           ─────────────────────         ────────────────
  injection family    ─┐     Tier 1/2: replay cached  ┐    compute-statistic (named)
  + params (severity)  ├──▶   engine outputs (free)    ├──▶ threshold-verdict (versioned)
  + constraint (=GT)  ─┘     Tier 3: drive pipeline    ┘    aggregate-scoreboard (stored)
        │                          │                              │
        └── entropy_map/           └── content-addressed          └── immutable run record
            metadata_truth             cache, keyed on                + baseline diff
            (recall truth)             (inputs, engine-version)       (regression = query)
```

The three seams become **immovable interfaces**; detectors and oracles carry **versions**;
runs are **immutable records** in a store; the cache is **content-addressed and
replay-by-default**; non-determinism is **epochs + reducer**; new verticals come from
**profiling-to-suggest**. Every one of these is a named pattern from §3.

---

## 7. Grounding in DAT-680

DAT-680 already diagnosed the disease ("all variety is seed × strategy × schema-transform
over one immutable finance schema — we only test what we thought to inject") and scanned the
same benchmark landscape (SchemaPile, RelBench, CTU PKDD'99, Raha/Baran, ADBench-adjacent).
Its three moves map cleanly onto Option B — with one correction (the "no new framework"
reframe, §4) and one observation (**the code has run ahead of the tickets**: much of P1's
agent-grading already exists as `test_*_e2e.py` while DAT-682/684/685/686/687 still read "To
Do").

| DAT-680 move | Status (code vs ticket) | This doc |
|---|---|---|
| **P1** — grade the agent layer (DAT-681…688) | Largely **built ad-hoc**; tickets open; `metadata_truth`, agent-label/roles/relationships/cycles oracles exist | Fits Option B seam+store; close the tickets or re-scope to what's left (DAT-687 answer-path is the live gap) |
| **P2** — vertical-agnostic testdata (DAT-689) | **Backlog** — the real gap; verticals DAT-690/691/698 **Cancelled** | Option B step 5 = profiling-to-suggest (pattern 6) |
| **P3** — wild-data gate (DAT-692/693/694) | rel-f1 lane **done**; monthly gate + Raha/Baran **Backlog** | Option B benefits directly from the cache + store |

DAT-680's anti-token-graveyard principles (kill-gate, synthetic-primary, curation checklist)
**stay** — Option B strengthens them (content-addressed replay *is* the mechanical form of
"never re-run as a loop").

---

## 8. Immediate, decision-independent wins

Regardless of A/B/C, these are safe to do now:
- **Delete the dead code** in Appendix A (orphan runners, non-test "test", orphan strategies, stale reports; probe dirs per the charter's own disposability rule).
- **Fix `test_ground_truth`'s VARCHAR crash** — today's `detection-typing-v1` run made the eval's *own* offline ground-truth SQL throw a DuckDB BinderException (`SUM(CASE WHEN … THEN debit …)` mixes VARCHAR with an INTEGER literal because `debit` is type-corrupted). An oracle that crashes on a strategy it wasn't born with is Exhibit A for §2.3.

---

## Appendix A — Dead-code list (evidence-backed)

**Confirmed orphan (zero importers / no oracle / no runner path):**
- `calibration/phase_contract.py` — zero importers; standalone `__main__` only.
- `calibration/batch.py` — zero importers; legacy "S0 spine" runner superseded by `run.py`; sole caller of `outcomes.label`.
- `calibration/test_report.py` — no `def test_` functions (vacuous under pytest); report generator with pre-reset default strategy `zone1-detection-v1`.
- `strategies/baseline.yaml` — no oracle ref; self-labels "reference for zone1-detection-v1"; pre-reset injector names.
- `strategies/tfm-{clean,low,medium,high}.yaml` — 0 oracle refs; mirrors for the standalone `tfm/` subproject.
- `tfm/` — self-contained TFM research subproject (own pyproject/uv.lock); no `calibration/` import.
- `strategies/detection-stockflow-cal-v1.yaml`, `detection-stockflow-events-ambiguous-v1.yaml` — referenced only by `scripts/calibrate_*` ablation scripts, never an oracle.
- `scripts/probes/` — 12 dirs, disposable by charter; 2 untracked (`dat850-edge-kind`, `dat853-validation`). Keep only the Sarawagi reference probe (cited in the method doc).
- `calibration/reports/zone1-detection-v1_*.yaml` + two dated report `.md`s — historical, not read by code.

**Manual-only (not dead, but unwired):** `scripts/calibrate_reliabilities.py`,
`check_reliability_consumption.py`, `dump_intent_readiness.py`, and the
`calibrate_wave2/temporal/structural_ablation/teach_protocol/band_impact_ablation` chain.

**Not dead (myth-busting):** "retired MCP references" are **docstrings only** in
`tools/{__init__,measure,sql}.py` — no live MCP code remains.

---

## Appendix B — Key file references

- Front door / lane dispatch: `run.py` (`_dispatch`, `run`; wild lane `_run_one_wild`).
- Isolated docker project: `stack.py`, `compose.eval-ports.yml`.
- Temporal drive + 6 teach-and-rerun primitives: `runner.py` (`_drive_workflows`, `teach_*`).
- Head-resolved, MEASURED-only score read + stale-sidecar fail-loud: `conftest.py`.
- Recall grammar + slice/CUT/DEMOTE constants: `test_detector_recall.py`.
- Fixture capture (the one cache): `scripts/capture_fixture.py`; loaders `unit/fixture.py`.
- Method law + measurement catalog: `entropy_eval_architecture.md`.
