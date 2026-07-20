# DAT-762 — the gate, v2

Written 2026-07-16 by an agent held blind to `results_rwd.json`, `grade_rwd.py`,
`diagnose_rwd.py`, `RESULTS_DEV.md` and GATE.md's own "The gate" section. Inputs
were: `judge2.py`, `frame_clean.py`, `rwd.py`, `check_premise.py`,
`check_support.py`, GATE.md's data + known-limits sections, the cost model, and
the product owner's statements. No arm's score was read. Nothing below was tuned
to make an answer come out.

This supersedes GATE.md's "The gate". That gate required
`P(correct|high) − P(correct|low) ≥ 0.25`, which demands that low-confidence calls
be **wrong**. Low confidence means *"do not act on this without checking"*, not
*"I am probably mistaken"*. A judge that says "low" on a 2-row FD and is right is
behaving exactly as designed; the old gate failed it for being honest. Nothing in
this document rebuilds that requirement in a new costume — see C5, which is
deliberately one-sided.

---

## 0. What this gate certifies — and what it cannot

**Certifies:** that the judge, sitting after the statistical stack, filters false
positives out of the *asserted* set better than the free non-LLM alternative, and
that what it is unsure about lands in `needs_confirmation` rather than in a silent
accept or a silent drop.

**Cannot certify, and no first version on this data can:** the cost asymmetry
itself. The cost model's worst case is a **false identity** — two columns declared
the same thing, silently corrupting numbers downstream. RWD labels one thing:
*is this FD part of the design schema*. It does not label identity-vs-drill-path.
Nothing computable from these 390 pairs distinguishes the catastrophic false
positive from the cheap one, so **no result here licenses the judge on identity
asserts.** A PASS certifies the lane for drill paths and hierarchy edges — the
"line in a list someone scrolls past" class — and for those only.

This is not a threshold I am lowering; it is a measurement the data cannot make.
Identity needs its own gate on data that labels identity. Ship the drill-path lane
on a PASS here; keep identity behind `needs_confirmation` unconditionally until
that gate exists.

---

## 1. The scored set

**324 pairs** = the 390 exact candidates minus the two degenerate tables:

| removed | pairs | labels | why |
|---|---|---|---|
| `hospital` | 22 | 22/22 meaningful | always-yes scores 1.00 here |
| `t_biocase_gathering` | 44 | 0/44 meaningful | always-no scores 1.00 here |

Base rate on the scored set: **104/324 = 32.10%**, against 32.31% on the full 390.
The exclusion moves the difficulty by 0.2pp. That is the fact that makes it safe:
this is not cherry-picking a friendlier set, it is removing two tables where a
constant answer is indistinguishable from competence while leaving the problem
exactly as hard.

The 66 excluded pairs are **reported per table** (§6), never gated.

---

## 2. The routing under test

The engine has three states. Pre-registered mapping, fixed before any number is
read, from the judge's `{meaningful, confidence}`:

| routed state | condition | consumer consequence |
|---|---|---|
| **ACCEPT** | `meaningful=true` ∧ `confidence=high` | asserted to the agent as context; shown in the UI as a structure. Acted on. |
| **GREY** | `confidence ∈ {medium, low}`, either polarity | surfaced as `needs_confirmation`. Costs a click. |
| **REJECT** | `meaningful=false` ∧ `confidence=high` | dropped. The user never learns it existed. |

Only two cells carry real cost:

- **ACCEPT ∧ label=not-meaningful** → a silent false assert.
- **REJECT ∧ label=meaningful** → a silent loss; invisible, un-askable.

Every GREY cell is near-free by the product owner's own ruling ("confidence flags
work quite well across other agents"). The gate therefore prices GREY at
approximately zero and spends all of its strictness on the two acted-on cells.

**Scoring is per rep, not on the majority vote.** The shipped product makes **one**
call. A gate that passes only on a 3-vote ensemble certifies a product we are not
shipping. So C1–C4 are computed independently on each of the 3 reps and **all three
must clear**. The majority-vote ensemble is reported (§6) as "what 3× the spend
would buy", not gated. This departs from GATE.md's pre-registered majority vote,
deliberately and on the record: conjunction of three noisy tests risks a false FAIL,
and I accept that trade because a false FAIL costs a re-run while a false PASS ships
the lane.

---

## 3. The comparators — the honest baselines

"Keep everything" (P=0.323, R=1.000) is **not** the baseline worth beating. It is
trivially beatable and beating it proves nothing. The real comparator is the free
one:

| comparator | rule | precision | recall |
|---|---|---|---|
| keep-everything | assert every candidate | 0.323 | 1.000 |
| **support-only** | assert iff `n_rows ≥ 1000` | **0.490** | **0.810** |

