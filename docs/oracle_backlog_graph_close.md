# Oracle backlog — DAT-725 graph-close slice (banked specs, cube-declared)

Handoff from the DAT-725 owner (2026-07-22). Seven oracle specs banked against the
execution cube (DAT-860): each carries its exact `cube.needs(...)` declaration so the
evolved framework can plan cells before any oracle is written. **Nothing here has been
run**; the engine substrate lives on `epic/dat-725-graph-close` (dataraum-context).
**Pin protocol (owner + eval, 2026-07-22 — do NOT wait for the merge):** the moment
DAT-787 integrates, the owner posts the epic-tip SHA on DAT-736 and the eval side pins
`vendor/dataraum-context` to it immediately for oracle authoring + Tier-1/2 iteration.
Graded sweeps re-pin to the merged-main SHA for verdict-store identity — the epic
branch is rebased onto main when main moves, so an epic-tip SHA is a fine dev target
but a bad durable identity (the store's `engine_on_main` field makes off-main
recording self-identifying). Since main hasn't moved all slice, the re-pin is expected
byte-identical — an identity swap only. Companion: the eval-prep brief on
DAT-736 (Jira) and the two new generator items in `generator_backlog.yaml`
(`CAP-measured-in-truth`, `CAP-roleplay-fk-fixture`).

DAT-862 discipline throughout: extending an existing module's assertions is a
**verdict-changing change → bump its `version`**; new modules start at `version=1`.

**Sweep-attention list** (three DELIBERATE graded-surface changes in the slice — oracles
asserting on these surfaces must be updated to the new intended behavior; they are design,
not regressions):
1. GraphAgent driver context: measured-empty renders an explicit "No significant driver
   found." line; abstained rankings never render (rankings now carry
   `status`/`abstain_reason` — loaders must be abstention-aware).
2. The imperative status-binding prompt line is gone; the posted-only scope is now
   INJECTED deterministically into `where_predicates` (groundings on status-bearing
   relations change shape; bypass = a typed `scope.validity` assumption in provenance).
3. Catalogue shared-axes pairing separates role-playing FKs (structural default).

---

## O1 · Temporal coverage, grain, anchor & calendar (P5 / DAT-730)

New module `test_temporal_graph_e2e.py`:

```python
pytestmark = cube.needs(vertical="finance", dataset="*", from_stage="begin_session")
```

Assert over the promoted operating-model graph (GRAPH_TABLE MATCH), never raw tables:

1. **Coverage shape** — for every (relation R, declared time column C) in
   `table_entities.time_columns`, exactly one `temporal_coverage` edge R→C.
   `observed_grain == temporal_column_profiles.detected_granularity` (NEVER
   `measure_aggregation_lineage.period_grain` — that is a config echo). observed_min/max
   == the true data window. `role ∈ {event, attribute}` and `declared_anchor` match the
   declared entry (`declared_anchor` is the time_columns DECLARATION — distinct from the
   operating-model anchor, see 3).
2. **Absence falls loud** — detected grain irregular/unknown ⇒ completeness_ratio,
   expected/actual_periods, last_period_complete all NULL on the edge (never 0 / 1.0).
   A declared-but-unprofiled time column keeps its edge with NULL observed_* (never a
   synthesized "complete").
3. **Trailing partial period** — `last_period_complete=False` for a truncated final
   bucket even when completeness_ratio≈1 and is_stale=False (the AR-NULL-at-MAX-period
   class); True for a consistently-stamped series regardless of final-month length.
   Known sensitivity ceiling (documented in detection.py): catches truncated tails
   (<~50% of typical fill), not merely-short tails — do not write an oracle demanding
   finer resolution than the mechanism defines.
4. **Anchor one-home** — `og_columns.anchor_time_axis` == the lineage-witness axis when
   a witness reconciled it, else the single declared is_anchor=event column; never
   positional. Include the witness≠declared divergence case (the engine has an
   integration fixture shape for it).
5. **Roll-up** — `rolls_up_to` reproduces each drilldown hierarchy's level order
   (level 0 coarsest, finer→coarser; edge keys are level-keyed); alias/role structures
   emit none. Period ladder day→month→quarter→year walkable via the bounded CTE;
   last-complete-quarter derivable from last-complete-month + the declared boundary.
6. **Calendar default stamped** — unset workspace: `fiscal_year_start_month=1`,
   `calendar_source='default'` (visible, never silent); declared: follows the
   declaration, `calendar_source='declared'`.
