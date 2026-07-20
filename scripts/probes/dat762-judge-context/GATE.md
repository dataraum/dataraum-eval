# DAT-762 attempt 2 — the held-out gate

Frozen 2026-07-16, before the tables landed and before any LLM call.
Attempt 1 (`PROTOCOL.md`, `RESULTS_DEV.md`) was CUT on a dev set its own prompts
were written against. This is the same question asked on data that shaped nothing.

## The question

Given a pair `(lhs, rhs)` where `lhs -> rhs` holds **exactly**, is it a real
constraint of the design schema, or a coincidence of this instance?

That is the residual the literature leaves open: statistics kill sampling
artifacts and degenerate dependencies; what they cannot do is separate two FDs
that both hold exactly and are both non-degenerate. Our own grain probe hit the
same wall independently (`driver__dob` 0.979 vs `circuit__location` 0.974,
opposite truths). This gate asks whether a well-fed judge covers that residual.

## The data — RWD, and why it is honest

Parciak et al., ICDE 2024. Zenodo 8098909, CC-BY-4.0. Two annotators per
candidate; disagreements discussed to consensus.

Verified locally (`verify_rwd.py`), not taken from a summary:

```
4926 ordered pairs -> 2024 computable -> 390 exact (g3 == 1.0)
  126 meaningful / 264 not     base rate 32.3%
  0 exact candidates in the excluded file  => the slice is COMPLETE, not sampled
  126 exact + 17 approx = 143 = ground_truth.csv rows  => reconciles
```

Held out in the only sense that counts: it never touched a channel, a frame, a
threshold or a cell in this repo. Nobody here labelled it.

**Every pair statistic is pinned on this slice.** g3 = 1.0 by construction, and
lambda = 1 follows (zero errors predicting rhs given lhs). Only single-column
profiles can discriminate — LHS near-key fraction, RHS skew — and those are
exactly the two candidates the grain probe CUT for total overlap. The slice is
semantic-only by construction. That is the point.

## Arms

| arm | evidence |
|---|---|
| **V** | column names, table's column list, both columns' profiles + sample values. No framing. (= the shape Auto-Relate's GPT-5 baseline used.) |
| **VH** | V, plus the origins framed as competing hypotheses with their discriminating facts, plus an explicit "cannot determine" channel. |

3 reps each, majority vote. 390 x 2 x 3 = 2340 calls. `N` (names-only) is not
run: it is cut, the record is corrected, and re-proving it costs 1170 calls.

Fixes carried from attempt 1's post-mortem, each a verified construction defect:
- The origin menu must span the truth space. Attempt 1's `frame_bidirectional`
  had no option for "a real attribute edge" or "vacuous on a degenerate domain",
  and its only misses were exactly those cells.
- No taste in the system prompt. Attempt 1's REJECT exemplar was "proxy key like
  a timestamp"; it then graded the judge wrong for rejecting timestamps.
- Every pair renders a frame. Attempt 1 scored 6 gradings on cells that rendered
  no frame at all.

## The gate — calibration, not accuracy

**Rewritten 2026-07-16 after Philipp's correction, before any LLM call.** The
first version of this section gated on `precision >= 0.65 at recall >= 0.90` and
demoted calibration to a secondary criterion. That was wrong, and wrong in a way
that had already been pointed out to me twice.

**Why.** This lane produces context for an agent and a flag in an operating-model
UI. It does not decide anything by itself. For that consumer, "is the verdict
right" is the wrong question:

- A judge at 50% precision **that knows which 50%** is useful — the agent
  caveats, the human clicks.
- A judge at 90% precision that is **confidently wrong** on the other 10% is
  dangerous, because nothing downstream can tell which is which.

An accuracy bar passes the second and fails the first. That is backwards.
Attempt 1's real finding was never "VH scored 40.3/45" — it was that **14 of its
14 errors were confidence=high**. That was the gate, and I filed it as an aside.

So: **calibration is the gate. Accuracy is reported, never gated.**

PASS requires both:

- **G1 — confidence partitions.** `P(correct | high) - P(correct | low) >= 0.25`,
  with medium between them (monotone). If confidence carries no signal, the
  lane's output cannot be trusted differentially, and a consumer has no way to
  use it.
- **G2 — high is actionable.** `P(correct | high) >= 0.80`. This is the only
  promise we make: when we say high, act on it.

REPORTED, with no bar attached:
- precision and recall on `meaningful`, overall and per table.
- the **confidently-wrong rate**: errors at high confidence / all high calls.
  This is the number that can hurt someone. It has no threshold because I do not
  know what it should be — but it is the headline.
- the abstain rate and the full confidence distribution.
- VH - V, which isolates framing on data that shaped nothing.

**No abstain-rate gate.** The previous version required non-high >= 10%. But
SYSTEM says "guessing at high confidence is worse than saying you cannot tell" —
so that gate would have scored a behaviour I explicitly instructed. Caught by the
frame agent. G1 is not instructable: telling a judge to abstain more does not
make its abstentions informative.

FAIL either -> report, CUT, and the fail-once rule is Philipp's call, not mine.

## Reporting rules, fixed now

- ~~**Headline is overall AND dblp10k alone.** dblp10k is 204 of 390 (52%) and
  sits near the base rate. It is the primary non-degenerate table.~~
  **WRONG — struck 2026-07-16 before the run, on a data fact, not a result.**
  dblp10k's median candidate stands on **7 rows** (min 1; eight of its FDs hold
  over a single row). It is the thinnest table in the slice, not the cleanest.
  38.5% of the whole slice has <= 1 row per LHS value, so "A -> B holds" is
  saying nothing about B.