Derived from the pre-registered data facts alone (182 thin @ 86.8% not-meaningful
→ 24 meaningful thin; 208 thick @ 102 meaningful = 49.0%). No LLM, no API call, no
prompt — a row count.

The product owner's constraint is verbatim: *"Having an LLM or not is not the target
but filtering out the false positives."* That is exactly an instruction to compare
against the non-LLM instrument. **If the judge cannot beat `n_rows ≥ 1000`, ship the
row count and delete the lane.**

> **Compute, do not assume.** The 0.490/0.810 above are for the full 390. On the
> scored 324 they depend on which stratum `hospital` and `t_biocase_gathering` fall
> in, which I have not verified. The comparator is a **rule**, not a number: recompute
> its precision and recall on whatever set the gate scores, at gate time. The
> quoted values are a sanity check on that computation, not an input to it.

---

## 4. The gate

All criteria on the 324-pair scored set, per rep, all 3 reps.

### C1 — the asserted set must be worth asserting *(headline)*

**C1a (relative, binding):** Wilson 95% lower bound of `P(meaningful | ACCEPT)` >
`max(support-only precision, scored-set base rate)`, both recomputed on the scored set.

*Why:* below this the judge is an expensive row count. The lower bound rather than
the point estimate because with an accept set around 60–120 pairs the binomial SE is
≈0.05; a point estimate 3pp over the comparator is noise, and a gate that passes on
noise is not a gate.

**C1b (absolute, product):** `P(meaningful | ACCEPT) ≥ 0.65`.

*Why 0.65:* it is 2:1 odds that an asserted structure is true. The consequence is the
reader's default. Below 2:1 the agent is told something false more than once every
three structures and the human's list is a third junk — the reader must verify every
line, which is what they must already do at the 0.323 baseline, so the lane changed
no behaviour. At 2:1 the default flips to "usually right" and spot-checking becomes
rational instead of exhaustive checking.
**This is a judgment call.** The defensible band is roughly 0.59 (comparator + 2 SE)
to 0.70. I chose the top of the behaviour-change argument rather than the bottom of
the noise argument. The product owner can move it; C1a cannot be moved without
making the gate invalid.

### C1c — the lift must not be row-counting in disguise

Wilson 95% lower bound of `P(meaningful | ACCEPT ∧ n_rows ≥ 1000)` > the thick-stratum
base rate, recomputed on the scored set.

*Why:* support is the confounder. Within the thick stratum support is constant, so any
lift there is semantic — which is the entire residual this lane exists to cover
(g3=1.0 and λ=1 on every pair; the pair statistics are pinned by construction). A judge
that wins overall but sits at the base rate inside the thick stratum has rediscovered
`n_rows ≥ 1000` and charged us Sonnet tokens for it.
*Power is limited here* — the thick non-degenerate stratum is roughly 140–190 pairs
depending on where the degenerate tables fall, so this test can fail on a true effect.
It is gated anyway: it is the only criterion that isolates the thing being bought.

### C2 — real structure must not be buried silently

`P(ACCEPT ∨ GREY | label=meaningful) ≥ 0.80` — equivalently, silent high-confidence
rejection of a real structure ≤ 20%.

*Why 0.80:* not a round number — it is the free rule's own figure. Support-only buries
24 of 126 real structures (recall 0.810). A missing structure is invisible: the user
never knows to ask. If the LLM buries *more* real structure than a row count does,
while costing money, it is the worse instrument on the axis where the cost is
unrecoverable. The bar is "no worse than free", rounded down from 0.810 to 0.80
because the ratio rests on ~104 positives (SE ≈ 0.035) and false precision would be
dishonest.

Note GREY counts as preserved. That is the point of the third state: an unsure call
that reaches the user costs a click, not a structure.

### C3 — the lane must do work, not hand it back

**Grey rate on the thick stratum ≤ 0.50.**

*Why thick only:* the thin stratum is 182 pairs with a median of 7 rows, 51 pairs with
≤2 rows, and 38.5% at ≤1 row per LHS value. **Abstaining there is the correct answer.**
A judge that greys the entire thin stratum would sit at 46.7% grey overall and I would
be failing it for being right — the exact predecessor bug in a new costume. So the thin
grey rate is **reported, never gated** (§6), and the bound applies only where the judge
has evidence and a shrug is a shrug.

*Why 0.50:* on data that supports a decision, handing more than half of it back makes
the operating model a to-do list rather than a model. This is a loose bound on purpose —
GREY is the safe state and the product owner blessed it. It exists solely to stop the
degenerate "abstain on everything" pass, not as a quality bar. **Judgment call**, and a
deliberately generous one.

