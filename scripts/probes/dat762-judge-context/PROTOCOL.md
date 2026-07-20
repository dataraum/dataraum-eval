# DAT-762 judge-context spike — protocol (pre-registered 2026-07-16)

Fixed BEFORE any LLM call in this probe. Channels, arms, truth labels, scoring
rules and kill gates below are frozen; anything learned during grading goes into
the report, never back into the inventory or the channel definitions. Amendments
are dated, justified in-line, and only permitted before the leg they affect runs.

Prior art in-repo: `scripts/probes/dat757-channel-ablation/` (the instrument this
extends — its `cells.py` inventory and `results.json` cache are reused read-only;
that probe is frozen and is not edited).

## Why this spike exists

Engine PR 500 (DAT-762) was rejected wholesale. Its judge saw column names only
("no values, no statistics" — `hierarchy_veto.yaml` states the withholding
explicitly), and a deterministic router in front of it (`routing.py`,
`classify_shape` = regexes + hand thresholds over stringified values) kept the
judge away from the classes it would otherwise wreck. The router was
string-guessing and had begun accreting exception patches (`entity_anchored`,
after 2/11 live vetoes proved false).

The starvation was justified by ONE measurement in the DAT-757 scorecard: on
quasi-identifiers, channel C3 (names + profiles + raw pair statistics) scored
2/4 vs C2 (names-only) 4/4 — read as "showing the judge statistics makes it
worse". Two facts about that reading are now on the record:

1. **It is a 2-cell difference in a 4-cell class, at one rep per cell**, with
   measured LLM instability elsewhere in the same scorecard. It may be noise.
2. **C3 bundled two things** — value evidence AND raw pair statistics — so it
   cannot separate "values hurt" from "raw statistic dumps hurt". The judge's
   own C3 misgrade reasons show it rationalizing near-FD numbers into asserting.

## Questions

- **Q1 (reproduction).** Does the C2 > C3 quasi-identifier regression survive
  repetition, or is it instability? Reported per-cell verdict distributions.
- **Q2 (separation).** Do value/profile evidence and raw pair statistics have
  different effects when unbundled?
- **Q3 (presentation).** Does presenting the same statistics as *competing
  hypotheses with discriminating facts computed* — instead of raw numbers —
  recover the classes raw statistics regress on, while keeping what the
  statistics get right?
- **Q4 (the router's job).** Is there a channel on which the judge upholds the
  stats-owned classes (F dirty-true hierarchies, H weak-true org edges, J true
  FK edges) — the classes the PR-500 router existed to fence off? If yes, the
  router has no job: the lane covers all asserted structures, veto-only, and
  `routing.py` dies with nothing replacing it. If no, the recorded fallback is
  routing by **statistical provenance** (which stack gate produced or deferred
  the structure), never by value or name shape.
- **Q5 (held-out).** Does the winning channel hold on databases that shaped
  nothing?

## Channels (judge held constant; evidence is the only variable)

All arms share ONE output schema and ONE system prompt (below), so every arm is
strictly comparable within this probe. The DAT-757 `results.json` C2/C3 entries
are a *historical reference* for Q1, not an arm — their schema differs.

- **N — names-only.** Table name + full column-name list + the pair. The PR-500
  veto judge's evidence surface. Reproduction of DAT-757 C2.
- **V — +values.** N + per-column profiles: n_rows, n_distinct, null rate, top
  values with frequencies, random samples. **No pair statistics.** Never tested
  before (C3 bundled these with the statistics).
- **VR — +raw statistics.** V + pair statistics as a raw JSON block (row-g3 both
  directions, pair-count g3, λ both directions, value-equality disagreement,
  value-set Jaccard). Reproduction of DAT-757 C3 — the "bad presentation" arm.
- **VH — +hypothesis-framed statistics.** V + the SAME statistics as VR, rendered
  as the assertion plus its competing origins, each equipped with the computed
  fact that discriminates it (near-key ratio, λ vs the majority baseline,
  reverse-direction violation, disagreement structure). Content identical to VR;
  framing is the variable. **This is the core arm.**
- **VHM — +meaning.** VH + a one-line authored meaning per column and the table's
  role, produced by a table-level semantic pass that mirrors the engine's
  `semantic_per_table` (the engine has `ColumnConcept.meaning` for every column
  and `TableEntity.table_role` at this seam — this arm simulates that feed).
- **VH-think — VH with extended thinking.** Confound flagged up front: the
  engine's v1 judges are non-thinking because forced `tool_choice` suppresses
  thinking on the Anthropic API. If this arm wins, the engine's structured-output
  mechanism must change (non-forced tool + repair), and that becomes a build
  requirement, not a reason to discard the result.

Arms N/V/VR/VH are the core legs and run first. VHM and VH-think run only if a
core arm clears the dev gate — cost control, pre-registered.

**What no channel ever contains:** the stack's verdict (this measures evidence
value, not verdict-parroting) and any name-pattern or value-shape classification
(the PR-500 failure being replaced).

