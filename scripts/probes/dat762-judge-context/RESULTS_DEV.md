# DAT-762 judge-context spike — dev leg results

Protocol: `PROTOCOL.md` (frozen). Judge `claude-sonnet-5`, max_tokens=400, model-default sampling. 45 cells x 4 arms x 3 reps = 540 gradings. C1 = mechanical stack v4 (no LLM).

Scoring: strict = verdict + direction (HIERARCHY truth is always `a->b`); lax = direction-insensitive. Ranges are min-max over the 3 reps; `r1` is the rep-1 point value (the grain the DAT-757 scorecard was measured at).

### Instrument notes (measured at pre-flight, before any LLM call; not fixed — the DAT-757 instrument is frozen and both artifacts hit every arm identically)

- **L3 (`number` vs `grid`)** renders `value_set_jaccard = 0.0` because `number` stringifies as float ("6.0") and `grid` as int ("0"), so the cell's "overlapping integers" premise is invisible to every judge. Pre-registered in PROTOCOL.md; scores reported, cell noted as compromised for class L.
- **`col_profile` top-values tie-order is nondeterministic per render.** polars' `value_counts().sort("count")` does not break ties stably, so each construction of the same arm can list equal-frequency values in a different order — and where the top-6 boundary falls inside a tie (near-key determinants: `raceId`, `SALESDOCUMENT`, `date`, `grid`), a different subset of tied values is shown. Verified at pre-flight: `random_samples` ARE identical across arms for every cell (the rng governs those, and it is constructed fresh per call), and n_rows/n_distinct/null_rate are identical; only the display order/membership of tied top-values moves. This is unbiased noise shared by V/VR/VH and by DAT-757's C3, not a systematic difference between arms — but it is a real contributor to the instability measured in section 4.
- **The judge sometimes thinks unprompted.** `claude-sonnet-5` at model-default sampling sporadically emits a `ThinkingBlock` before its text block, with no thinking parameter requested. This surfaced as a bug: `probe_ablation.ask` reads `content[0].text`, which raises on those responses — all 4 retries failed and an `ERROR` verdict was cached, which would have scored as a silent miss (2 hits on H2:V before the fix). `probe_dev.ask` now takes the first *text* block, never caches an ERROR as a verdict, and records `_thinking`. Evidence, stated exactly: both cached ERRORs exhausted all 4 retries and the final attempt of each raised the ThinkingBlock error, so between 2 and 8 calls emitted a thinking block — all of them on the single prompt H2:V, none anywhere else in 540 calls. The 2 post-fix re-calls of that same prompt did NOT think (and returned ROLE x3 with the third rep — a stable verdict the ERROR had been masking), so the behaviour is sporadic and time-clustered, not prompt-determined. Spontaneous-thinking count per arm over the 2 calls made after the flag existed: {'N': 0, 'V': 0, 'VR': 0, 'VH': 0}. **This is a live confound for the protocol's VH-think arm**, which assumes the core arms are non-thinking: they are almost always, but not strictly, non-thinking, and the probe cannot certify which of the 538 pre-flag calls thought.

## 1. Per-cell verdicts (3-rep distribution; OK/MISS = rep-1 strict; conf = modal)

