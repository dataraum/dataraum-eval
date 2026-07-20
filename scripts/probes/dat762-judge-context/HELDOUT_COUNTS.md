# DAT-762 held-out leg — mechanical counts

Protocol: `PROTOCOL.md` (frozen), section *Held-out gate — the verdict (Q5)*. **This stage made ZERO LLM calls.** It builds and validates the held-out harness and sizes the judge leg before the dev gate resolves.

Instruments imported read-only and unmodified: `dat757-g3-wide/fdlib.py`, `dat757-relbench/probe_fold_grade.py` (`SPECS`, `build_obt`), `dat757-channel-ablation/probe_ablation.py` (`c1_verdict`, `lam`, `utf`) and `cells.py`.

## 0. BLOCKED OBTs — read this first

**2 of 3 recommended OBTs could not be measured at all.** The frozen instrument fails on them; per the standing rule a known blocker is reported, not designed around. Nothing below is tuned to compensate.

```
rel-trial-outcome-analyses  (rel-trial / outcome_analyses)
  OBT built fine: 74,765 rows x 65 cols
  BLOCKED in scan_pairs: OutOfMemoryException: Out of Memory Error: could not allocate block of size 256.0 KiB (38.4 GiB/38.3 GiB used)
rel-stack-comments  (rel-stack / comments)
  OBT built fine: 134,258 rows x 30 cols
  BLOCKED in scan_pairs: OutOfMemoryException: Out of Memory Error: could not allocate block of size 256.0 KiB (38.4 GiB/38.3 GiB used)
```

**Consequence for G-H3.** The measurable OBTs cover **1 database(s)**: rel-stack. PROTOCOL.md's **G-H3 requires G-H1 and G-H2 to hold independently on >= 2 held-out databases**. Two OBTs from the *same* database are not two databases, so **G-H3 cannot be satisfied as pre-registered** unless a second database is recovered. This is a gate-blocking finding and it is surfaced before any billed call, which is what this stage is for.

## 1. `stack_verdict` vs `c1_verdict` — equivalence on the dev cells

**PASS — 43/43 cells agree exactly** (verdict, direction and reason), on the 43 non-constructed DAT-757 dev cells (rel-f1 / rel-hm / rel-salt). The 2 constructed cross-view cells (K1, K2) have no OBT and no joint statistics, so they are outside the port's domain.

No disagreements. The port is the frozen stack.


## 2. The held-out OBTs

Perm reps = **999** for every OBT (`perm_reps` in each spec) — the DAT-757 precedent for non-rel-f1 OBTs (rel-f1 alone used 2999). Alias and edge significance are per-pair perm-p <= 0.05, exactly as `c1_verdict`.

```
spec                         db          fact                      rows  cols   build    scan    stack
rel-stack-postlinks          rel-stack   postLinks              103,969    37      1s     10s     777s
```

### Fold-group label vocabulary (read off `build_obt`'s returned map — not guessed)