7. **Dimension ordering** — `og_concepts.ordering='ordered'` where the vertical declares
   it, NULL (⇒ nominal, windows withheld) otherwise; time axes carry no stored ordering
   fact (ordered by construction).

## O2 · Units & additivity projection (P6 / DAT-731)

New module `test_units_additivity_e2e.py`:

```python
pytestmark = cube.needs(vertical="finance", dataset="*", from_stage="operating_model")
```

1. **measured_in coverage** — every measure with a unit column carries a
   `measured_in` edge matching the `measured_in:` generator truth
   (`CAP-measured-in-truth`); label-invariant; **skip (not vacuous-pass) when zero
   edges exist** — grounding recall is /smoke's concern, mirroring
   test_metric_additivity_e2e's skip discipline. Self-denominated columns are
   self-loops with `self_denominated=true`; `dimensionless` yields no edge.
2. **og_additivity parity** — `MATCH (a IS additivity_verdict)` reproduces
   `current_metric_additivity` row-for-row (PLUMBING check only; verdict VALUES are
   already graded by test_metric_additivity_e2e — do not re-grade them). Metric-kind
   verdicts have no inbound `has_additivity` edge (honest under-coverage — a metric has
   no concept vertex).
3. **Cross-unit gate** — on single-currency corpora the drill unit gate is SILENT
   (assert no measure flagged); on a mixed-currency variant the flagged set ==
   `cross_unit` truth. (The gate is per-(fact, column) — a single-currency fact must
   never be flagged because a sibling fact's same-named column is multi-currency.)

## O3 · Metric DAG shapes + walk (P7 / DAT-732)

Extends `test_grounding_e2e.py` (**bump its `version`**; from_stage already
`operating_model`):

1. `_P2_MATCH_SHAPES` gains: `og_metrics` (`MATCH (m IS metric_node)`),
   `og_derives_from` (`metric_node -[derives_from]-> concept_node`),
   `og_has_parameter` (`metric_node -[has_parameter]-> parameter_node` — the parameter
   carries the declared default + `derivation` marker, e.g. days_in_period /
   period_grain).
2. A walk oracle: `metric_node -[derives_from]-> concept_node -[grounded_by]->
   grounding_node` (and on via `uses` to columns) returns > 0 rows —
   **xfail-if-no-metrics-declared** (depends on metrics-phase LLM recall, like the
   existing grounding-enumeration oracle).

## O4 · Validity scope (P8 / DAT-733)

Extends `test_grounding_e2e.py` (same **version bump** — coordinate with O3):

1. `_P2_MATCH_SHAPES` gains `og_validity_filter` + `og_scoped_by` — **CONDITIONED-HARD
   (owner-ruled)**: hard-assert the projection WHEN a measured status cycle exists in
   `detected_business_cycles` (status_column/completion_value/completion_rate all
   non-NULL); skip otherwise. Whether a cycle was detected at all is the cycles recall
   oracle's job; these entries grade only the plumbing.
2. Semantic check in the grounding-batch oracle: every healthy grounding on a
   status-bearing relation carries the posted-only predicate in its `where_predicates`
   **or** a `scope.validity` bypass assumption in its provenance (read both; the
   engine's default-inject vs defer split is deliberate — sweep-attention item 2).

## O5 · Generated validations (P10 / DAT-735)

New module `test_validation_induction_e2e.py`:

```python
pytestmark = cube.needs(vertical="finance", dataset="*", from_stage="operating_model")
```

1. **Induction liveness** — the OM run's `validation_induction` phase completes with
   `generated >= 1` on the finance corpus (a rich promoted graph should yield grounded
   proposals). NOTE the accepted engine limitation: the FIRST OM run serves the PRIOR
   run's cycles/additivity (empty on run 1) — induction proposes from the structural
   substrate + metric DAG alone on run 1; grade accordingly (don't demand
   cycle-informed checks on a first run).
2. **No fabricated grounding** — every `source='generated'` row EXPLAIN-binds through
   the existing validation-phase gate; no generated row references a non-existent
   table/column (the engine membership-validates at induction; this is the
   defense-in-depth read).
3. **nothing_declared unaffected** — a declaring vertical reaches `promoted`; a
   zero-declare framed vertical still reaches `nothing_declared`; induction can never
   flip it (generated ≠ declared — pinned engine-side, assert it end-to-end).
4. **check_type vocabulary** — every persisted validation row's `check_type` ∈ the
   four-value contract (balance|comparison|constraint|aggregate) — mirrors the cockpit
   zod contract; the engine CHECK enforces it, this is the cross-package read.

**Parity oracle (the sweep-#2 gate)** — new module `test_validation_parity_e2e.py`,
same needs line: the nine seed validations regenerate **verdict-identical** from the
DB home vs the pre-migration YAML path on the finance corpus. This grade DECIDES the
YAML deletion. Verdict-stability caveat: during engine probes the sign_conventions
VERDICT flipped failed↔passed across prompt revisions (LLM account-classification
judgment, not bind mechanics) — parity grading should run under the DAT-863
epochs/reducer discipline, not a single draw (open question Q3).

## O6 · Role-separated conformed identity (DAT-788)

New module `test_role_identity_e2e.py` — **blocked on `CAP-roleplay-fk-fixture`**:

```python
pytestmark = cube.needs(vertical="finance", dataset="detection-roleplay-v1", from_stage="begin_session")
```

(Dataset name ruled in Q1 below: a new Tier-A dataset, not a fold-in.)

1. **Recall** — the lineage witness pairs same-role across facts; never cross-pairs
   bill_to ↔ ship_to.
2. **Precision** — no conformed identity fabricated across roles when the judge returns
   role/abstain (`needs_confirmation` surfaced on the abstained cell).
3. **Conform path** — a differently-named same-role pair the judge conforms DOES pair
   (the judge→bus_matrix→graph positive path).
4. **Graph** — `og_conformed_dimension` shows the two roles as distinct axes unless
   conformed; identity signatures are content-derived (`ref:{dim_table_id}:{sorted
   role names}` — never per-run).

## O7 · Cycle direction three-state grading (DAT-856 — the sweep-#3 gate)

Evolves `test_cycles_e2e.py` (**bump its `version`**; needs already declared
`operating_model`) + `metadata_truth`:

1. **Truth**: directed backbone cycles gain `family` + `direction`
   (accounts_payable: family=settlement, direction=outgoing; undirected cycles
   unchanged). This is DECLARED ground truth from the vertical's family declaration —
   not a truth patch (DAT-685; the be67049 revert is the precedent).
2. **read_detected_cycles** surfaces the new `family`/`direction` columns.
3. **test_cycle_recall grades THREE named states** per expected directed cycle:
   - `CORRECT`: member canonical_type detected, key_tables covered, direction matches.
   - `DETECTED_BUT_UNDIRECTED`: the FAMILY row exists with `direction='undetermined'`
     (engine Cut B: canonical_type = the family when undirected) — still FAILS a
     required directed cycle, but as its own named state, distinguishable from missed.
   - `MISSED` / key-tables-short: as today.
   The AP acceptance carried from DAT-853 resolves through this: green on merits, or
   red as the distinguishable undirected state with the missing evidence named in the
   cycle's own description.

---

## Open questions for the eval agent (answer or bounce to the owner/lead)

- **Q1 (O6)**: dataset naming for the role-play fixture — new Tier-A dataset
  (e.g. `detection-roleplay-v1`) vs folding the shape into an existing corpus
  variant? The cube declaration above carries a TBD placeholder.
- **Q2 (O3/O4)**: both extend `test_grounding_e2e.py` — one coordinated version bump,
  or does the evolved framework prefer splitting `_P2_MATCH_SHAPES` growth into a new
  structural-shapes module? Owner has no preference; DAT-862 semantics decide.
- **Q3 (O5 parity)**: how should verdict-identical parity interact with the DAT-863
  epochs/reducer — parity of reduced verdicts across N draws, or per-draw parity?
  The sign_conventions verdict-flip observation says single-draw parity will flap.
- **Q4 (O1)**: one module or split (coverage/anchor vs ladder/calendar)? Single module
  declared above; split freely if cube-cell planning favors it.
- **Q5 (conditioning idiom, O4/O2)**: the owner's conditioned-hard and
  skip-not-vacuous rules assume pytest skip semantics — if the evolved framework has a
  first-class "conditional cell" concept, prefer it and note the mapping.

---

## Answers (eval agent, 2026-07-22 — framework-semantics rulings, DAT-860/862/863)

**Q1 — new Tier-A dataset: `detection-roleplay-v1`.** Never fold a structural FK-shape
change into an existing corpus: it perturbs the relationship judge, bus-matrix, and
shared-axes surfaces for every oracle bound to that corpus, and (under DAT-861) a
structural edit invalidates the corpus's cached cells for all of them — the exact
§2.2 confounding the replan retires. The cube makes a small dedicated dataset cheap:
O6 binds it at `begin_session`, so its cells never pay for an OM run. The DAT-419
shape (two distinct FKs between one table pair) graduates in the SAME dataset — one
corpus, two truths. O6's declaration above is updated; `CAP-roleplay-fk-fixture` in
`generator_backlog.yaml` now names the dataset.

**Q2 — split: new module `test_graph_shapes_e2e.py` (version=1) owns
`_P2_MATCH_SHAPES` + the O3/O4 shape entries.** DAT-862's version is module-grain, so
a module is the unit of verdict-history comparability — every bump resets it for ALL
the module's nodeids. `_P2_MATCH_SHAPES` is a growth surface (10 vertex/14 edge kinds
and rising through band 6): leaving it in `test_grounding_e2e.py` makes that module a
version-churn hotspot where graph-schema growth keeps blurring the history of the
semantic grounding verdicts. Split by version-churn driver: the shapes module's
version tracks the graph schema; `test_grounding_e2e.py` keeps the judgment-dependent
oracles (O3's walk, O4's where_predicates/bypass semantic check) and takes ONE bump
(shapes moved out + walk + scope check in). The store's diff will show the moved
nodeids as `gone` on grounding — triage note: intended, moved. Same cube cell either
way (`dataset="*", from_stage="operating_model"`), so the planner is indifferent;
this is purely verdict-history legibility.

**Q3 — split the parity claim by leg; reduced-verdict parity for judgment legs,
per-draw parity for deterministic legs.** "Verdict-identical" is a migration-
equivalence claim, and it decomposes exactly along the DAT-862 verdict-leg split:

- *Deterministic legs* (the set of nine, their identity, SQL/bind mechanics,
  EXPLAIN-bind, check_type, scope): **per-draw, exact, hard** — any flap here IS a
  migration bug.
- *LLM-judgment legs* (sign_conventions' account classification): **parity of
  REDUCED verdicts** under the DAT-863 discipline — N draws per home, same named
  reducer (majority vote), compare the reduced verdicts AND the draw split. Demanding
  per-draw equality on an LLM leg demands determinism from a non-deterministic
  instrument — manufactured red, the harness-level Goodhart the charter bans.
  A reduced-verdict disagreement is a real finding and blocks the deletion; a shifted
  draw split with agreeing reduced verdicts (5/5 vs 3/5) is a REPORTED finding (the
  migration moved the judgment context) but not a blocker.

The YAML-deletion decision keys on: deterministic-leg parity green + judgment-leg
reduced parity green, flap rate named in the read-out. Token thrift: only the
judgment legs get epochs (classify each of the nine by mechanics first); until the
DAT-863 reducer lands in the harness, the parity oracle runs its own bounded N-draw
loop for those legs only — a named-budget gate, not a dev loop.

**Q4 — single module, as banked.** Both halves bind the identical cell
(`dataset="*", from_stage="begin_session"`), so cube-cell planning is indifferent —
a split would be organizational only. Split later only if a real divergence shows up
(different version-churn rates or different conditioning). Unlike Q2 there is no
growth-surface/judgment split here: both halves are deterministic graph reads on one
substrate.

**Q5 — no first-class conditional cell, by design; the idiom is a reason-prefixed
skip.** The cube declares STATIC binding (what a plan can know before materializing);
"a measured status cycle exists in this run" is a runtime fact of the materialized
cell, so it cannot live in the declaration without making plans lie. The framework's
contract for conditioned-hard, all three parts:

1. **skip, never vacuous-pass** (as the owner ruled);
2. **machine-readable reason prefix** — `pytest.skip("conditional-cell: <condition>")`.
   The DAT-862 store records every skip reason verbatim, so sweep accounting can
   partition designed conditioning from silent stand-downs, and the coverage-baseline
   diff still surfaces a conditioned oracle that stops grading;
3. **the condition's own recall belongs to another oracle** (O4 already does this:
   cycles recall owns "should a cycle exist"; the conditioned entries grade plumbing
   only) — a conditioned-hard oracle without that pairing is a silent hole.

**Flag — RESOLVED by the graph-close owner (2026-07-22):** O1/O6's `begin_session`
declarations are **correct as banked**. There is no unified "og_* promotes with the
OM head": the graph is DDL over `current_*` views, and each element view resolves its
own substrate's grain at query time. O1/O6's substrates (temporal profiles,
time_columns, hierarchies, slices, bus matrix, lineage witness) are all
add_source/begin_session-grain; the genuinely OM-grain elements are exactly the ones
already declared `operating_model` (additivity, validity filters). The same fact
clears the DAT-860 bus-matrix/folded-dims caveat. The executor can trust the
declarations as banked.