```
id  class               truth     C1         N (3 reps)                         V (3 reps)                         VR (3 reps)                        VH (3 reps)                       
A1  A-true-alias        MERGE     OK         OK   MERGEx3              high   OK   MERGEx3              high   OK   MERGEx3              high   OK   MERGEx3              high  
A2  A-true-alias        MERGE     OK         OK   MERGEx3              high   OK   MERGEx3              high   OK   MERGEx3              high   OK   MERGEx3              high  
A3  A-true-alias        MERGE     OK         OK   MERGEx3              high   OK   MERGEx3              high   OK   MERGEx3              high   OK   MERGEx3              high  
A4  A-true-alias        MERGE     OK         OK   MERGEx3              high   OK   MERGEx3              high   OK   MERGEx3              high   OK   MERGEx3              high  
A5  A-true-alias        MERGE     OK         OK   MERGEx3              high   OK   MERGEx3              high   OK   MERGEx3              high   OK   MERGEx3              high  
A6  A-true-alias        MERGE     OK         MISS HIERARCHYx3          high   OK   MERGEx3              high   OK   MERGEx3              high   OK   MERGEx3              high  
B1  B-dirty-alias       MERGE     OK         OK   MERGEx3              high   OK   MERGEx3              high   OK   MERGEx3              high   OK   MERGEx3              high  
B2  B-dirty-alias       MERGE     OK         OK   MERGEx3              high   OK   MERGEx3              high   OK   MERGEx3              high   OK   MERGEx3              high  
P1  P-proxy-bijection   HIERARCHY MERGE      OK   HIERARCHYx3          high   MISS MERGEx2,HIERARCHYx1  high   OK   MERGEx2,HIERARCHYx1  high   OK   REJECTx2,HIERARCHYx1 high  
P2  P-proxy-bijection   HIERARCHY MERGE      MISS REJECTx3             high   MISS REJECTx3             high   MISS REJECTx3             high   MISS REJECTx3             high  
C1  C-role              ROLE      OK         OK   ROLEx3               high   OK   ROLEx3               high   OK   ROLEx3               high   OK   ROLEx3               high  
C2  C-role              ROLE      OK         OK   ROLEx3               high   OK   ROLEx3               high   OK   ROLEx3               high   OK   ROLEx3               high  
C3  C-role              ROLE      OK         OK   ROLEx3               high   OK   ROLEx3               high   OK   ROLEx3               high   OK   ROLEx3               high  
C4  C-role              ROLE      OK         OK   ROLEx3               high   OK   ROLEx3               high   OK   ROLEx3               high   OK   ROLEx3               high  
C5  C-role              ROLE      REJECT     MISS REJECTx3             high   OK   ROLEx3               high   OK   ROLEx3               high   OK   ROLEx3               high  
D1  D-quasi-identifier  REJECT    HIERAR     OK   REJECTx3             high   MISS ROLEx2,REJECTx1      high   OK   REJECTx3             high   OK   REJECTx3             high  
D2  D-quasi-identifier  REJECT    HIERAR     OK   REJECTx3             high   OK   REJECTx3             high   OK   REJECTx3             high   OK   REJECTx3             high  
D3  D-quasi-identifier  REJECT    HIERAR     OK   REJECTx3             high   OK   REJECTx3             high   OK   REJECTx3             high   OK   REJECTx3             high  
D4  D-quasi-identifier  REJECT    HIERAR     OK   REJECTx3             high   MISS HIERARCHYx3          high   MISS HIERARCHYx3          medium OK   REJECTx3             high  
E1  E-free-text         REJECT    HIERAR     OK   REJECTx3             high   OK   REJECTx3             high   OK   REJECTx3             high   OK   REJECTx3             high  
E2  E-free-text         REJECT    HIERAR     OK   REJECTx3             high   OK   REJECTx3             high   OK   REJECTx3             high   OK   REJECTx3             high  
F1  F-dirty-hierarchy   HIERARCHY OK         MISS REJECTx3             high   OK   HIERARCHYx3          high   OK   HIERARCHYx3          high   OK   HIERARCHYx3          high  
F2  F-dirty-hierarchy   HIERARCHY OK         MISS REJECTx3             high   OK   HIERARCHYx3          medium OK   HIERARCHYx3          high   OK   HIERARCHYx3          high  
F3  F-dirty-hierarchy   HIERARCHY OK         MISS REJECTx3             high   MISS ROLEx3               medium OK   ROLEx2,HIERARCHYx1   medium OK   HIERARCHYx3          high  
F4  F-dirty-hierarchy   HIERARCHY OK         MISS ROLEx3               medium MISS ROLEx3               medium MISS ROLEx3               high   OK   HIERARCHYx3          high  
F5  F-dirty-hierarchy   HIERARCHY OK         OK   HIERARCHYx3          medium OK   HIERARCHYx3          high   OK   HIERARCHYx3          high   OK   HIERARCHYx3          high  
G1  G-grain             HIERARCHY OK         OK   HIERARCHYx3          medium OK   HIERARCHYx3          high   OK   HIERARCHYx3          high   OK   HIERARCHYx3          high  
G2  G-grain             HIERARCHY OK         MISS REJECTx3             high   MISS REJECTx3             medium MISS REJECTx3             high   OK   HIERARCHYx3          high  
G3  G-grain             REJECT    HIERAR     OK   REJECTx3             high   OK   REJECTx3             high   OK   REJECTx3             high   OK   REJECTx3             high  
H1  H-weak-true         HIERARCHY OK         MISS REJECTx3             high   MISS REJECTx3             high   MISS REJECTx3             high   OK   HIERARCHYx3          medium
H2  H-weak-true         HIERARCHY OK         MISS ROLEx3               medium MISS ROLEx3               medium OK   HIERARCHYx3          high   OK   HIERARCHYx3          medium
I1  I-vacuous-skew      REJECT    OK         OK   REJECTx3             high   OK   REJECTx3             high   OK   REJECTx3             high   OK   REJECTx3             high  
I2  I-vacuous-skew      REJECT    OK         OK   REJECTx3             medium OK   REJECTx3             high   OK   REJECTx3             high   OK   REJECTx3             high  
I3  I-vacuous-skew      REJECT    OK         OK   REJECTx3             high   OK   REJECTx3             high   OK   REJECTx3             high   OK   REJECTx3             high  
J1  J-true-fk           HIERARCHY OK         OK   HIERARCHYx3          high   OK   HIERARCHYx3          high   OK   HIERARCHYx3          high   OK   HIERARCHYx3          high  
J2  J-true-fk           HIERARCHY OK         OK   HIERARCHYx3          high   OK   HIERARCHYx3          high   OK   HIERARCHYx3          high   OK   HIERARCHYx3          high  
J3  J-true-fk           HIERARCHY OK         OK   HIERARCHYx3          high   OK   HIERARCHYx3          high   OK   HIERARCHYx3          high   OK   HIERARCHYx3          high  
J4  J-true-fk           HIERARCHY OK         OK   HIERARCHYx3          high   OK   HIERARCHYx3          high   OK   HIERARCHYx3          high   OK   HIERARCHYx3          high  
J5  J-true-fk           HIERARCHY OK         OK   HIERARCHYx3          high   OK   HIERARCHYx3          high   OK   HIERARCHYx3          high   OK   HIERARCHYx3          high  
M1  M-measure-derived   REJECT    OK         OK   REJECTx3             high   OK   REJECTx3             high   OK   REJECTx3             high   OK   REJECTx3             high  
K1  K-disjoint-conform  MERGE     REJECT     OK   MERGEx3              medium MISS REJECTx3             high   MISS REJECTx3             high   MISS REJECTx3             high  
K2  K-disjoint-conform  MERGE     REJECT     MISS REJECTx3             high   MISS ROLEx3               high   MISS ROLEx2,REJECTx1      high   MISS ROLEx3               high  
L1  L-false-friend      REJECT    OK         MISS HIERARCHYx3          medium MISS HIERARCHYx3          medium MISS HIERARCHYx3          low    OK   REJECTx3             high  
L2  L-false-friend      REJECT    OK         MISS REJECTx2,ROLEx1      high   OK   REJECTx3             medium MISS ROLEx3               medium MISS MERGEx3              high  
L3  L-false-friend      REJECT    OK         OK   REJECTx3             high   OK   REJECTx3             high   OK   REJECTx3             high   OK   REJECTx3             high  
```