`build_obt` labels the fact's columns `fact`, its pkey `fact-key`, each folded dim's attributes `<prefix>` and **the FK column itself** `<prefix>-key` (`group[key_col] = f"{gname}-key"` — the fk IS the folded dim's identity column). Note the consequence: a fold whose key is itself a folded column (`post__OwnerUserId`) is **relabelled out of its parent group** into `postowner-key`.

**rel-stack-postlinks**

```
  fact                 2 cols   LinkTypeId, CreationDate
  fact-key             1 cols   Id
  post                 8 cols   post__PostTypeId, post__ParentId, post__OwnerDisplayName, post__Title, post__Tags, post__ContentLicense, … (+2)
  post-key             1 cols   PostId
  postowner            7 cols   postowner__AccountId, postowner__DisplayName, postowner__Location, postowner__ProfileImageUrl, postowner__WebsiteUrl, postowner__AboutMe, … (+1)
  postowner-key        1 cols   post__OwnerUserId
  related              8 cols   related__PostTypeId, related__ParentId, related__OwnerDisplayName, related__Title, related__Tags, related__ContentLicense, … (+2)
  related-key          1 cols   RelatedPostId
  relatedowner         7 cols   relatedowner__AccountId, relatedowner__DisplayName, relatedowner__Location, relatedowner__ProfileImageUrl, relatedowner__WebsiteUrl, relatedowner__AboutMe, … (+1)
  relatedowner-key     1 cols   related__OwnerUserId
  -- total            37 cols
```

## 3. Asserted structures — stack verdict x truth class

Truth per PROTOCOL.md: **in-group** = both columns in the same declared fold group (real dimension structure — a veto is a FALSE veto); **cross-group** = two different declared dim fold groups (join artifact — a veto is a TRUE veto); **fact-internal** = either column is fact-own (`fact` / `fact-key`) — reported, excluded from gate arithmetic.

### rel-stack-postlinks — 666 pairs scanned, 153 asserted (23.0%)

```
verdict            in-group    cross-group  fact-internal    total
MERGE                    18              0              0       18
HIERARCHY                60             56             17      133
ROLE                      1              1              0        2
TOTAL                    79             57             17      153
```

### All 1 measurable OBT(s) combined

```
verdict            in-group    cross-group  fact-internal    total
MERGE                    18              0              0       18
HIERARCHY                60             56             17      133
ROLE                      1              1              0        2
TOTAL                    79             57             17      153
```

Same asserts under the **fold harness's own residue taxonomy** (`probe_fold_grade.grade`: fact-internal only when BOTH columns are fact-own, so every fact-vs-dim pair lands in cross-group). PROTOCOL.md cites that taxonomy but its own bullet says *either* column — the two rules disagree, and the difference is exactly the fact-vs-dim asserts:

```
verdict            in-group    cross-group  fact-internal    total
MERGE                    18              0              0       18
HIERARCHY                61             72              0      133
ROLE                      1              1              0        2
TOTAL                    80             73              0      153
```

## 4. Asserted structures per fold group

### rel-stack-postlinks

```
group pair                                      MERGE   HIER   ROLE  total  class
related | related                                   3     16      1     20  in-group
post | postowner                                    0     18      0     18  cross-group
related | relatedowner                              0     18      0     18  cross-group
post | post                                         3     10      0     13  in-group
postowner | postowner                               1      9      0     10  in-group
relatedowner | relatedowner                         1      9      0     10  in-group
related | related-key                               3      5      0      8  in-group
related-key | relatedowner                          0      6      0      6  cross-group
post | post-key                                     3      3      0      6  in-group
post-key | postowner                                0      6      0      6  cross-group
fact | post                                         0      6      0      6  fact-internal
fact | postowner                                    0      6      0      6  fact-internal
postowner | postowner-key                           2      4      0      6  in-group
relatedowner | relatedowner-key                     2      4      0      6  in-group
post | postowner-key                                0      3      0      3  cross-group
related | relatedowner-key                          0      3      0      3  cross-group
fact | related                                      0      2      0      2  fact-internal
related-key | relatedowner-key                      0      1      0      1  cross-group
fact | post-key                                     0      1      0      1  fact-internal
post-key | postowner-key                            0      1      0      1  cross-group
fact | fact                                         0      1      0      1  fact-internal
fact | postowner-key                                0      1      0      1  fact-internal
post | related                                      0      0      1      1  cross-group

  in-group asserts concentrated by dim: related=28, post=19, postowner=16, relatedowner=16
```

## 5. Headline — cost of an exhaustive held-out leg

`calls = (asserted in-group + asserted cross-group) x 1 arm x 3 reps` (PROTOCOL.md: 3 repetitions per cell per arm; the held-out gate runs the winning arm only). Fact-internal asserts are excluded from the gate arithmetic and are listed separately.

```
OBT                           in-group   cross   gated   x3 reps    fact-internal
rel-stack-postlinks                 79      57     136       408               17
TOTAL                                              136       408               17
```

**408 LLM calls** for an exhaustive held-out leg over the 1 measurable OBT(s) (136 gated structures x 3 reps, one arm). Grading the 17 fact-internal asserts as well would add 51 calls (**459** total).

## 6. Examples — is the truth model plausible?

### asserted **in-group** (79 total; sample below)

```
  rel-stack-postlinks  MERGE            RelatedPostId <-> related__Title
    related-key | related   (bidirectional pair-count g3 + significant)
  rel-stack-postlinks  MERGE            RelatedPostId <-> related__Body
    related-key | related   (bidirectional pair-count g3 + significant)
  rel-stack-postlinks  MERGE            RelatedPostId <-> related__CreationDate
    related-key | related   (bidirectional pair-count g3 + significant)
  rel-stack-postlinks  MERGE            PostId <-> post__Title
    post-key | post   (bidirectional pair-count g3 + significant)
  rel-stack-postlinks  MERGE            PostId <-> post__Body
    post-key | post   (bidirectional pair-count g3 + significant)
  rel-stack-postlinks  MERGE            PostId <-> post__CreationDate
    post-key | post   (bidirectional pair-count g3 + significant)
  rel-stack-postlinks  MERGE            post__OwnerUserId <-> postowner__AccountId
    postowner-key | postowner   (bidirectional pair-count g3 + significant)
  rel-stack-postlinks  MERGE            post__OwnerUserId <-> postowner__CreationDate
    postowner-key | postowner   (bidirectional pair-count g3 + significant)
  rel-stack-postlinks  MERGE            post__Title <-> post__Body
    post | post   (bidirectional pair-count g3 + significant)
  rel-stack-postlinks  HIERARCHY/a->b   RelatedPostId <-> related__PostTypeId
    related-key | related   (row-g3 + lambda + perm-p)
  rel-stack-postlinks  HIERARCHY/a->b   RelatedPostId <-> related__ParentId
    related-key | related   (row-g3 + lambda + perm-p)
  rel-stack-postlinks  HIERARCHY/a->b   RelatedPostId <-> related__OwnerDisplayName
    related-key | related   (row-g3 + lambda + perm-p)
```

### asserted **cross-group** (57 total; sample below)

```
  rel-stack-postlinks  HIERARCHY/a->b   RelatedPostId <-> related__OwnerUserId
    related-key | relatedowner-key  [chain (fold-spec FK hop)]   (row-g3 + lambda + perm-p)
  rel-stack-postlinks  HIERARCHY/a->b   RelatedPostId <-> relatedowner__AccountId
    related-key | relatedowner  [chain (fold-spec FK hop)]   (row-g3 + lambda + perm-p)
  rel-stack-postlinks  HIERARCHY/a->b   RelatedPostId <-> relatedowner__DisplayName
    related-key | relatedowner  [chain (fold-spec FK hop)]   (row-g3 + lambda + perm-p)
  rel-stack-postlinks  HIERARCHY/a->b   RelatedPostId <-> relatedowner__Location
    related-key | relatedowner  [chain (fold-spec FK hop)]   (row-g3 + lambda + perm-p)
  rel-stack-postlinks  HIERARCHY/a->b   RelatedPostId <-> relatedowner__WebsiteUrl
    related-key | relatedowner  [chain (fold-spec FK hop)]   (row-g3 + lambda + perm-p)
  rel-stack-postlinks  HIERARCHY/a->b   RelatedPostId <-> relatedowner__AboutMe
    related-key | relatedowner  [chain (fold-spec FK hop)]   (row-g3 + lambda + perm-p)
  rel-stack-postlinks  HIERARCHY/a->b   RelatedPostId <-> relatedowner__CreationDate
    related-key | relatedowner  [chain (fold-spec FK hop)]   (row-g3 + lambda + perm-p)
  rel-stack-postlinks  HIERARCHY/a->b   PostId <-> post__OwnerUserId
    post-key | postowner-key  [chain (fold-spec FK hop)]   (row-g3 + lambda + perm-p)
  rel-stack-postlinks  HIERARCHY/a->b   PostId <-> postowner__AccountId
    post-key | postowner  [chain (fold-spec FK hop)]   (row-g3 + lambda + perm-p)
  rel-stack-postlinks  ROLE             post__OwnerDisplayName <-> related__ParentId
    post | related  [same-dim role (posts)]   (T1 membership-systematic vs LinkTypeId)
```

## 7. Truth-model audit — where 'cross-group == artifact' is shaky

Every asserted cross-group pair, sub-classified by **why** the two groups are different. This is diagnostic: the sub-class is replayed from the spec's own fold list and `schema.json`, and no verdict depends on it. The protocol scores all three sub-classes identically as *artifact, veto = TRUE veto*.

PROTOCOL.md defines cross-group as *"the columns belong to two independently declared dimensions **with no declared relationship between them**"*. Each sub-class below tests that stated precondition against the schema's own FK graph — the first four all **falsify it**:

- **chain (fold-spec FK hop)** — the spec itself folds one group's column into the other's dim (`post__OwnerUserId -> users`). A real two-hop dimension chain — exactly the structure DAT-757 counted as *truth* on rel-f1 (`raceId -> race__circuitId -> circuit__*`).
- **same-dim role** — both groups are folded from the SAME dim table via different FK roles. Same concept, deliberately distinct instances — i.e. the textbook ROLE verdict, which the stack asserting is *correct* behaviour.
- **declared FK -> identity (SAME entity)** — one column IS a declared FK into the very dim the other column IS the identity of. These are the same entity by construction of the declared schema; a MERGE here is right.
- **dim-FK** — the two source dim tables are related by a declared FK in `schema.json`, so they are not 'independently declared' in PROTOCOL's sense.
- **independent** — two dims with no declared relationship anywhere. **The only sub-class PROTOCOL's 'join artifact' reading actually describes.**

```
OBT                          sub-class                       MERGE   HIER   ROLE  total
rel-stack-postlinks          chain (fold-spec FK hop)            0     56      0     56
rel-stack-postlinks          same-dim role (posts)               0      0      1      1

ALL                          chain (fold-spec FK hop)            0     56      0     56
ALL                          same-dim role (posts)               0      0      1      1
```

**57 of 57 cross-group asserts (100%) are NOT independent dims** — they sit on a declared FK chain or are two roles of one dim. Under G-H2 every one of them counts as an artifact the judge is REWARDED for vetoing.

## 7b. Truth-model audit — the in-group side ('a veto here is a FALSE veto')

The gate's other half. G-H1 penalises the judge for every in-group assert it vetoes, so in-group must mean *real, groupable structure*. Shapes below are structural (group map + verdict only):

```
OBT                          shape                                               count
rel-stack-postlinks          attribute -> attribute HIERARCHY                       44
rel-stack-postlinks          key -> attribute HIERARCHY (the FK fold edge)          16
rel-stack-postlinks          key <-> attribute MERGE (identity or PROXY bijection?)     10
rel-stack-postlinks          attribute <-> attribute MERGE                           8
rel-stack-postlinks          ROLE (in-group)                                         1
```

**10 of 79 in-group asserts are `key <-> attribute` MERGEs.** A fold key is unique per dim row, so it is bijective with EVERY attribute of that row — the bijection is an artifact of the key's uniqueness, not evidence of shared identity. These are the dev set's own **P-proxy-bijection** and **E-free-text** shapes, whose pre-registered truth is **REJECT**. Vetoing them is the CORRECT call, yet G-H1 scores every one as a *false veto*:

```
  rel-stack-postlinks  MERGE  RelatedPostId <-> related__Title   [related-key | related]
  rel-stack-postlinks  MERGE  RelatedPostId <-> related__Body   [related-key | related]
  rel-stack-postlinks  MERGE  RelatedPostId <-> related__CreationDate   [related-key | related]
  rel-stack-postlinks  MERGE  PostId <-> post__Title   [post-key | post]
  rel-stack-postlinks  MERGE  PostId <-> post__Body   [post-key | post]
  rel-stack-postlinks  MERGE  PostId <-> post__CreationDate   [post-key | post]
  rel-stack-postlinks  MERGE  post__OwnerUserId <-> postowner__AccountId   [postowner-key | postowner]
  rel-stack-postlinks  MERGE  post__OwnerUserId <-> postowner__CreationDate   [postowner-key | postowner]
  rel-stack-postlinks  MERGE  related__OwnerUserId <-> relatedowner__AccountId   [relatedowner-key | relatedowner]
  rel-stack-postlinks  MERGE  related__OwnerUserId <-> relatedowner__CreationDate   [relatedowner-key | relatedowner]
```

### Named counterexamples (asserted, cross-group, and arguably real)

```
  rel-stack-postlinks  HIERARCHY/a->b   RelatedPostId <-> related__OwnerUserId
    related-key | relatedowner-key  [chain (fold-spec FK hop)]
  rel-stack-postlinks  HIERARCHY/a->b   RelatedPostId <-> relatedowner__AccountId
    related-key | relatedowner  [chain (fold-spec FK hop)]
  rel-stack-postlinks  HIERARCHY/a->b   RelatedPostId <-> relatedowner__DisplayName
    related-key | relatedowner  [chain (fold-spec FK hop)]
  rel-stack-postlinks  HIERARCHY/a->b   RelatedPostId <-> relatedowner__Location
    related-key | relatedowner  [chain (fold-spec FK hop)]
  rel-stack-postlinks  HIERARCHY/a->b   RelatedPostId <-> relatedowner__WebsiteUrl
    related-key | relatedowner  [chain (fold-spec FK hop)]
  rel-stack-postlinks  HIERARCHY/a->b   RelatedPostId <-> relatedowner__AboutMe
    related-key | relatedowner  [chain (fold-spec FK hop)]
  rel-stack-postlinks  HIERARCHY/a->b   RelatedPostId <-> relatedowner__CreationDate
    related-key | relatedowner  [chain (fold-spec FK hop)]
  rel-stack-postlinks  HIERARCHY/a->b   PostId <-> post__OwnerUserId
    post-key | postowner-key  [chain (fold-spec FK hop)]
  rel-stack-postlinks  HIERARCHY/a->b   PostId <-> postowner__AccountId
    post-key | postowner  [chain (fold-spec FK hop)]
  rel-stack-postlinks  HIERARCHY/a->b   PostId <-> postowner__DisplayName
    post-key | postowner  [chain (fold-spec FK hop)]
  rel-stack-postlinks  HIERARCHY/a->b   PostId <-> postowner__Location
    post-key | postowner  [chain (fold-spec FK hop)]
  rel-stack-postlinks  HIERARCHY/a->b   PostId <-> postowner__WebsiteUrl
    post-key | postowner  [chain (fold-spec FK hop)]
  rel-stack-postlinks  HIERARCHY/a->b   PostId <-> postowner__AboutMe
    post-key | postowner  [chain (fold-spec FK hop)]
  rel-stack-postlinks  HIERARCHY/a->b   PostId <-> postowner__CreationDate
    post-key | postowner  [chain (fold-spec FK hop)]
  rel-stack-postlinks  HIERARCHY/b->a   post__OwnerUserId <-> post__Title
    postowner-key | post  [chain (fold-spec FK hop)]
  … (+42 more)
```

## 8. Honest read — does the mechanical truth model hold up?

**No. On the one measurable OBT it is close to INVERTED relative to the dev set's own pre-registered labels.** Both halves fail, in opposite directions:

1. **cross-group is not 'artifact'.** 57/57 asserted cross-group pairs sit on a declared FK path or are two roles of one dim — **zero** are the 'independently declared dimensions with no declared relationship' PROTOCOL.md defines. `PostId -> postowner__Location` is the post's author's location: the exact two-hop shape DAT-757 counted as *truth* on rel-f1. G-H2 pays the judge 3:1 to destroy them.
2. **in-group is not all 'real'.** 10/79 in-group asserts are `key <-> attribute` MERGEs like `PostId <-> post__Body` — a bijection that exists only because the key is unique per dim row. That is the dev set's P-proxy-bijection / E-free-text shape, truth **REJECT**. G-H1 charges the judge a false veto for getting them right.

A judge could therefore *pass* G-H1+G-H2 by behaving exactly wrong, and *fail* by behaving exactly right. The fold-group map answers "which dim did this column arrive from?" — it was never a claim about groupability, which is the property the gate needs. Running the leg on this truth model would spend real money to measure the judge's agreement with an artifact of the fold spec.

**Recommendation: do not run the held-out leg as specified.** The counts above are the sizing you asked for and the leg is mechanically ready — but the sampling rule needs fixing first, and G-H3 is unreachable regardless (1 measurable database, gate needs >= 2). Options, none taken here — they are yours:

- **The blocker.** `fdlib.scan_pairs` computes every pair's joint distinct count in ONE DuckDB query, so cost scales with n_cols x total bytes: ~22-27 GB naive on all three OBTs vs a 38.3 GiB machine. R1 fits at 22.7 GB; R3 (22.5 GB) and R2 (26.5 GB) do not — R1 is itself near the edge. A chunked scan would fix it, but `fdlib` is frozen, so that is a decision, not a repair I should make. A DAT-762-owned scan proven identical to `scan_pairs` on the dev OBTs is the cheapest honest route to a second database.
- **The truth model.** If in-group/cross-group is kept, it needs to grade *groupability*, not fold provenance: at minimum exclude `<g>-key <-> attribute` bijections from in-group, and count declared-chain / same-dim-role pairs as real rather than artifact. That is a change to a pre-registered gate and must be an explicit, dated amendment — not something inferred from these numbers.
- **The corpus.** rel-avito / rel-event were CUT on C6 (opaque numeric dims) and on truncation integrity — but opaque numeric dims are exactly the cheap-to-scan case. If a second database matters more than text richness, that CUT is worth revisiting on its own terms.
