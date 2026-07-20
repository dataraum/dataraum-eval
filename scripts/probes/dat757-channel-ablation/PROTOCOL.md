# DAT-757 channel-ablation scorecard — protocol (pre-registered 2026-07-14)

Fixed BEFORE any LLM call. Cells, truth labels, prompts, and scoring rules in this
file and `cells.py` are frozen; anything learned during grading goes into the
report, not back into the inventory.

## Question

For each dimension-identity cell class, which evidence channel is minimally
sufficient — and does a richer channel *regress* on classes the statistics already
solve? Prior art: FD-mining is semantics-blind; schema matching keys on names
(GLUE ~12–15% names-only, for matching not dimension identity). Nobody publishes
this map.

## Channels (cumulative evidence, judge held constant)

- **C1 values-only** — the frozen DAT-757 stack v4, mechanical, no LLM:
  same-domain near-copy check first (value-equality disagreement in (0,5%] →
  disagreement-set role tests, T1 role-specific) → alias screen (pair-count g3
  both dirs ≤ 0.01, BH) → edge screen (row-g3 ≤ 0.01 + guards + λ ≥ 0.5 + BH) →
  else REJECT. Cross-view cells (no shared rows) are REJECT by construction.
- **C2 +names** — LLM judge; evidence = table name + full column-name list +
  the pair. No values, no stats. (2026 reading of the "names channel": what
  identifiers alone support, judged by a strong reader — not edit distance.)
- **C3 +values/stats** — LLM judge; evidence = C2's + per-column profiles
  (n, distinct, null rate, top values with frequencies, random samples) + pair
  statistics (row-g3 both directions, pair-count g3, λ, disagreement rate,
  role-test p-values where applicable). The stack's *verdict* is withheld —
  C3 measures evidence value, not verdict-parroting.
- **C4 +TFM** — TabICL column embeddings, targeted at the disjoint-value (K) and
  false-friend (L) cells with A cells as controls; kill condition per the queue:
  cluster purity ≤ the C2 names baseline on K∪L. Designed here, run as its own
  leg in `tfm/` (separate uv env).

## Judge

`claude-sonnet-5`, JSON verdict. One scoring pass; one full repetition to report
per-cell instability (reported, never majority-overridden — no deterministic
patching of LLM judgments). *Amendment 2026-07-14, before any successful grading:
temperature 0 was pre-registered but the Claude 5 API rejects the parameter
(400: deprecated) — the judge runs at model-default sampling; the repetition
remains the instability measure.*

## Verdict space (what the engine must decide per pair)

- **MERGE** — same thing; collapse into one identity (alias/code↔name/conform).
- **HIERARCHY a→b** — a valid groupable dimension edge (b is a coarser level or
  attribute of a). Direction scored strictly and reported lax.
- **ROLE** — same concept family, deliberately distinct instances; keep apart.
- **REJECT** — no dimension relationship worth asserting (coincidence,
  quasi-identifier, proxy determinant, measure-derived, void).

## Cells

45 cells in `cells.py`: 13 classes × 1–6 instances, drawn from the three folded
RelBench OBTs (+2 constructed cross-view cells). Classes: A true alias, B dirty
alias, P proxy bijection (id↔timestamp — statistically MERGE, semantically edge),
C roles, D quasi-identifiers, E free-text determinants, F dirty-true hierarchy,
G grain quasi-keys, H weak-true org edges, I vacuous skew, J true-FK sanity,
M measure-derived, K disjoint-value conform (constructed), L false friends.
J/I/M exist to measure **regression**: channels must not over-assert where C1
correctly rejects. Truth labels carry a one-line justification each; the softest
labels (K2, P-class) are flagged in-line.

## Scoring

Per class and channel: fraction of cells with exact verdict match (strict =
direction-sensitive for HIERARCHY; lax also reported). Headline = class × channel
map + "minimal sufficient channel" per class (first channel ≥ 0.8, qualitative at
these n). Deliverable feeds the engine's evidence-ordering ("names last" claim)
and the LLM-call budget placement.

## Non-goals / honesty

Small n per class — this is a map, not a hypothesis test; no significance theater.
LLM instability reported, not patched. C1 verdicts recomputed mechanically from
the scans (role tests re-run, reps=999, fixed seed), never transcribed by hand.