## 2. Class x arm scorecard (strict, range over reps; lax in parens where different)

```
class                   n         C1   N                       V                       VR                      VH                      
A-true-alias            6        6/6   5-5 r1=5                6-6 r1=6                6-6 r1=6                6-6 r1=6                
B-dirty-alias           2        2/2   2-2 r1=2                2-2 r1=2                2-2 r1=2                2-2 r1=2                
C-role                  5        4/5   4-4 r1=4                5-5 r1=5                5-5 r1=5                5-5 r1=5                
D-quasi-identifier      4        0/4   4-4 r1=4                2-3 r1=2                3-3 r1=3                4-4 r1=4                
E-free-text             2        0/2   2-2 r1=2                2-2 r1=2                2-2 r1=2                2-2 r1=2                
F-dirty-hierarchy       5        5/5   1-1 r1=1                3-3 r1=3                3-4 r1=4                5-5 r1=5                
G-grain                 3        2/3   2-2 r1=2                2-2 r1=2                2-2 r1=2                3-3 r1=3                
H-weak-true             2        2/2   0-0 r1=0                0-0 r1=0                1-1 r1=1                2-2 r1=2                
I-vacuous-skew          3        3/3   3-3 r1=3                3-3 r1=3                3-3 r1=3                3-3 r1=3                
J-true-fk               5        5/5   5-5 r1=5                5-5 r1=5                5-5 r1=5                5-5 r1=5                
K-disjoint-conform      2        0/2   1-1 r1=1                0-0 r1=0                0-0 r1=0                0-0 r1=0                
L-false-friend          3        3/3   1-2 r1=1                2-2 r1=2                1-1 r1=1                2-2 r1=2                
M-measure-derived       1        1/1   1-1 r1=1                1-1 r1=1                1-1 r1=1                1-1 r1=1                
P-proxy-bijection       2        0/2   1-1 r1=1                0-1 r1=0                0-1 r1=1                0-1 r1=1                

VETO (D,E,P,G3)         9        0/9   8-8 r1=8                5-6 r1=5                6-7 r1=7                7-8 r1=8                
STATS-OWNED (F,H,J)    12      12/12   6-6 r1=6                8-8 r1=8                9-10 r1=10              12-12 r1=12             
```