## Judge

`claude-sonnet-5` (the scorecard's model, kept for comparability). Verdict space
unchanged from DAT-757 — MERGE | HIERARCHY (+direction) | ROLE | REJECT — so the
cell inventory's pre-registered truth applies unchanged. Output adds a
`confidence` ∈ {high, medium, low} field: the engine's abstain posture is
low-confidence, and abstention must be measurable here rather than bolted on
later. Claude 5 rejects the `temperature` parameter (400: deprecated) — the judge
runs at model-default sampling, as in the DAT-757 amendment.

**3 repetitions per cell per arm**, per-cell verdict distributions reported.
This is the Q1 instrument: the original finding is one rep. Instability is
reported, never majority-patched into a verdict; where an arm's cells are
unstable, the class score is reported as a range across reps.

## Dev set — the 45 cells (regression only, NOT the verdict)

`scripts/probes/dat757-channel-ablation/cells.py`, imported read-only. These
cells shaped PR 500's routing classes and its names-only decision; a green score
here proves nothing about a redesign and is explicitly not the gate. They are
here to (a) answer Q1–Q4 against a labelled inventory with per-class structure,
and (b) regression-check that a new channel doesn't lose what names-only had.

Added to the dev set, not to the verdict: the **2 live false-veto structures**
from PR 500 (the account drill chain routed as quasi-identifier), as a
regression case with truth = uphold.

> **Amendment 2026-07-16, before the dev leg ran — the PR-500 false-veto cells
> are DEFERRED.** They exemplify one class: a real org hierarchy the judge must
> not reject. That class is already carried by F (dirty-true hierarchy, 5 cells)
> and H (weak-true org edges, 2 cells) — H1 `SOLDTOPARTY → doc__SALESOFFICE` is
> the same shape as the account chain — and G-D2 gates on exactly it. The
> held-out gate then measures the same property mechanically at scale on fresh
> databases (G-H1: real structure vetoed). Two hand-picked cells on a fourth
> corpus add cost, not evidence. If G-D2 comes out ambiguous, they get built and
> the ambiguity is reported either way.

> **Note recorded at render-check, before any LLM call — a dev-set data-quality
> artifact, not fixed (the DAT-757 instrument is frozen and the artifact hits
> every arm identically):** cell L3 (`number` vs `grid`, "overlapping integers")
> renders with `value_set_jaccard = 0.0`, because `number` stringifies as "6.0"
> (float) and `grid` as "0" (int), so the value sets do not overlap as strings.
> The cell's stated premise is therefore not visible to any judge. L3 scores are
> reported but this cell is noted as compromised for the false-friend class.

## Dev gate (proceed / CUT — evaluated before any held-out call)

Pre-registered, evaluated on the core arms:

- **G-D1** — the best arm scores ≥ N (names-only) on the veto classes
  (D quasi-identifier, E free-text, P proxy-bijection, G3), across reps.
- **G-D2** — the best arm upholds the stats-owned classes (F dirty-true
  hierarchy, H weak-true org, J true-FK) at ≥ 0.8 strict. **This is Q4's gate.**
  Names-only is expected to fail it — that failure is what the PR-500 router was
  compensating for, and reproducing it is part of the result.
- **G-D3** — zero false MERGE on the L false-friend cells, on the best arm. This
  is the costly error: a wrong conform corrupts `conformed_group` identity and
  every DAT-800 consumer downstream.

All three must hold on one arm to proceed to held-out. If no arm clears them
after this one grounded attempt, the full-coverage judge design is **CUT**, the
result is recorded in the catalog, and the fallback (names-only + provenance
routing, or no lane at all) is brought to Philipp as the verdict.

> **Amendment 2026-07-16, recorded while the dev leg was still running and no
> score had been seen — "best arm" is defined, not chosen.** G-D1/G-D3 say "the
> best arm" without a selection rule, which would let the result pick its own
> gate. Fixed reading, faithful to "all three must hold on one arm": an arm
> **passes iff it clears G-D1 ∧ G-D2 ∧ G-D3 on its own scores**. If several pass,
> the one with the highest overall strict score (rep-1, ties broken by the 3-rep
> mean) carries to held-out. If none passes, the outcome is **CUT** — there is no
> "closest arm" and no partial credit.
>
> Consequence stated up front, before the data: **N (names-only) is expected to
> fail G-D2**, since the DAT-757 record shows both LLM channels rejecting the
> stats-owned classes — that failure is what PR-500's router existed to hide. So
> if VH also fails G-D1 (the early P-class signal suggests it may), then **no arm
> passes and the entire LLM lane is CUT**, leaving only Part 2's LLM-free legs
> (referenced + degenerate) and the bus-matrix plumbing. That is a legitimate and
> valuable verdict — it would say the stack v4 stands alone and DAT-762's Part 1
> was never buildable on any evidence channel tested. It is recorded as such, not
> softened.

## Held-out gate — the verdict (Q5)

**Datasets.** RelBench databases never downloaded before this spike and used in
nothing that shaped any design: candidates `rel-amazon`, `rel-avito`,
`rel-event`, `rel-stack`, `rel-trial`. Selection criteria, fixed before the data
was inspected and applied mechanically (survey in `heldout_survey.md`):
C1 not rel-f1/rel-hm/rel-salt (required); C2 ≥1 fact table with ≥2 FKs into
dimension tables (required); C3 fact ≥10k rows (required); C4 ≥2 fact tables
sharing ≥1 declared FK target, enabling cross-fact conform (strongly preferred);
C5 role-playing FKs present (preferred); C6 descriptive/text-bearing dimension
attributes (preferred); C7 domain diversity and probe cost (tiebreak). 2–3 DBs
are taken forward.

**The measured question is operational, not academic:** on a database nobody
looked at, of the structures the stack v4 actually asserts, how many does the
judge correctly veto, and how much real structure does it destroy?

**Truth is mechanical — derived from the database's own declared PK/FK metadata,
never authored by anyone who saw a judge verdict.** Every asserted structure is
classified by the fold harness's existing taxonomy
(`dat757-relbench/probe_fold_grade.py`):

- **in-group** — both columns belong to the same declared dimension (same FK
  target table). The schema itself says these columns describe one entity ⇒
  **real dimension structure; a veto here is a false veto.**
- **cross-group** — the columns belong to two independently declared dimensions
  with no declared relationship between them. An FD across them is an artifact
  of the fact-table join ⇒ **spurious; a veto here is a true veto.**
- **fact-internal** — determinant is the fact's own PK/near-key, or both columns
  are fact-own measures/keys. Mixed by nature ⇒ **reported separately, excluded
  from the gate arithmetic**, with the residue hand-labelled BLIND (before any
  judge verdict is read) only where a call is needed.

**Gates, per database, on the winning arm:**

- **G-H1** — ≤ 10% of in-group (real) asserted structures vetoed.
- **G-H2** — ≥ 3:1 ratio of cross-group artifacts vetoed to in-group real
  structures destroyed.
- **G-H3** — G-H1 and G-H2 hold independently on ≥ 2 held-out databases.

Miss → the design is **CUT** after one grounded attempt, per the kill-gate rule;
the fallback is recorded and brought to Philipp. Pass → the result is the
evidence for the engine build, and the same gate is re-run through the engine's
own lane before the PR leaves draft (the probe's verdict is never the PR's).

## Conform leg (Part 1's second role)

The DAT-762 ticket states cross-fact conformed-dimension identity "has no
pairwise statistics (different facts share no rows)". That is true only for
**disjoint** value sets (the K cells). Where fold-key domains overlap across
facts, two named statistics exist and are computed here: **domain containment**
(|A∩B| / min(|A|,|B|)) and **attribute agreement on the overlap region** (the
rate at which the same key value carries the same attribute values in both
facts). Conform arms:

- **CN** — PR-500's surface: names + attribute names (+ meanings in VHM form).
- **CV** — CN + value evidence (profiles, top values, sample values).
- **CH** — CV + containment/overlap-agreement statistics, hypothesis-framed.

Graded on K (disjoint conform, MERGE) and L (false friends, REJECT) in dev; on
held-out DBs, on fact pairs sharing a declared FK target (**truth = CONFORM, from
the schema**) vs pairs into different targets (**truth = DISTINCT**). ABSTAIN is
a permitted verdict and is scored as neither correct nor a false merge — it is
the correct posture on genuinely disjoint evidence, and is reported as its own
rate. **Zero false CONFORM is the hard floor** on every arm, dev and held-out.

## Non-goals / honesty

Small n per class — this is a map plus a decision gate, not a hypothesis test;
no significance theater. LLM instability is reported, never patched. No arm's
definition changes after seeing its score. The dev set cannot produce a passing
verdict; only the held-out gate can. A CUT is a successful outcome of this spike.
