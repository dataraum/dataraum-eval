# DAT-762 judge spike — held-out RelBench survey

**Purpose.** Acquire a *genuinely untouched* RelBench verdict set for the LLM-judge
spike. The DAT-757 round designed against `rel-f1`, `rel-hm`, `rel-salt` — those are
design-contaminated and are excluded by construction (C1). This document
characterizes the five never-downloaded candidates and scores them against
criteria fixed **before** the data was inspected.

Instrument: the frozen `scripts/probes/dat757-relbench/fetch_export.py`, unmodified,
same overlay (`uv run --with relbench --with pandas --with pyarrow`), same
`--max-rows` default of 2,000,000, same `SEED = 757`. Nothing in `dat757-relbench/`
was edited; `build_obt` was imported read-only to validate the proposed SPECS.

---

## 1. Acquisition

| DB | `db.zip` | cache (unzipped) | export (parquet) | wall | status |
|---|---|---|---|---|---|
| rel-event | 112 MB | 396 MB | 131 MB | 22 s | exported |
| rel-trial | 560 MB | 1.2 GB | 642 MB | 6 m 40 s | exported |
| rel-avito | 352 MB | 796 MB | 187 MB | 1 m 24 s | exported |
| rel-stack | 848 MB | 1.8 GB | 1.0 GB | 3 m 27 s | exported |
| rel-amazon | ≥4.4 GB (incomplete) | — | — | stopped at 16 m | **not acquired** — see §6 |

Exports live in `corpora/relbench/<db>/` (gitignored, re-derivable).

> Note: `corpora/relbench/` also contains `rel-f1`, `rel-hm`, `rel-salt` exports written
> at 01:59 by something outside this session. They are excluded by C1 and were not
> touched.

### Truncation damage (`--max-rows 2,000,000`)