## 3. Overall per arm (strict, all 45 cells)

```
arm    rep1  rep2  rep3     range   mean   lax mean
C1       33     -     -         -     33        33   (mechanical, deterministic)
N        32    33    33    32-33    32.7      32.7
V        33    34    34    33-34    33.7      33.7
VR       36    34    34    34-36    34.7      34.7
VH       41    40    40    40-41    40.3      40.3
```

## 4. Instability (3 reps disagree) — reported, never majority-patched

7 of 180 (cell, arm) pairs are unstable (4%).

```
  P1  [P-proxy-bijection  ] V   -> MERGEx2,HIERARCHYx1
  P1  [P-proxy-bijection  ] VR  -> MERGEx2,HIERARCHYx1
  P1  [P-proxy-bijection  ] VH  -> REJECTx2,HIERARCHYx1
  D1  [D-quasi-identifier ] V   -> ROLEx2,REJECTx1
  F3  [F-dirty-hierarchy  ] VR  -> ROLEx2,HIERARCHYx1
  K2  [K-disjoint-conform ] VR  -> ROLEx2,REJECTx1
  L2  [L-false-friend     ] N   -> REJECTx2,ROLEx1

  per arm: N=1, V=2, VR=3, VH=1
```

## 5. Q1 — reproduction: N vs VR on class D (quasi-identifier)