### C4 — the lane must actually assert something

`P(ACCEPT | label=meaningful) ≥ 0.40`.

*Why:* C1 is gameable by accepting three easy pairs at high confidence and greying the
rest — precision 1.00, lane worthless. At least 2 in 5 real structures must land in the
model without a human touching them; below that the "automatic" operating model is a
confirmation queue and the lane is triage-only. For scale, the free rule asserts at
recall 0.810 — it asserts far more, and far dirtier. **Judgment call.** If it fails
while C1 passes strongly, that is a *tuning* finding (the judge is too shy), not a
condemnation — say so rather than failing the lane silently.

### C5 — the confidence flag must not point backwards

`P(correct | meaningful=true ∧ high) ≥ P(correct | meaningful=true ∧ medium-or-low)`.

**One-sided. No margin. Deliberately.**

*Why no margin:* a margin is precisely the predecessor's bug. Requiring high to beat low
*by* something requires low to be wrong, and low does not mean wrong — it means
unverified. The only thing that must be true is that the flag does not point backwards.
An **inverted** flag actively harms the consumer: it routes the judge's better calls into
the confirmation queue and acts on its worse ones. That is a broken instrument and fails.
A **flat** flag (high ≈ low) does not harm anyone — it means the third state is overhead,
which is a finding about the routing, not a failure of the lane. Reported (§6), not gated.

---

## 5. Verdict rule

PASS iff C1a ∧ C1b ∧ C1c ∧ C2 ∧ C3 ∧ C4 ∧ C5, on **each** of the 3 reps, on the 324-pair
scored set.

Any FAIL is reported as a FAIL with the failing criterion named. "CUT is not an option"
means the instrument must be valid and we must keep building until the lane works — it
does **not** mean the answer must be yes. A FAIL here is a direction to the next build,
not a cut.

---

## 6. Reported, not gated

Everything here is read, published, and argued about. None of it can flip the verdict.
Fixing that boundary now is what stops the verdict from being chosen after the fact.

1. **Per-table breakdown** — accept precision, accept recall, grey rate, for each of the
   9 tables including the 2 degenerate ones. Plus each table's constant-baseline score,
   so a reader sees the trap rather than being protected from it.
2. **The two degenerate tables** — does the judge accept most of `hospital` and reject
   most of `t_biocase_gathering`? A behaviour check. Diagnostic only.
3. **Thin-stratum grey rate and thin-stratum accept precision.** High thin grey is
   *expected and correct*, not a defect.
4. **The confidence lift** `P(correct|high) − P(correct|low)`, signed, with CI. If ≈ 0,
   the three-state routing is unearned → follow-up ticket to consider two states. Not a
   FAIL.
5. **Majority-vote ensemble numbers** — all of C1–C4 recomputed on the 3-rep majority
   vote. Answers "what would 3× the spend buy?".
6. **Stability** — per-pair unanimity rate on `meaningful`; spread of accept precision
   across the 3 reps (min/median/max).
7. **VH − V** — the arm contrast. This gate scores each arm against the bar independently;
   it does not gate the contrast. If both arms pass, ship the cheaper one. If the contrast
   is what a reader wants, it is here, but the lane's fate does not hang on it.
8. **The two-state routing (R2)** — accept = `meaningful=true` at any confidence — scored
   under the same criteria, as a comparator.
9. **Reason-string reading.** Not computable from `{meaningful, confidence}`, so
   structurally outside the gate. Read 30 accepts and 30 greys by hand anyway; if the
   accepts are all "two renderings of one fact" (encodings — the easy origin), the lane
   found the easy half and the record should say so.

---

## 7. The headline number

> **`P(meaningful | ACCEPT)` — precision of the auto-accept set, on the 324-pair
> non-degenerate scored set, per rep — printed beside 0.323 (keep-everything) and the
> recomputed support-only precision (≈0.490).**

*Why this one:* the product owner's objective is verbatim *"filtering out the false
positives"*. This measures exactly false positives, in exactly the cell where a false
positive costs anything — the set that gets acted on rather than flagged — on a set
where the two degenerate tables cannot inflate it. Recall, grey rate and coverage are
constraints that stop it from being gamed; they are not the objective. One number, one
consequence: *of the structures we assert without asking, how many are real?*

It must never be printed alone. Precision without its two comparators is meaningless —
0.49 of it is free.

---

## 8. Degenerate tables and the thin stratum

The threat is that both can produce a competent-looking number from a constant answer.

