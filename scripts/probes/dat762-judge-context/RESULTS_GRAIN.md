# DAT-762 — can an LLM-free statistic filter the stack's false positives?

Probe: `scripts/probes/dat762-judge-context/probe_grain.py`. **ZERO LLM calls.**
Candidates C-A..C-D pre-registered in the probe docstring before the run; each gets
ONE grounded attempt, and a failure is CUT and recorded, never tuned. Frozen
instruments (`fdlib`, `cells`, `probe_fold_grade`, `probe_ablation`, `probe_heldout`)
are imported read-only.

Reference: RESULTS_DEV.md §2 — the C1 column is the mechanical stack v4's per-class
truth, and the target to beat. C1 = 33/45 overall, 12/12 on F/H/J, 0/9 on the veto
classes (D, E, P, G3).

**C1 reproduction control:** recomputed C1 scores 33/45 strict; RESULTS_DEV.md §3 records 33/45. Match.

## C-A — entity-grain near-key

`u(s) = distinct(s) / distinct(<key of s's fold group>)` — uniqueness of the
determinant at its OWN dimension's grain. Rule: reject the edge if
`u(s) >= 0.9` AND `s` is not itself the fold key. `KEY` marks a fold key
(exempt by the rule). Fact-group columns have no entity above the row, so their
denominator is `n_rows` — there C-A IS the frozen guard.

```
id  class               truth     C1        determinant                         d(s)   denom    u(s)  denominator                 C-A
P1  P-proxy-bijection   HIERARCHY MERGE     (raceId)                            1091    1091   1.000  distinct(raceId)            exempt (fold key)
P2  P-proxy-bijection   HIERARCHY MERGE     (SALESDOCUMENT)                    50000   50000   1.000  distinct(SALESDOCUMENT)     exempt (fold key)
D1  D-quasi-identifier  REJECT    HIERARCHY driver__dob                          839     857   0.979  distinct(driverId)          REJECT
D2  D-quasi-identifier  REJECT    HIERARCHY driver__dob                          839     857   0.979  distinct(driverId)          REJECT
D3  D-quasi-identifier  REJECT    HIERARCHY customer__postal_code              50862   60000   0.848  distinct(customer_id)       keep
D4  D-quasi-identifier  REJECT    HIERARCHY driver__surname                      798     857   0.931  distinct(driverId)          REJECT
E1  E-free-text         REJECT    HIERARCHY article__detail_desc               15348   31444   0.488  distinct(article_id)        keep
E2  E-free-text         REJECT    HIERARCHY article__detail_desc               15348   31444   0.488  distinct(article_id)        keep
F1  F-dirty-hierarchy   HIERARCHY HIERARCHY article__product_code              16210   31445   0.515  distinct(article_id)        keep
F2  F-dirty-hierarchy   HIERARCHY HIERARCHY article__product_code              16210   31445   0.515  distinct(article_id)        keep
F3  F-dirty-hierarchy   HIERARCHY HIERARCHY article__department_name             236   31467   0.007  distinct(article_id)        keep
F4  F-dirty-hierarchy   HIERARCHY HIERARCHY SHIPPINGPOINT                         85  212500   0.000  n_rows (fact grain)         keep
F5  F-dirty-hierarchy   HIERARCHY HIERARCHY circuit__location                     74      76   0.974  distinct(race__circuitId)   REJECT
H1  H-weak-true         HIERARCHY HIERARCHY SOLDTOPARTY                         6815    6815   1.000  distinct(SOLDTOPARTY)       exempt (fold key)
H2  H-weak-true         HIERARCHY HIERARCHY PLANT                                 38  190000   0.000  n_rows (fact grain)         keep
J1  J-true-fk           HIERARCHY HIERARCHY raceId                              1091    1091   1.000  distinct(raceId)            exempt (fold key)
J2  J-true-fk           HIERARCHY HIERARCHY driverId                             857     857   1.000  distinct(driverId)          exempt (fold key)
J3  J-true-fk           HIERARCHY HIERARCHY circuit__location                     74      76   0.974  distinct(race__circuitId)   REJECT
J4  J-true-fk           HIERARCHY HIERARCHY article_id                         31446   31446   1.000  distinct(article_id)        exempt (fold key)
J5  J-true-fk           HIERARCHY HIERARCHY SALESDOCUMENT                      50000   50000   1.000  distinct(SALESDOCUMENT)     exempt (fold key)
```