```
  cell truth   N (3 reps)                 VR (3 reps)               
  D1   REJECT  REJECTx3                   REJECTx3                  
  D2   REJECT  REJECTx3                   REJECTx3                  
  D3   REJECT  REJECTx3                   REJECTx3                  
  D4   REJECT  REJECTx3                   HIERARCHYx3               

  N   strict per rep [4, 4, 4] -> range 4-4/4, mean 4.00
  V   strict per rep [2, 2, 3] -> range 2-3/4, mean 2.33
  VR  strict per rep [3, 3, 3] -> range 3-3/4, mean 3.00
  VH  strict per rep [4, 4, 4] -> range 4-4/4, mean 4.00
```

DAT-757 cached numbers for the same cells (read-only cross-reference; C2 == N surface, C3 == VR surface, different output schema, 2 reps):

```
  cell C2:r1      C2:r2      C3:r1      C3:r2     
  D1   REJECT     REJECT     ROLE       ROLE      
  D2   REJECT     REJECT     REJECT     REJECT    
  D3   REJECT     REJECT     REJECT     REJECT    
  D4   REJECT     REJECT     HIERARCHY  HIERARCHY 
  DAT-757 C2 (=N surface) rep1: 4/4 strict
  DAT-757 C2 (=N surface) rep2: 4/4 strict
  DAT-757 C3 (=VR surface) rep1: 2/4 strict
  DAT-757 C3 (=VR surface) rep2: 2/4 strict
```

## 6. Q2 — separation: N vs V (values, no stats) vs VR (values + raw stats)

```
class                   n   N mean  V mean VR mean      V-N   VR-V   VR-N
A-true-alias            6     5.00    6.00    6.00    +1.00  +0.00  +1.00
B-dirty-alias           2     2.00    2.00    2.00    +0.00  +0.00  +0.00
C-role                  5     4.00    5.00    5.00    +1.00  +0.00  +1.00
D-quasi-identifier      4     4.00    2.33    3.00    -1.67  +0.67  -1.00
E-free-text             2     2.00    2.00    2.00    +0.00  +0.00  +0.00
F-dirty-hierarchy       5     1.00    3.00    3.33    +2.00  +0.33  +2.33
G-grain                 3     2.00    2.00    2.00    +0.00  +0.00  +0.00
H-weak-true             2     0.00    0.00    1.00    +0.00  +1.00  +1.00
I-vacuous-skew          3     3.00    3.00    3.00    +0.00  +0.00  +0.00
J-true-fk               5     5.00    5.00    5.00    +0.00  +0.00  +0.00
K-disjoint-conform      2     1.00    0.00    0.00    -1.00  +0.00  -1.00
L-false-friend          3     1.67    2.00    1.00    +0.33  -1.00  -0.67
M-measure-derived       1     1.00    1.00    1.00    +0.00  +0.00  +0.00
P-proxy-bijection       2     1.00    0.33    0.33    -0.67  +0.00  -0.67
__ALL__                45    32.67   33.67   34.67    +1.00  +1.00  +2.00
```

## 7. Q3 — presentation: VR vs VH (identical numbers, different framing)

```
class                   n   VR mean  VH mean     VH-VR
A-true-alias            6      6.00     6.00     +0.00
B-dirty-alias           2      2.00     2.00     +0.00
C-role                  5      5.00     5.00     +0.00
D-quasi-identifier      4      3.00     4.00     +1.00
E-free-text             2      2.00     2.00     +0.00
F-dirty-hierarchy       5      3.33     5.00     +1.67
G-grain                 3      2.00     3.00     +1.00
H-weak-true             2      1.00     2.00     +1.00
I-vacuous-skew          3      3.00     3.00     +0.00
J-true-fk               5      5.00     5.00     +0.00
K-disjoint-conform      2      0.00     0.00     +0.00
L-false-friend          3      1.00     2.00     +1.00
M-measure-derived       1      1.00     1.00     +0.00
P-proxy-bijection       2      0.33     0.33     +0.00
__ALL__                45     34.67    40.33     +5.67
```

## 8. Q4 — the router's job: stats-owned classes F, H, J