| trap | how it inflates | handling |
|---|---|---|
| `hospital` 22/22 | always-yes → 22 free true accepts, inflating the headline's numerator | excluded from the scored set; reported per table |
| `t_biocase_gathering` 44/0 | always-no → 44 free correct rejects, inflating reject purity | excluded from the scored set; reported per table |
| thin stratum (182 @ 86.8% not) | "few rows → not meaningful" is 86.8% correct for free; a row-counter looks semantic | **conditioned on, not removed** — C1c gates the thick stratum where support is constant, so lift there cannot come from row counts |
| thin stratum, deflation | greying 182 thin pairs is *correct*, and an overall grey bound would fail an honest judge for it | C3 gates grey on **thick only**; thin grey is reported |

Removing the two degenerate tables costs 0.2pp of base rate (32.31% → 32.10%) — verified
arithmetic, not an assumption. The strata and every comparator are **recomputed on the
scored set at gate time**; nothing in this document's numbers is hard-coded into the
grader.

---

## 9. Validity — the gate must be able to fail

A gate that cannot fail is not a gate. Before any real result is graded, run the grader
against five synthetic judges. **All five must FAIL.** If any passes, the gate is broken
and the real result is not to be read until it is fixed.

| synthetic judge | expected | via |
|---|---|---|
| always `{true, high}` | FAIL | accept precision = 0.321 < 0.65 (C1b), LB below base rate (C1a) |
| always `{false, high}` | FAIL | visible recall = 0 (C2); accept set empty |
| always `{false, low}` (abstain-on-everything) | FAIL | thick grey = 1.0 > 0.50 (C3); accept recall = 0 (C4) |
| random at base rate, all high | FAIL | accept precision ≈ 0.32 (C1a, C1b) |
| **support-only** — `{n_rows ≥ 1000, high}` | FAIL | cannot beat its own comparator (C1a); thick accept precision = thick base rate (C1c) |

The fifth is the one that matters. It is the free instrument, and the gate is constructed
so that it fails by definition. Anything that passes has beaten it.

An empty or near-empty accept set is a FAIL, not an undefined precision: if `|ACCEPT| < 20`
on the scored set the lane is not certifiable at this sample size — report FAIL-underpowered,
not PASS.

---

## 10. What would make me distrust a PASS

Written before any result was read. If any of these holds, the PASS is reported as
**PASS-suspect** and does not ship on its own.

1. **Passes C1a/C1b but fails or barely scrapes C1c.** The win is row-counting. The judge
   is an expensive `n_rows >= 1000` and we should ship the row count.
2. **Re-including the degenerate tables changes the verdict.** If the gate passes on 390 and
   fails on 324, the judge learned "biocase → no" and the number is table identity, not
   semantics.
3. **The PASS rests on one or two tables.** If ≥3 of the 7 scored tables sit at or below
   their own base rate, this is table-specific luck, not a lane. Per-table breakdown (§6.1)
   is where this shows.
4. **Low unanimity with all 3 reps passing.** If the reps disagree per-pair a lot but each
   happens to clear the bar, the aggregate is stable while the instrument is not — a fourth
   rep is a coin flip on a customer's schema.
5. **High precision with accept recall near the C4 floor and a large grey.** The judge found
   the easy pairs and shrugged at the rest. Precision is real but the lane is a triage queue
   wearing a filter's clothes.
6. **The accepts are all one origin.** If the hand-read (§6.9) shows the accept set is
   entirely encoding pairs — "A and B are two renderings of one fact" — then the lane covers
   the syntactically-obvious half of the residual and nothing about the semantic half, and
   the headline is measuring the easy stratum.
7. **C5 passes only because low-confidence calls are rare.** If the medium/low accept
   population is under ~20 pairs, C5 is untested rather than passed. Report as untested.
8. **A PASS read as licensing identity asserts.** §0. The data cannot speak to it. This is
   the one where a wrong reading of a correct result silently corrupts a customer's numbers.

---

## 11. Judgment calls, listed in one place

So they can be argued with individually rather than swallowed as a package:

| call | value | status |
|---|---|---|
| accept-precision product floor | 0.65 (2:1 odds) | **judgment** — defensible band 0.59–0.70; PO may move; C1a may not |
| visible-recall floor | 0.80 | anchored — the free rule's own 0.810, rounded down for honest precision |
| thick grey ceiling | 0.50 | **judgment** — deliberately loose; an anti-degenerate check, not a quality bar |
| accept-recall floor | 0.40 | **judgment** — weakest anchor in the document; failing it alone is a tuning finding |
| thin/thick cut | `n_rows = 1000` | inherited from the pre-registered bimodality (182/208); not tuned here |
| per-rep conjunction over majority vote | all 3 must pass | **judgment** — accepts false-FAIL risk to match the one-call product |
| C5 margin | none, one-sided | **not** a judgment — a margin here is the predecessor's bug |