The default cap silently breaks referential integrity when it clips a **table that is
an FK target**. Measured FK match rate (share of distinct FK values present in the
dim's pkey) on the exports:

| DB | truncated tables | worst measured FK match |
|---|---|---|
| **rel-stack** | none | **100 %** on every FK |
| **rel-trial** | none | **100 %** on every FK |
| rel-avito | SearchInfo (2.0/2.6 M), VisitStream (2.0/6.5 M), SearchStream (2.0/9.3 M), AdsInfo (2.0/6.0 M) | **33.5 %** (`SearchStream.AdID → AdsInfo`) |
| rel-event | event_attendees (2.0/11.2 M), user_friends (2.0/30.4 M), events (2.0/3.1 M) | **63.6 %** (`event_interest.event → events`) |

This matters: a clipped dim manufactures LEFT-JOIN nulls that **do not exist in the
source**, so the folded exposure is no longer the one the FK truth describes. For
rel-avito, two thirds of the `AdsInfo` fold would be null — the truth model breaks.
rel-stack and rel-trial are unaffected at the standard cap: nothing exceeds 2 M.

---

## 2. Schema characterization

### rel-stack (Stack Exchange)

| table | n_rows | pkey | fkeys | time_col | shape |
|---|---|---|---|---|---|
| votes | 1,673,836 | Id | PostId→posts, UserId→users | CreationDate | FACT |
| postHistory | 1,486,886 | Id | PostId→posts, UserId→users | CreationDate | FACT |
| comments | 794,597 | Id | UserId→users, PostId→posts | CreationDate | FACT |
| badges | 590,833 | Id | UserId→users | Date | fact (1 FK) |
| posts | 415,913 | Id | OwnerUserId→users, ParentId→posts | CreationDate | FACT + DIM |
| users | 333,784 | Id | — | CreationDate | DIM |
| postLinks | 103,969 | Id | PostId→posts, RelatedPostId→posts | CreationDate | FACT |

Columns / dtypes:

- `votes`: Id `Int64` \<pkey\>, UserId `Int64` \<fk\>, PostId `Int64` \<fk\>, VoteTypeId `Int64`, CreationDate `Datetime(ns)` \<time\>
- `postHistory`: Id \<pkey\>, PostId \<fk\>, UserId \<fk\>, PostHistoryTypeId `Int64`, UserDisplayName `String`, ContentLicense `String`, RevisionGUID `String`, Text `String`, Comment `String`, CreationDate \<time\>
- `comments`: Id \<pkey\>, PostId \<fk\>, UserId \<fk\>, ContentLicense `String`, UserDisplayName `String`, Text `String`, CreationDate \<time\>
- `badges`: Id \<pkey\>, UserId \<fk\>, Class `Int64`, Name `String`, TagBased `Boolean`, Date \<time\>
- `posts`: Id \<pkey\>, OwnerUserId \<fk\>, PostTypeId `Int64`, ParentId \<fk→posts\>, OwnerDisplayName `String`, Title `String`, Tags `String`, ContentLicense `String`, Body `String`, CreationDate \<time\>
- `users`: Id \<pkey\>, AccountId `Float64`, DisplayName `String`, Location `String`, ProfileImageUrl `Float64`, WebsiteUrl `String`, AboutMe `String`, CreationDate \<time\>
- `postLinks`: Id \<pkey\>, RelatedPostId \<fk→posts\>, PostId \<fk→posts\>, LinkTypeId `Int64`, CreationDate \<time\>

**Shared FK targets (cross-fact conform surface):**
- `posts` ← comments, postHistory, postLinks, posts, votes — **5 referrers**
- `users` ← badges, comments, postHistory, posts, votes — **5 referrers**

**Role-playing:** `postLinks → posts` via **`PostId` and `RelatedPostId`** — two
roles into the same dim from one fact.

**Two-hop:** yes — `{comments,votes,postHistory,postLinks}.PostId → posts.OwnerUserId → users`,
plus the self-referential `posts.ParentId → posts`.

**Text-bearing dim attributes:** strong — `users.{DisplayName, Location, WebsiteUrl, AboutMe}`,
`posts.{Title, Tags, Body, OwnerDisplayName, ContentLicense}`.

---

### rel-trial (ClinicalTrials.gov)

| table | n_rows | pkey | fkeys | time_col | shape |
|---|---|---|---|---|---|
| facilities_studies | 1,867,226 | id | nct_id→studies, facility_id→facilities | date | FACT |
| outcomes | 476,790 | id | nct_id→studies | date | DIM (+1 FK) |
| facilities | 453,233 | facility_id | — | — | DIM |
| drop_withdrawals | 440,547 | id | nct_id→studies | date | fact (1 FK) |
| conditions_studies | 440,543 | id | nct_id→studies, condition_id→conditions | date | FACT |
| reported_event_totals | 435,129 | id | nct_id→studies | date | fact (1 FK) |
| sponsors_studies | 425,014 | id | nct_id→studies, sponsor_id→sponsors | date | FACT |
| eligibilities | 273,160 | id | nct_id→studies | date | fact (1 FK) |
| studies | 273,160 | nct_id | — | start_date | DIM |
| designs | 272,521 | id | nct_id→studies | date | fact (1 FK) |
| outcome_analyses | 254,420 | id | nct_id→studies, outcome_id→outcomes | date | FACT |
| interventions_studies | 179,738 | id | nct_id→studies, intervention_id→interventions | date | FACT |
| sponsors | 53,241 | sponsor_id | — | — | DIM |
| conditions | 3,973 | condition_id | — | — | DIM |
| interventions | 3,462 | intervention_id | — | — | DIM |

Key column lists / dtypes:

- `studies` (DIM, 29 cols): nct_id `Int64` \<pkey\>, start_date `Datetime(ns)` \<time\>, target_duration `String`, study_type `String`, acronym `String`, baseline_population `String`, brief_title `String`, official_title `String`, phase `String`, enrollment `Float64`, enrollment_type `String`, source `String`, limitations_and_caveats `Float64`, number_of_arms `Float64`, number_of_groups `Float64`, has_dmc `String`, is_fda_regulated_drug `String`, is_fda_regulated_device `String`, is_unapproved_device `String`, is_ppsd `String`, is_us_export `String`, biospec_retention `String`, biospec_description `String`, source_class `String`, baseline_type_units_analyzed `String`, fdaaa801_violation `String`, plan_to_share_ipd `String`, detailed_descriptions `String`, brief_summaries `String`
- `outcomes` (DIM): id \<pkey\>, nct_id \<fk→studies\>, outcome_type `String`, title `String`, description `String`, time_frame `String`, population `String`, units `String`, units_analyzed `String`, dispersion_type `String`, param_type `String`, date \<time\>
- `facilities` (DIM): facility_id \<pkey\>, name `String`, city `String`, state `String`, zip `String`, country `String`
- `sponsors` (DIM): sponsor_id \<pkey\>, name `String`, agency_class `String`
- `conditions` (DIM): condition_id \<pkey\>, mesh_term `String`
- `interventions` (DIM): intervention_id \<pkey\>, mesh_term `String`
- `outcome_analyses` (FACT, 25 cols): id \<pkey\>, nct_id \<fk\>, outcome_id \<fk\>, non_inferiority_type `String`, non_inferiority_description `String`, param_type `String`, param_value `Float64`, dispersion_type `String`, dispersion_value `Float64`, p_value_modifier `String`, p_value `Float64`, ci_n_sides `String`, ci_percent `Float64`, ci_lower_limit `Float64`, ci_upper_limit `Float64`, ci_upper_limit_na_comment `String`, p_value_description `String`, method `String`, method_description `String`, estimate_description `String`, groups_description `String`, other_analysis_description `String`, ci_upper_limit_raw `Float64`, ci_lower_limit_raw `Float64`, p_value_raw `Float64`, date \<time\>
- `facilities_studies`: id \<pkey\>, nct_id \<fk\>, facility_id \<fk\>, date \<time\>
- `conditions_studies`: id \<pkey\>, nct_id \<fk\>, condition_id \<fk\>, date \<time\>
- `sponsors_studies`: id \<pkey\>, nct_id \<fk\>, sponsor_id \<fk\>, lead_or_collaborator `String`, date \<time\>
- `interventions_studies`: id \<pkey\>, nct_id \<fk\>, intervention_id \<fk\>, date \<time\>

**Shared FK targets:** `studies` ← conditions_studies, designs, drop_withdrawals,
eligibilities, facilities_studies, interventions_studies, outcome_analyses, outcomes,
reported_event_totals, sponsors_studies — **10 referrers**, the widest conformed
dimension in the corpus.

**Role-playing:** NONE.

**Two-hop:** `outcome_analyses.outcome_id → outcomes.nct_id → studies` — and this one
is special: it is a **redundant denormalized path**, because `outcome_analyses.nct_id`
points at the same `studies` row. The folded `outcome__nct_id` and the fact's own
`nct_id` are therefore an exact alias pair — a genuine, naturally-occurring
cross-path conform case.

**Text-bearing dim attributes:** strong, and *domain-meaningful* (titles, MeSH terms,
facility geography, sponsor agency class).

---

### rel-avito (Avito classifieds)

| table | n_rows (full) | pkey | fkeys | time_col | shape |
|---|---|---|---|---|---|
| SearchInfo | 2,000,000 (2,579,289) | SearchID | UserID→UserInfo, LocationID→Location, CategoryID→Category | SearchDate | FACT + DIM |
| VisitStream | 2,000,000 (6,454,562) | — | UserID→UserInfo, AdID→AdsInfo | ViewDate | FACT |
| SearchStream | 2,000,000 (9,254,702) | — | SearchID→SearchInfo, AdID→AdsInfo | SearchDate | FACT |
| AdsInfo | 2,000,000 (5,960,558) | AdID | LocationID→Location, CategoryID→Category | — | FACT + DIM |
| PhoneRequestsStream | 302,974 | — | UserID→UserInfo, AdID→AdsInfo | PhoneRequestDate | FACT |
| UserInfo | 98,250 | UserID | — | — | DIM |
| Location | 3,512 | LocationID | — | — | DIM |
| Category | 68 | CategoryID | — | — | DIM |

- `UserInfo`: UserID \<pkey\>, UserAgentID `Float64`, UserAgentOSID `Float64`, UserDeviceID `Float64`, UserAgentFamilyID `Float64`
- `Location`: LocationID \<pkey\>, Level `Float64`, RegionID `Float64`, CityID `Float64`
- `Category`: CategoryID \<pkey\>, Level `Int64`, ParentCategoryID `Int64`, SubcategoryID `Int64`
- `AdsInfo`: AdID \<pkey\>, LocationID \<fk\>, CategoryID \<fk\>, Price `Float64`, Title `String`, IsContext `Float64`
- `SearchInfo`: UserID \<fk\>, SearchID \<pkey\>, SearchDate \<time\>, IPID `Float64`, IsUserLoggedOn `Float64`, SearchQuery `String`, LocationID \<fk\>, CategoryID \<fk\>

**Shared FK targets:** `AdsInfo` ← PhoneRequestsStream, SearchStream, VisitStream;
`UserInfo` ← PhoneRequestsStream, SearchInfo, VisitStream; `Location` ← AdsInfo,
SearchInfo; `Category` ← AdsInfo, SearchInfo.

**Role-playing:** NONE. **Two-hop:** yes (via AdsInfo and SearchInfo).

**Text-bearing dim attributes:** WEAK — `UserInfo`, `Location`, `Category` are
*entirely* opaque numeric surrogate ids. Only `AdsInfo.Title` and
`SearchInfo.SearchQuery` carry meaning, and both are Russian-language free text.

---

### rel-event (Event recommendation)

| table | n_rows (full) | pkey | fkeys | time_col | shape |
|---|---|---|---|---|---|
| event_attendees | 2,000,000 (11,245,010) | — | event→events, user_id→users | start_time | FACT |
| user_friends | 2,000,000 (30,386,403) | — | user→users, friend→users | — | FACT |
| events | 2,000,000 (3,137,972) | event_id | user_id→users | start_time | DIM |
| users | 38,209 | user_id | — | joinedAt | DIM |
| event_interest | 15,398 | — | event→events, user→users | timestamp | FACT |

- `users`: user_id \<pkey\>, locale `String`, birthyear `Float64`, gender `String`, joinedAt \<time\>, location `String`, timezone `Float64`
- `events`: event_id \<pkey\>, user_id \<fk\>, start_time \<time\>, city/state/zip/country `String`, lat/lng `Float64`, **c_1 … c_100 `Int64`, c_other `Int64`**
- `event_interest`: user \<fk\>, event \<fk\>, invited `Int64`, timestamp \<time\>, interested `Int64`, not_interested `Int64`
- `event_attendees`: Unnamed: 0 `Int64`, event \<fk\>, status `String`, user_id \<fk\>, start_time \<time\>
- `user_friends`: Unnamed: 0 `Int64`, user \<fk\>, friend \<fk\>

**Shared FK targets:** `events` ← event_attendees, event_interest; `users` ←
event_attendees, event_interest, events, user_friends.

**Role-playing:** `user_friends → users` via **`user` and `friend`**.

**Two-hop:** `{event_interest, event_attendees}.event → events.user_id → users`.

**Text-bearing dim attributes:** WEAK — the `events` dim is 101 of 111 columns of
anonymized bag-of-words counts (`c_1..c_100`, `c_other`) with no lexicon. Real
meaning is confined to `events.{city,state,zip,country}` and `users.{locale,gender,location}`.

---

## 3. Pre-registered criteria — scoring

Criteria were fixed before inspection and applied mechanically.

| | rel-stack | rel-trial | rel-avito | rel-event | rel-amazon |
|---|---|---|---|---|---|
| **C1** not f1/hm/salt *(req)* | PASS | PASS | PASS | PASS | PASS |
| **C2** fact w/ ≥2 FKs → dims *(req)* | PASS (votes, postHistory, comments, postLinks, posts) | PASS (facilities_studies, conditions_studies, sponsors_studies, outcome_analyses, interventions_studies) | PASS (SearchStream, VisitStream, PhoneRequestsStream, SearchInfo, AdsInfo) | PASS (event_interest, event_attendees, user_friends) | not assessed (§6) |
| **C3** fact ≥10k rows *(req)* | PASS (104k–1.67 M) | PASS (180k–1.87 M) | PASS (303k–2 M) | PASS (15,398–2 M) | not assessed |
| **C4** ≥2 facts share an FK target | **STRONG** — `posts` ×5, `users` ×5 | **STRONG** — `studies` ×10 | PASS — `AdsInfo` ×3, `UserInfo` ×3, `Location` ×2, `Category` ×2 | PASS — `events` ×2, `users` ×4 | not assessed |
| **C5** role-playing FKs | **YES** — postLinks→posts via PostId + RelatedPostId | NO | NO | YES — user_friends→users via user + friend | not assessed |
| **C6** text-bearing dim attrs | **STRONG** — Title, Tags, Body, AboutMe, DisplayName, Location | **STRONG** — brief/official_title, phase, mesh_term, facility name/city/country, sponsor name | **WEAK** — dims are pure numeric ids; only Title/SearchQuery (ru) | **WEAK** — dim is c_1..c_100 anonymized counts | not assessed |
| **C7** diversity / cost | tech Q&A; 1.0 GB; postLinks probes whole at 104k rows | clinical research; 642 MB; ~75k-row OBT | ru classifieds; 187 MB | social events; 131 MB | e-commerce; ≥7 GB |
| *integrity at `--max-rows 2M`* | **clean** (no truncation, 100 % FK match) | **clean** (no truncation, 100 % FK match) | **BROKEN** (33.5 % FK match) | **DEGRADED** (63.6 % FK match) | — |

All four assessed DBs pass every **required** criterion (C1–C3). Separation happens
on C4–C6 and on truncation integrity.

---

## 4. Recommendations

**rel-stack and rel-trial**, in that order — the only two that are structurally rich
*and* survive the standard export cap intact. They are also maximally
complementary: rel-stack supplies the role-playing cell (C5) that rel-trial lacks;
rel-trial supplies a 10-referrer conformed dimension and domain-meaningful text.

Because the frozen `main()` couples the SPECS key to the export dir
(`base = Path("corpora/relbench") / args.dataset`), a per-DB *multi-fact* keying needs
the new DAT-762 probe to pass `base` itself — `build_obt(base, spec)` already takes
it as a parameter, so this needs no edit to the frozen instrument. Each proposed
entry therefore carries an explicit `"db"` field.

### R1 — `rel-stack` / `postLinks` (role-playing; **no sampling needed**)

The direct out-of-domain analogue of rel-salt's role-provenance cell: two roles into
one dim, each with its own two-hop into `users`. Cheapest probe in the survey — the
whole table is 103,969 rows, so no sampling decision to defend at all.

```python
"rel-stack-postlinks": {
    "db": "rel-stack",
    "fact": "postLinks",
    "folds": [
        ("PostId", "posts", "post__"),
        ("RelatedPostId", "posts", "related__"),
        ("post__OwnerUserId", "users", "postowner__"),
        ("related__OwnerUserId", "users", "relatedowner__"),
    ],
    "probe_n": None,      # 103,969 rows — use everything
    "perm_reps": 999,
    # role contexts: the fact's own columns only (LinkTypeId, CreationDate, Id),
    # never the sibling role copies — they are outcomes, not drivers.
    "role_context_groups": ("fact", "fact-key"),
},
```

Validated with the frozen `build_obt`: OBT **103,969 × 37**, **0 unmatched keys** on
all four folds. Key ratios vs the `NEAR_KEY_FRAC = 0.9` guard: `PostId` 48.9 %,
`RelatedPostId` 30.9 %, `post__OwnerUserId` 28.2 %, `related__OwnerUserId` 17.4 % —
all clear.

**Entity-complete sampling: NOT needed.** The full fact is used.
Natural dirt included: `PostId` 19.7 % null, `RelatedPostId` 2.2 % null.

### R2 — `rel-trial` / `outcome_analyses` (rich text dims; **entity-complete needed**)

Carries the naturally-redundant two-hop (`outcome__nct_id` ≡ `nct_id`) and the
richest meaning-bearing dim in the corpus (`studies`, 29 columns of titles, phase,
regulatory flags).

```python
"rel-trial-outcome-analyses": {
    "db": "rel-trial",
    "fact": "outcome_analyses",
    "folds": [
        ("nct_id", "studies", "study__"),
        ("outcome_id", "outcomes", "outcome__"),
    ],
    # entity-complete: a row-random sample drives outcome_id to 64.9% distinct
    # (vs 42.1% here) — sampling whole studies is the realistic slice and FD
    # exactness is subset-invariant.
    "sample_by": ("nct_id", 6_000),
    "probe_n": None,
    "perm_reps": 999,
},
```

Validated: OBT **74,765 × 65**, **0 unmatched keys**. `nct_id` 8.0 %, `outcome_id`
42.1 %.

**Entity-complete sampling: NEEDED** — measured, not assumed. Row-random at
`probe_n = 60_000` yields `outcome_id` at **64.9 %** distinct vs **42.1 %** under
entity-complete. It does not cross the 0.9 guard, so this is a *distortion* concern
rather than a fold-killer (weaker than rel-hm's ~92 % case), but the entity-complete
slice is the realistic one and costs nothing.

### R3 — `rel-stack` / `comments` (the cross-fact conform partner; **entity-complete needed**)

R1 alone cannot exercise C4: the harness builds one OBT per fact, so cross-fact
conform judgment needs a **second** fact folding the **same** dims. `comments` shares
both `posts` and `users` with `postLinks` — same dims, different fact grain, and it
adds its own text (`Text`, `UserDisplayName`).

```python
"rel-stack-comments": {
    "db": "rel-stack",
    "fact": "comments",
    "folds": [
        ("PostId", "posts", "post__"),
        ("UserId", "users", "user__"),
        ("post__OwnerUserId", "users", "postowner__"),
    ],
    # entity-complete: row-random at 120k drives PostId to 74.1% distinct, close to
    # the 0.9 near-key guard; sampling whole posts holds it at 29.8%.
    "sample_by": ("PostId", 40_000),
    "probe_n": None,
    "perm_reps": 999,
},
```

Validated: OBT **134,258 × 30**, **0 unmatched keys**. `PostId` 29.8 %, `UserId`
16.1 %, `post__OwnerUserId` 14.9 %.

**Entity-complete sampling: NEEDED** — measured. Row-random at `probe_n = 120_000`
gives `PostId` **74.1 %** distinct vs **29.8 %** entity-complete. This is the rel-hm
failure mode in the making: shrink `probe_n` any further and it crosses 0.9 and the
whole `posts` fold dies.

> R1 + R3 together give the conform pair (`posts`, `users` folded from two different
> facts) on one 1.0 GB export. R2 adds a second, unrelated domain and the widest
> conformed dimension. If only two are run: **R1 + R3**.

---

## 5. Failures against required criteria

**None.** All four assessed DBs pass C1, C2 and C3.

Two are nonetheless **not recommended**, on preferred criteria and on integrity:

- **rel-avito** — fails C6 in substance (`UserInfo`, `Location`, `Category` dims are
  100 % opaque numeric surrogate ids; the judge would have no meaning to reason
  over), and its integrity is **broken at the standard cap**: `SearchStream.AdID →
  AdsInfo` matches only **33.5 %**. Usable only by re-exporting at `--max-rows ≥
  6_000_000`, which departs from the frozen protocol and costs ~3× the rows.
- **rel-event** — fails C6 in substance (the `events` dim is 101 of 111 columns of
  unlabeled `c_1..c_100` word counts) and is **degraded** at the cap
  (`event_interest.event → events` matches **63.6 %**). It does carry role-playing
  (`user_friends` → `users` via `user`/`friend`), but `user_friends` is a bare
  3-column edge list with no attributes to fold, so the role cell would be vacuous.

---

## 6. rel-amazon — blocked

`rel-amazon` did not complete inside the time box and was **stopped at 16 minutes**,
still streaming, having reached **4.43 GB** (~275 MB/min sustained, no terminal size
reached) — by a wide margin the largest artifact in the corpus. The orphaned partial
was deleted; the cache and disk were left clean. Per the standing instruction to
timebox at ~15 minutes rather than block, it is **not assessed** here.

It is also not needed: rel-stack and rel-trial already satisfy every required
criterion and both strongly-preferred ones, with clean integrity at the standard
cap. rel-amazon's known shape (`review` fact → `customer` / `product` dims) offers
no role-playing and only two dims — strictly weaker than rel-stack on C4/C5 at
roughly ten times the acquisition and probe cost. **Recommend leaving it CUT** for
this spike unless a third domain is later wanted.

---

## 7. Reproduction

```bash
# stage 1 — export (ephemeral overlay; the eval env is polars-only)
uv run --with relbench --with pandas --with pyarrow \
    python scripts/probes/dat757-relbench/fetch_export.py rel-stack
uv run --with relbench --with pandas --with pyarrow \
    python scripts/probes/dat757-relbench/fetch_export.py rel-trial
```

Both at the default `--max-rows 2_000_000` and `SEED = 757`; neither is truncated at
that cap, so the exports are the full source databases.