```
arm    rep1  rep2  rep3    range   mean  mean frac  G-D2 (>=0.8)
C1       12     -     -        -     12       1.00  PASS (reference, not an arm)
N         6     6     6    6-6     6.00       0.50  FAIL  (per-rep frac 0.50-0.50)
V         8     8     8    8-8     8.00       0.67  FAIL  (per-rep frac 0.67-0.67)
VR       10     9     9    9-10    9.33       0.78  FAIL  (per-rep frac 0.75-0.83)
VH       12    12    12   12-12   12.00       1.00  PASS  (per-rep frac 1.00-1.00)

  F-dirty-hierarchy      n=5  N=1.00  V=3.00  VR=3.33  VH=5.00
  H-weak-true            n=2  N=0.00  V=0.00  VR=1.00  VH=2.00
  J-true-fk              n=5  N=5.00  V=5.00  VR=5.00  VH=5.00
```

## 9. Pre-registered dev gates

**Best arm by overall strict mean: `VH` (40.3/45).** Gates are evaluated for every arm below so the pick is auditable; the protocol's gate applies to the best arm.

```
arm   G-D1 veto (D,E,P,G3), n=9        G-D2 F,H,J >=0.8           G-D3 false MERGE on L   
N     8.00 vs N 8.00 (8-8) PASS        6.00/12 = 0.50 FAIL        0 false MERGE PASS      
V     5.67 vs N 8.00 (5-6) FAIL        8.00/12 = 0.67 FAIL        0 false MERGE PASS      
VR    6.33 vs N 8.00 (6-7) FAIL        9.33/12 = 0.78 FAIL        0 false MERGE PASS      
VH    7.33 vs N 8.00 (7-8) FAIL        12.00/12 = 1.00 PASS       3 false MERGE FAIL      
```

- **N**: G-D1 PASS | G-D2 FAIL | G-D3 PASS
- **V**: G-D1 FAIL | G-D2 FAIL | G-D3 PASS
- **VR**: G-D1 FAIL | G-D2 FAIL | G-D3 PASS
- **VH**: G-D1 FAIL | G-D2 PASS | G-D3 FAIL

**Arms clearing all three gates: NONE**
G-D1 note: N (names-only) is the baseline, veto mean 8.00/9; '>= N' is evaluated on the 3-rep mean, with the per-rep range shown.

## 10. Misgrades (rep 1, strict) — the qualitative evidence