**Separation on `u(determinant)`, non-key determinants only** (fold keys are exempt by the rule and cannot be separated by it):

```
  false positives {D,E,P}: D1=0.979, D2=0.979, D4=0.931, D3=0.848, E1=0.488, E2=0.488
  real dims     {F,H,J}: F5=0.974, J3=0.974, F1=0.515, F2=0.515, F3=0.007, F4=0.000, H2=0.000
  min(FP) = 0.488   max(REAL) = 0.974   margin = -0.486  -> DOES NOT SEPARATE (overlap)
```

## C-B — RFI (Mandros-Boley-Vreeken)

`RFI(s->t) = FI(s->t) - E_perm[FI(s, shuffled t)]`, fdlib's existing implementation,
on the direction the stack asserted (or `a->b` where it asserted nothing).

```
id  class               truth     C1        direction                                         RFI
P1  P-proxy-bijection   HIERARCHY MERGE     raceId -> date                                 0.4557
P2  P-proxy-bijection   HIERARCHY MERGE     SALESDOCUMENT -> CREATIONTIMESTAMP             0.2427
D1  D-quasi-identifier  REJECT    HIERARCHY driver__dob -> driver__surname                 0.7204
D2  D-quasi-identifier  REJECT    HIERARCHY driver__dob -> driver__nationality             0.8944
D3  D-quasi-identifier  REJECT    HIERARCHY customer__postal_code -> customer__club_mem    0.3745
D4  D-quasi-identifier  REJECT    HIERARCHY driver__surname -> driver__nationality         0.8937
E1  E-free-text         REJECT    HIERARCHY article__detail_desc -> article__garment_gr    0.8215
E2  E-free-text         REJECT    HIERARCHY article__detail_desc -> article__index_grou    0.8625
F1  F-dirty-hierarchy   HIERARCHY HIERARCHY article__product_code -> article__product_t    0.7527
F2  F-dirty-hierarchy   HIERARCHY HIERARCHY article__product_code -> article__departmen    0.7033
F3  F-dirty-hierarchy   HIERARCHY HIERARCHY article__department_name -> article__garmen    0.9952
F4  F-dirty-hierarchy   HIERARCHY HIERARCHY SHIPPINGPOINT -> PLANT                         0.9944
F5  F-dirty-hierarchy   HIERARCHY HIERARCHY circuit__location -> circuit__alt              0.9751
H1  H-weak-true         HIERARCHY HIERARCHY SOLDTOPARTY -> doc__SALESOFFICE                0.5104
H2  H-weak-true         HIERARCHY HIERARCHY PLANT -> doc__SALESORGANIZATION                0.9973
J1  J-true-fk           HIERARCHY HIERARCHY raceId -> race__year                           0.6973
J2  J-true-fk           HIERARCHY HIERARCHY driverId -> driver__nationality                0.8948
J3  J-true-fk           HIERARCHY HIERARCHY circuit__location -> circuit__country          0.9854
J4  J-true-fk           HIERARCHY HIERARCHY article_id -> article__product_group_name      0.7285
J5  J-true-fk           HIERARCHY HIERARCHY SALESDOCUMENT -> doc__SALESORGANIZATION        0.5887
```

**Separation on RFI:**

```
  false positives {D,E,P}: D2=0.894, D4=0.894, E2=0.862, E1=0.821, D1=0.720, P1=0.456, D3=0.374, P2=0.243
  real dims     {F,H,J}: H2=0.997, F3=0.995, F4=0.994, J3=0.985, F5=0.975, J2=0.895, F1=0.753, J4=0.728, F2=0.703, J1=0.697, J5=0.589, H1=0.510
  FP range   [0.243, 0.894]
  REAL range [0.510, 0.997]
  overlap    YES
```

## C-C — cluster-aware permutation null

The row-wise `perm_pvalue` shreds the clustering: every row of one driver repeats
that driver's dob. DAT-544 recorded the permutation null as ICC-governed. C-C
deduplicates the OBT to one row per entity key of the DETERMINANT's fold group and
permutes the dependent inside that frame — the entity, not the row, is the
exchangeable unit.

