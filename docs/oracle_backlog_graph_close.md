# Oracle backlog — DAT-725 graph-close slice (banked specs, cube-declared)

Handoff from the DAT-725 owner (2026-07-22). Seven oracle specs banked against the
execution cube (DAT-860): each carries its exact `cube.needs(...)` declaration so the
evolved framework can plan cells before any oracle is written. **Nothing here has been
run**; the engine substrate lives on `epic/dat-725-graph-close` (dataraum-context, not
yet merged to main — vendor pin follows the merge). Companion: the eval-prep brief on
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
pytestmark = cube.needs(vertical="finance", dataset=("<roleplay-dataset-TBD>",), from_stage="begin_session")
```

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