### arm VH
```
  P2  [P-proxy-bijection  ] got REJECT           want HIERARCHY conf=high  
      CREATIONTIMESTAMP is a proxy/audit key that happens to be bijective with SALESDOCUMENT but is not a groupable dimensional attribute of it.
  K1  [K-disjoint-conform ] got REJECT           want MERGE     conf=high  
      The two columns come from disjoint country-specific datasets with non-overlapping region codes (Jaccard ~0.05), so they represent different, incompati
  K2  [K-disjoint-conform ] got ROLE             want MERGE     conf=high  
      Driver nationality and circuit country are distinct entity attributes (person vs. race location) that happen to share a country-like domain but repres
  L2  [L-false-friend     ] got MERGE            want REJECT    conf=high  
      customer__FN and customer__Active are near-identical binary flags that co-occur on 99.4% of rows, indicating they encode the same underlying customer 
  -- 4 misgrades / 45 cells
```
### arm N
```
  A6  [A-true-alias       ] got HIERARCHY/a->b   want MERGE     conf=high  
      race__circuitId is the circuit's identifier that determines the circuit's name, a coarser attribute lookup.
  P2  [P-proxy-bijection  ] got REJECT           want HIERARCHY conf=high  
      CREATIONTIMESTAMP is a proxy timestamp attribute, not a dimensional attribute or grouping level of the sales document identifier.
  C5  [C-role             ] got REJECT           want ROLE      conf=high  
      Grid (starting position) and position (finishing result) are correlated race outcomes, not a dimensional hierarchy or same entity.
  F1  [F-dirty-hierarchy  ] got REJECT           want HIERARCHY conf=high  
      product_code identifies a specific product (style) while product_type_name is a separate categorical attribute (e.g., garment type) not functionally d
  F2  [F-dirty-hierarchy  ] got REJECT           want HIERARCHY conf=high  
      Product code and department name are independent classification attributes of an article, not a hierarchical or identity relationship since one articl
  F3  [F-dirty-hierarchy  ] got REJECT           want HIERARCHY conf=high  
      Both are separate article classification attributes at similar granularity with no determinacy between them, representing different classification hie
  F4  [F-dirty-hierarchy  ] got ROLE             want HIERARCHY conf=medium
      Plant is the manufacturing/stocking location for the item while shipping point is the logistics dispatch point, related but distinct entities that sho
  G2  [G-grain            ] got REJECT           want HIERARCHY conf=high  
      PLANT is an item-level attribute of the sales document, not a determined nor coincidental value; SALESDOCUMENT doesn't functionally determine PLANT (v
  H1  [H-weak-true        ] got REJECT           want HIERARCHY conf=high  
      SOLDTOPARTY (customer) and doc__SALESOFFICE (internal sales org unit) are independent attributes of the document with no functional dependency between
  H2  [H-weak-true        ] got ROLE             want HIERARCHY conf=medium
      Plant (logistics/shipping location) and sales organization (commercial org unit) are related but independently assigned facets of a sales document, no
  K2  [K-disjoint-conform ] got REJECT           want MERGE     conf=high  
      Driver nationality and circuit country are distinct, unrelated entities (person origin vs. race location) with no functional or hierarchical dependenc
  L1  [L-false-friend     ] got HIERARCHY/b->a   want REJECT    conf=medium
      A sales group typically rolls up into a single sales office, making sales office the coarser grouping level.
  L2  [L-false-friend     ] got ROLE             want REJECT    conf=high  
      Both are separate customer flag attributes (fashion-news opt-in vs active status) that represent distinct concepts, not a hierarchy or duplicate.
  -- 13 misgrades / 45 cells
```

## 11. Failure attribution — VH score by the frame the cell actually rendered

Not pre-registered; computed after the fact from `channels.hypothesis_block` to locate *where* VH fails. Reported as a mechanism, not as a gate.

```
rendered frame            n        N     VR     VH   VH frac
frame_determination      24    17.00  18.33  24.00   1.00
frame_bidirectional      15    11.67  12.33  12.33   0.82
    VH misses: ['P1', 'P2', 'L2']
frame_no_finding          4     3.00   4.00   4.00   1.00
no joint stats (K)        2     1.00   0.00   0.00   0.00
    VH misses: ['K1', 'K2']
```

`frame_determination` offers four origins (real hierarchy / near-key artifact / vacuous skew / proxy determinant) — a menu that spans the truth space — and VH is perfect on every cell that renders it. `frame_bidirectional` offers three (two encodings of one identity / two concepts in lockstep / a copied value), all of which read the pair as one-thing-or-nothing: it contains **no 'real attribute edge' option** (class P's truth) and **no 'the statistic is vacuous on a degenerate domain' option** (L2's truth). Every VH miss with joint statistics (P1, P2, L2) renders that one frame, and both VH gate failures (G-D1 via P1, G-D3 via L2) trace to it.

## 12. Confidence — is abstention measurable?

```
confidence      n  correct  wrong  accuracy
high          482      399     83      0.83
medium         55       25     30      0.45
low             3        0      3      0.00

  VH misgrades stated at confidence=high: 14/14
```

Across all arms the field is directionally calibrated (high 0.83 > medium 0.45 > low 0.00), so it carries real signal in aggregate. **But on the best arm it is useless as an abstain trigger: VH is high-confidence on every single one of its errors.** An abstain posture built on this field would abstain on none of VH's misgrades. The protocol asked whether abstention is measurable rather than bolted on later — measured, and for VH the answer is no.