```
id  class               truth     C1             p_row  p_entity  note
P1  P-proxy-bijection   HIERARCHY MERGE         0.0003    1.0000  dedup on raceId, n=1091, d(raceId)=1091 — TAUTOLOGY: determinant is a 
P2  P-proxy-bijection   HIERARCHY MERGE         0.0010    1.0000  dedup on SALESDOCUMENT, n=50000, d(SALESDOCUMENT)=50000 — TAUTOLOGY: d
D1  D-quasi-identifier  REJECT    HIERARCHY     0.0003    1.0000  dedup on driverId, n=857, d(driver__dob)=839
D2  D-quasi-identifier  REJECT    HIERARCHY     0.0003    0.5248  dedup on driverId, n=857, d(driver__dob)=839
D3  D-quasi-identifier  REJECT    HIERARCHY     0.0010    0.1045  dedup on customer_id, n=60000, d(customer__postal_code)=50862
D4  D-quasi-identifier  REJECT    HIERARCHY     0.0003    0.0003  dedup on driverId, n=857, d(driver__surname)=798
E1  E-free-text         REJECT    HIERARCHY     0.0010    0.0010  dedup on article_id, n=31446, d(article__detail_desc)=15348
E2  E-free-text         REJECT    HIERARCHY     0.0010    0.0010  dedup on article_id, n=31446, d(article__detail_desc)=15348
F1  F-dirty-hierarchy   HIERARCHY HIERARCHY     0.0010    0.0010  dedup on article_id, n=31446, d(article__product_code)=16210
F2  F-dirty-hierarchy   HIERARCHY HIERARCHY     0.0010    0.0010  dedup on article_id, n=31446, d(article__product_code)=16210
F3  F-dirty-hierarchy   HIERARCHY HIERARCHY     0.0010    0.0010  dedup on article_id, n=31446, d(article__department_name)=236
F4  F-dirty-hierarchy   HIERARCHY HIERARCHY     0.0010       n/a  fact-grain determinant — dedup is the identity (row grain)
F5  F-dirty-hierarchy   HIERARCHY HIERARCHY     0.0003    1.0000  dedup on race__circuitId, n=76, d(circuit__location)=74
H1  H-weak-true         HIERARCHY HIERARCHY     0.0010    1.0000  dedup on SOLDTOPARTY, n=6815, d(SOLDTOPARTY)=6815 — TAUTOLOGY: determi
H2  H-weak-true         HIERARCHY HIERARCHY     0.0010       n/a  fact-grain determinant — dedup is the identity (row grain)
J1  J-true-fk           HIERARCHY HIERARCHY     0.0003    1.0000  dedup on raceId, n=1091, d(raceId)=1091 — TAUTOLOGY: determinant is a 
J2  J-true-fk           HIERARCHY HIERARCHY     0.0003    1.0000  dedup on driverId, n=857, d(driverId)=857 — TAUTOLOGY: determinant is 
J3  J-true-fk           HIERARCHY HIERARCHY     0.0003    0.0017  dedup on race__circuitId, n=76, d(circuit__location)=74
J4  J-true-fk           HIERARCHY HIERARCHY     0.0010    1.0000  dedup on article_id, n=31446, d(article_id)=31446 — TAUTOLOGY: determi
J5  J-true-fk           HIERARCHY HIERARCHY     0.0010    1.0000  dedup on SALESDOCUMENT, n=50000, d(SALESDOCUMENT)=50000 — TAUTOLOGY: d
```

## C-D — fold-key-aware alias rule (provenance, no statistic)

For a bidirectional (MERGE) assert: if exactly one side is a fold key and the other
is an attribute of THE SAME fold group, the verdict is HIERARCHY (key -> attribute),
never MERGE. Applied to P and — as the pre-registered regression check — to A/B.

```
id  class               truth     C1        group(a)        group(b)        C-D fires   result
A1  A-true-alias        MERGE     MERGE     article         article         -           untouched
A2  A-true-alias        MERGE     MERGE     article         article         -           untouched
A3  A-true-alias        MERGE     MERGE     article         article         -           untouched
A4  A-true-alias        MERGE     MERGE     article         article         -           untouched
A5  A-true-alias        MERGE     MERGE     constructor     constructor     -           untouched
A6  A-true-alias        MERGE     MERGE     circuit-key     circuit         a->b        MERGE -> HIERARCHY/a->b  (DAMAGE)
B1  B-dirty-alias       MERGE     MERGE     article         article         -           untouched
B2  B-dirty-alias       MERGE     MERGE     fact            race            -           untouched
P1  P-proxy-bijection   HIERARCHY MERGE     race-key        fact            -           untouched
P2  P-proxy-bijection   HIERARCHY MERGE     doc-key         fact            -           untouched
```