- **Stratify by support and report the strata separately**: `n_rows < 1000`
  (182/390 with the sentinel fix) vs `n_rows >= 1000`. Support is a data fact,
  fixed here before any grading. Do NOT restrict the run to one stratum — on the
  thin stratum the honest verdict is *low confidence*, and whether the judge
  produces it is exactly what G1 measures. The thin pairs are not noise to be
  dropped; they are the calibration test.
- **Two tables are free wins and must be reported separately, never pooled into
  a headline:** `hospital` 22/22 all meaningful (always-yes scores 100%),
  `t_biocase_gathering` 44/0 none meaningful (always-no scores 100%). A judge
  that has merely learned the domain will show up here and nowhere else.
- Filenames are NOT given to the judge. The table's column list is — a real
  deployment sees real columns, and the domain is legible from them anyway. This
  is a known, unavoidable confound; per-table reporting is how it gets caught.
- Report V and VH separately. VH - V isolates framing on held-out data. Attempt
  1 measured that effect at +5.67 on identical numbers, contaminated.

## Known limits — stated now, not after

- Single-column LHS only. Our stack asserts multi-column structures this cannot
  speak to.
- 390 pairs, 9 tables, no finance. A gate, not a training set, and not evidence
  about the finance corpus.
- There is no published GPT-5-on-RWD number. This is not a reproduction of
  anyone's result; the 0.90 in the literature is Auto-Relate's Real-FD figure and
  their prompts are unpublished. Do not compare to it.
- "Part of the design schema" is not identical to "a practitioner would group by
  it". It is the closest labelled proxy that exists, and it is the residual the
  statistics cannot reach. It is not the whole product question.
- Non-determinism handled by pooling + majority. Never by overriding a verdict.

## Amendment 1 — I contaminated myself, and how it was handled

Recorded 2026-07-16, before any LLM call, while the data-fetch agent's report was
still the only thing that had touched the labels.

**What happened.** Step 5 of my own data-fetch task asked for column-profile
summaries of the 390 slice *split by label*. I got them. So I have now seen how
the answer key is distributed — specifically which direction two profile metrics
lean for meaningful vs not-meaningful pairs. That was my error in writing the
task, not the agent's in answering it.

**Why it matters.** `judge2.py`'s original `frame()` (written before the report
landed, so itself uncontaminated) asserted a direction for one of those metrics
as if it were a discriminating fact. The data says my direction was backwards.
So the frame was both wrong AND, from here on, unfixable by me: correcting the
direction would mean writing the answer key into the prompt.

**How it was handled.**
1. `frame()` is being rewritten by a subagent that is banned from
   `ground_truth.csv`, from `exact_candidates()`'s `meaningful` field, from
   `verify_rwd.py` and from this file. It may read the tables and the pairs.
   Its task prompt contains no medians, no directions, no per-table counts.
2. Nothing was ADDED on the strength of what I saw. One new candidate fact
   occurred to me while reading the label table (how many of the table's other
   columns the LHS also determines exactly — a key determines everything, so the
   FD asserts nothing specific). It is a plausibly good fact. It arrived after I
   saw the labels, so it does not go in. Post-hoc additions are how contamination
   enters.
3. The frame in `judge2.py` is superseded, not corrected. The only edit I made
   myself would have been subtractive — removing information can lower a score,
   never inflate it.

**Residual risk, stated plainly.** The subagent's frame is clean, but I chose
which facts `facts()` computes (LHS key fraction, RHS majority share) and I made
that choice before seeing anything. Those two turn out to be the metrics that
lean hardest. That is a correct prior about *which* facts matter, not knowledge
of which way they point — but a reader should know I had it. If VH passes, this
paragraph is the first thing to hold it against.

## What would make me distrust a PASS

Written down now so it cannot be rationalised later:
- A pass driven by hospital + gathering while dblp10k sits near the base rate.
- Confidence uniformly high again (G3 fails) — then G2 is noise on a small n,
  exactly as it was in attempt 1.
- Any per-table result at 0/n or n/n that the overall number hides.