## Combined filter — C1 vs C1 + filter (C-A + C-D)

No candidate passed its own separation gate, so this is not the pre-registered
'apply the ones that pass' — it is what applying them ANYWAY costs, which is the
number the question turns on. C-B is unusable (no threshold exists) and C-C is
undefined on key determinants, so the combination is C-A + C-D.

```
class                      n      C1   C1+filter   delta
A-true-alias               6       6           5      -1
B-dirty-alias              2       2           2      +0
C-role                     5       4           4      +0
D-quasi-identifier         4       0           3      +3
E-free-text                2       0           0      +0
F-dirty-hierarchy          5       5           4      -1
G-grain                    3       2           3      +1
H-weak-true                2       2           2      +0
I-vacuous-skew             3       3           3      +0
J-true-fk                  5       5           4      -1
K-disjoint-conform         2       0           0      +0
L-false-friend             3       3           3      +0
M-measure-derived          1       1           1      +0
P-proxy-bijection          2       0           0      +0
TOTAL                     45      33          34      +1

VETO (D,E,P)               8       0           3      +3
STATS-OWNED (F,H,J)       12      12          10      -2
```

**F/H/J recall: 10/12** (C1 = 12/12). LOST — kill condition.

**Every cell the filter changed:**

```
  A6  A-true-alias        truth=MERGE     MERGE                  -> HIERARCHY/a->b        BROKE
      C-D fold-key provenance: key -> attribute
  D1  D-quasi-identifier  truth=REJECT    HIERARCHY/a->b         -> REJECT                FIXED
      C-A entity-grain near-key on driver__dob
  D2  D-quasi-identifier  truth=REJECT    HIERARCHY/a->b         -> REJECT                FIXED
      C-A entity-grain near-key on driver__dob
  D4  D-quasi-identifier  truth=REJECT    HIERARCHY/a->b         -> REJECT                FIXED
      C-A entity-grain near-key on driver__surname
  F5  F-dirty-hierarchy   truth=HIERARCHY HIERARCHY/a->b         -> REJECT                BROKE
      C-A entity-grain near-key on circuit__location
  G3  G-grain             truth=REJECT    HIERARCHY/a->b         -> REJECT                FIXED
      C-A entity-grain near-key on doc__CREATIONTIMESTAMP
  J3  J-true-fk           truth=HIERARCHY HIERARCHY/a->b         -> REJECT                BROKE
      C-A entity-grain near-key on circuit__location
```

## Post-hoc diagnostic — the most generous LLM-free combination

**Not pre-registered, not a verdict, and not a threshold search.** C-A fires on
F5/J3 because `u` alone cannot see that a near-unique determinant is still a real
dimension. C-C is strictly better informed on the D class (it rejects D3 at
u=0.848, which C-A's guard misses) and is *undefined* — not passed — where the
determinant is its own group's key. Applying C-C only where it is defined, with
the same fold-key precondition C-A already carries, is the friendliest reading of
the LLM-free stack. It is reported to show that the residue survives even it.

```
class                      n      C1      C1+C-C   delta
A-true-alias               6       6           6      +0
B-dirty-alias              2       2           2      +0
C-role                     5       4           4      +0
D-quasi-identifier         4       0           3      +3
E-free-text                2       0           0      +0
F-dirty-hierarchy          5       5           4      -1
G-grain                    3       2           2      +0
H-weak-true                2       2           2      +0
I-vacuous-skew             3       3           3      +0
J-true-fk                  5       5           5      +0
K-disjoint-conform         2       0           0      +0
L-false-friend             3       3           3      +0
M-measure-derived          1       1           1      +0
P-proxy-bijection          2       0           0      +0
TOTAL                     45      33          35      +2

VETO (D,E,P)               8       0           3      +3
STATS-OWNED (F,H,J)       12      12          11      -1
```

**F/H/J recall: 11/12** (C1 = 12/12). LOST — kill condition.

**Every cell the filter changed:**

```
  D1  D-quasi-identifier  truth=REJECT    HIERARCHY/a->b         -> REJECT                FIXED
      C-C entity-grain null not cleared on driver__dob (p=1.0000)
  D2  D-quasi-identifier  truth=REJECT    HIERARCHY/a->b         -> REJECT                FIXED
      C-C entity-grain null not cleared on driver__dob (p=0.5248)
  D3  D-quasi-identifier  truth=REJECT    HIERARCHY/a->b         -> REJECT                FIXED
      C-C entity-grain null not cleared on customer__postal_code (p=0.1045)
  F5  F-dirty-hierarchy   truth=HIERARCHY HIERARCHY/a->b         -> REJECT                BROKE
      C-C entity-grain null not cleared on circuit__location (p=1.0000)
```

## Held-out reality check — rel-stack / postLinks (153 stack asserts)

`heldout_asserts.json`, the exact pairs the frozen stack asserts on an untouched
database. **Not graded** against the FK-derived in-group/cross-group truth model —
HELDOUT_COUNTS.md found that model INVERTED (57/57 'cross-group' pairs sit on
declared FK paths; 10/79 'in-group' are key<->attribute bijections that SHOULD be
vetoed). Raw removals for human inspection, never a score.

```
  asserts in            153
  removed (-> REJECT)   82
  re-typed (C-D)        10
  kept unchanged        61
```

**Removals by the group taxonomy** (the taxonomy is descriptive here, not truth):

```
  removed    cross-group=42  in-group=40
  re-typed   in-group=10
  kept       cross-group=15  fact-internal=17  in-group=29

  removed, by cross_sub (schema FK provenance of the pair):
      40  (in-group/fact)
      42  chain (fold-spec FK hop)
```

**~10 concrete REMOVALS (of 82)**

```
  post__OwnerUserId                   post__Title                         HIERARCHY/b->a       -> REJECT     [cross-group]
      C-A entity-grain near-key on post__Title
  post__OwnerUserId                   post__Body                          HIERARCHY/b->a       -> REJECT     [cross-group]
      C-A entity-grain near-key on post__Body
  post__OwnerUserId                   post__CreationDate                  HIERARCHY/b->a       -> REJECT     [cross-group]
      C-A entity-grain near-key on post__CreationDate
  post__OwnerDisplayName              post__Title                         HIERARCHY/b->a       -> REJECT     [in-group]
      C-A entity-grain near-key on post__Title
  post__OwnerDisplayName              post__Body                          HIERARCHY/b->a       -> REJECT     [in-group]
      C-A entity-grain near-key on post__Body
  post__OwnerDisplayName              post__CreationDate                  HIERARCHY/b->a       -> REJECT     [in-group]
      C-A entity-grain near-key on post__CreationDate
  post__Title                         post__Tags                          HIERARCHY/a->b       -> REJECT     [in-group]
      C-A entity-grain near-key on post__Title
  post__Title                         post__ContentLicense                HIERARCHY/a->b       -> REJECT     [in-group]
      C-A entity-grain near-key on post__Title
  post__Title                         postowner__AccountId                HIERARCHY/a->b       -> REJECT     [cross-group]
      C-A entity-grain near-key on post__Title
  post__Title                         postowner__DisplayName              HIERARCHY/a->b       -> REJECT     [cross-group]
      C-A entity-grain near-key on post__Title
```

**~10 concrete RE-TYPINGS (of 10)**

```
  RelatedPostId                       related__Title                      MERGE                -> HIERARCHY  [in-group]
      C-D fold-key provenance: key -> attribute
  RelatedPostId                       related__Body                       MERGE                -> HIERARCHY  [in-group]
      C-D fold-key provenance: key -> attribute
  RelatedPostId                       related__CreationDate               MERGE                -> HIERARCHY  [in-group]
      C-D fold-key provenance: key -> attribute
  PostId                              post__Title                         MERGE                -> HIERARCHY  [in-group]
      C-D fold-key provenance: key -> attribute
  PostId                              post__Body                          MERGE                -> HIERARCHY  [in-group]
      C-D fold-key provenance: key -> attribute
  PostId                              post__CreationDate                  MERGE                -> HIERARCHY  [in-group]
      C-D fold-key provenance: key -> attribute
  post__OwnerUserId                   postowner__AccountId                MERGE                -> HIERARCHY  [in-group]
      C-D fold-key provenance: key -> attribute
  post__OwnerUserId                   postowner__CreationDate             MERGE                -> HIERARCHY  [in-group]
      C-D fold-key provenance: key -> attribute
  related__OwnerUserId                relatedowner__AccountId             MERGE                -> HIERARCHY  [in-group]
      C-D fold-key provenance: key -> attribute
  related__OwnerUserId                relatedowner__CreationDate          MERGE                -> HIERARCHY  [in-group]
      C-D fold-key provenance: key -> attribute
```

**~10 concrete KEEPS (of 61)**

```
  RelatedPostId                       related__OwnerUserId                HIERARCHY/a->b       -> HIERARCHY  [cross-group]
      stack
  RelatedPostId                       related__PostTypeId                 HIERARCHY/a->b       -> HIERARCHY  [in-group]
      stack
  RelatedPostId                       related__ParentId                   HIERARCHY/a->b       -> HIERARCHY  [in-group]
      stack
  RelatedPostId                       related__OwnerDisplayName           HIERARCHY/a->b       -> HIERARCHY  [in-group]
      stack
  RelatedPostId                       related__Tags                       HIERARCHY/a->b       -> HIERARCHY  [in-group]
      stack
  RelatedPostId                       related__ContentLicense             HIERARCHY/a->b       -> HIERARCHY  [in-group]
      stack
  RelatedPostId                       relatedowner__AccountId             HIERARCHY/a->b       -> HIERARCHY  [cross-group]
      stack
  RelatedPostId                       relatedowner__DisplayName           HIERARCHY/a->b       -> HIERARCHY  [cross-group]
      stack
  RelatedPostId                       relatedowner__Location              HIERARCHY/a->b       -> HIERARCHY  [cross-group]
      stack
  RelatedPostId                       relatedowner__WebsiteUrl            HIERARCHY/a->b       -> HIERARCHY  [cross-group]
      stack
```

**Per-column `u(s)` for every determinant the filter removed** (the number the rule fires on):

```
  post__Title                             d=  50782  u=0.999   distinct(PostId)
  post__Body                              d=  50807  u=1.000   distinct(PostId)
  post__CreationDate                      d=  50813  u=1.000   distinct(PostId)
  related__Title                          d=  31907  u=0.995   distinct(RelatedPostId)
  related__Body                           d=  32080  u=1.000   distinct(RelatedPostId)
  related__CreationDate                   d=  32079  u=1.000   distinct(RelatedPostId)
  postowner__AccountId                    d=  29268  u=1.000   distinct(post__OwnerUserId)
  postowner__CreationDate                 d=  29268  u=1.000   distinct(post__OwnerUserId)
  relatedowner__AccountId                 d=  18137  u=1.000   distinct(related__OwnerUserId)
  relatedowner__DisplayName               d=  16474  u=0.908   distinct(related__OwnerUserId)
  relatedowner__CreationDate              d=  18137  u=1.000   distinct(related__OwnerUserId)
```

## Verdicts — one grounded attempt each

### C-A — entity-grain near-key: **CUT**

Does not separate. `min(u) over {D,E,P}` = 0.488 (E1/E2 `article__detail_desc`) sits far BELOW `max(u) over {F,H,J}` = 0.974 (F5/J3 `circuit__location`) — margin **-0.486**, a total overlap, not a near miss.

**The hypothesis is falsified by a clean counterexample.** The *measurement* half
of it is correct and worth keeping in mind: `driver__dob` really is 0.979 of the
driver entity, not the 0.03 the fact-row denominator reports, so the guard's
denominator IS wrong. But the *inference* — near-superkey of its entity therefore
arithmetic, not semantics — is false. `circuit__location` is 0.974 unique among
circuits and its FDs are real: a location has one altitude (F5) and one country
(J3). Meanwhile `article__detail_desc` at 0.488 is nowhere near a key and its FD
is a pure artifact. Entity-grain uniqueness is simply not the axis that separates a
dimension from an artifact.

At `NEAR_KEY_FRAC = 0.9` it buys D1, D2, D4, G3 and costs F5, J3, while missing D3
(0.848), E1 and E2. No other cutoff does better — the classes are interleaved, and
searching for one would be the tuning this gate exists to prevent.

### C-B — RFI: **CUT**

No threshold exists. The false positives run up to RFI 0.894 (D2) and 0.894 (D4), above **9 of the 12** real dimensions — H1 0.510, J5 0.589, J1 0.697, F2 0.703, J4 0.728, F1 0.753. The ranges are nested, not adjacent.

This is not a calibration failure, it is a category error, and it was predictable
from what RFI measures. RFI chance-corrects a dependence estimate. The D and E false
positives are not weak or unreliable dependences — `detail_desc` genuinely predicts
`garment_group_name`, `dob` genuinely predicts `surname`. They are *strong, real*
dependences that are not dimension edges. A reliability correction cannot reject a
dependence that is really there.

### C-C — cluster-aware permutation null: **CUT as a filter; the statistic itself is sound**

Two distinct results, and they point opposite ways.

**1. DAT-544 is confirmed, emphatically.** The row-wise null is worthless on folded
data: D1 `driver__dob -> driver__surname` reads p_row = 0.0003 (wildly
significant) and p_entity = 1.0000 (pure chance). Same columns, same
data — the only difference is whether the 26,080 fact rows are treated as 26,080
independent observations or as the 857 drivers they actually are. Every clustered
attribute pair in a folded OBT is 'significant' under the row-wise null. **This is a
real defect in the frozen stack, independent of the filter question.**

**2. It cannot be a filter, for a structural reason no threshold reaches.** Where the
determinant IS its group's key, deduplication makes it a perfect key by construction
— FI = null = 1, p = 1.0. That is 7 of the 20 measured cells and **5 of the 12**
stats-owned (H1, J1, J2, J4, J5). Applied as written, C-C destroys the entire FK
fold-edge class. The finding underneath is worth stating plainly: **at entity grain, a
key -> attribute edge is a tautology.** It is real dimension structure that carries no
statistical evidence at all — it is true by provenance, and no test can confirm what
is true by construction.

Where it IS defined it is the best instrument in this probe — it rejects all three
reachable quasi-identifiers (D1 p=1.0000, D2 p=0.5248, D3 p=0.1045), including D3 which C-A's guard misses. And it still
cannot touch E (E1 p=0.0010, E2 p=0.0010) or D4 (p=0.0003), and it still costs F5 (p=1.0000).

**F5 deserves its own note, because it is not really C-C's error.** A 74-distinct
determinant over 76 circuits predicts anything about as well by chance, so the
statistic is telling the truth: **the evidence for F5 is not in this data.** The same
point lands harder on the stack's OWN g3 gate, recomputed at the two grains — same
Kivinen-Mannila statistic, same `FD_MAX_G3 = 0.01` gate, only the denominator moves:

```
id  edge                                            g3 @ row grain  g3 @ entity grain
F5  circuit__location -> circuit__alt                 0.0025 pass        0.0263 FAIL 
J3  circuit__location -> circuit__country             0.0000 pass        0.0000 pass 
D1  driver__dob -> driver__surname                    0.0016 pass        0.0210 FAIL 
F1  article__product_code -> article__product_typ     0.0076 pass        0.0066 pass 
E1  article__detail_desc -> article__garment_grou     0.0058 pass        0.0098 pass 
```

F5's two same-city exceptions are 0.0263 of 76 circuits — which FAILS the
stack's own 0.01 gate — but only 0.0025 of 26,080 rows, which passes it. **The
stack asserts F5 only because the row-wise view dilutes the exceptions.** The edge is
true because of geography, not because of its numbers; the row grain reaches the
right answer for the wrong reason, and the entity grain reaches the wrong answer for
the right one. That is the residue in its purest form.

### C-D — fold-key alias rule: **CUT**

Zero gains, one loss — and both halves of the pre-registered premise were factually
wrong about this data.

**It never reaches P.** P1's `date` and P2's `CREATIONTIMESTAMP` are FACT columns
(group `fact` / `fact`), not attributes of the key's fold group, so the
rule's precondition is not met and it does not fire. The expectation that C-D would
fix the P class was a structural misreading of where those columns live.

**And 'NEITHER side is a fold key' is false for A6.** `race__circuitId` (`circuit-key`) <-> `circuit__name` (`circuit`) is exactly the rule's trigger:
a fold key bijective with a same-group attribute. Its truth is MERGE. C-D breaks it.

**The reason this matters more than a 1-cell loss.** On the held-out DB the same rule
fires 10/10 and looks *right* every time (`PostId <-> post__Title`, `<-> post__Body`,
`<-> post__CreationDate` — a post's title is an attribute the post has, not the post's
identity). On the dev set it fires once and is wrong (a circuit's name IS the
circuit's identity). **Provenance is identical in both cases.** `circuit__name` and
`post__Title` are both unique-per-entity text hanging off a fold key; nothing
structural distinguishes the entity's NAME from an attribute that happens to be
unique. That question — identity encoding or attribute? — is meaning, and the rule
gets the majority right while being silently wrong on the identity encodings.

## The honest read

**Can a named, grounded, LLM-free statistic filter the stack's false positives
without losing the real dimensions? On this evidence: no.** All four candidates are
CUT after one grounded attempt each. The combined filter turns 33/45 into 34/45 by
trading 3 false positives for 2 real dimensions; the most generous LLM-free reading
(C-C where defined) reaches 35/45 and still costs F5, and neither clears the
12/12 F/H/J floor. **The false-positive problem is not a statistics problem.**

**Two real defects were found on the way, and they are worth landing on their own
merits — as measurements, not as filters.**

1. **The near-key denominator IS wrong** (the hypothesis's measurement half). A fold
   attribute is measured against the fact's row count, so `driver__dob` reads 0.03
   when it is 0.979 of the driver entity. Any near-key reasoning on a folded OBT is
   currently reading a number that means nothing.
2. **The row-wise permutation null is inflated by clustering** (DAT-544, now
   confirmed on real folded data at p_row 0.0003 vs p_entity 1.0). The stack's
   per-pair perm-p is not measuring what it claims on any folded dimension.

Fixing both is correct and changes the D class. Neither fixes E, D4, P, or the
A-vs-P bijection question — and #2 must be gated by the fold-key exemption or it
deletes every FK fold edge. **Neither is a licence to build the filter this probe
was asked to find.**

### The residue that genuinely needs semantics

Stated as measured pairs, not as a category:

1. **E vs F1 — the cleanest demonstration in the probe.** Same OBT, same entity,
   same grain, and the numbers do not differ:

```
                                            u(s)    p_entity      RFI
  E1 article__detail_desc  -> garment_group_name   0.488     0.0010   0.821   truth REJECT
  F1 article__product_code -> product_type_name    0.515     0.0010   0.753   truth HIERARCHY
```

   A description and a product code, statistically indistinguishable. One is a
   merchandising hierarchy; the other is prose that happens to predict it. **No
   statistic splits 0.488 from 0.515.** The difference is entirely what the
   columns mean.

2. **D4 — where the statistic is RIGHT and the assert is still wrong.**
   `driver__surname -> driver__nationality`, p_entity = 0.0003, RFI = 0.894.
   Surnames really do cluster by nationality; the dependence survives the
   cluster-aware null because it is genuinely there. 'Real signal' and 'groupable
   dimension level' are different predicates, and **no null-hypothesis test can
   reject a true dependence.** This one is unreachable by construction.

3. **Bijection: identity encoding, or attribute?** A6 `race__circuitId <-> circuit__name`
   (MERGE) and the held-out `PostId <-> post__Title` (correctly HIERARCHY) are
   provenance-identical to the byte: a fold key bijective with unique-per-entity
   text of its own group. Is the bijective partner the entity's name, or something
   the entity has? Meaning — and C-D's 10-right/1-wrong record is exactly what a
   rule that cannot see meaning looks like.

4. **F5/J3 vs D1 — 0.974 against 0.979.** `circuit__location` and `driver__dob` are
   0.005 apart on the axis C-A ranks them by, on opposite sides of the
   truth. A location determines an altitude because of geography; a birthday
   determines nothing about a surname despite the arithmetic working out. Meaning
   again.

**What the residue is, in one line:** every surviving false positive is a *true and
strong statistical dependence that is not a dimension*, and every real dimension the
filters destroy is *true for reasons the data does not contain*. Those are the two
failure modes no statistic can address, because in both the statistic is already
correct — it is the question being asked of it that needs meaning. That is the case
for a semantic lane, and it is also the boundary of one: the lane is needed for E,
D4, P/A bijections and low-power edges like F5, and is NOT needed for D1/D2/D3 or
G3, which the two measurement fixes above reach without any LLM.

