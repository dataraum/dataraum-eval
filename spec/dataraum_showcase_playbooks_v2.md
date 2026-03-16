# DataRaum Showcase Playbooks v2

## Calibration Framework: 3 Real-World Test Cases

### Core thesis

Modern data is well-formatted. APIs return typed JSON with ISO timestamps. Schema validation passes. The problems that cost companies millions aren't formatting bugs — they're **ontological ambiguities**: data that is technically correct but semantically wrong when interpreted without business context.

DataRaum's value isn't "we fix your messy CSVs." It's: **"we force every interpretive judgment call to be explicit, made once, and enforced consistently across every query, every refresh, every report."**

The cached computation graph is where business policy lives. Not in a wiki. Not in an analyst's head. In the infrastructure.

---

## Interface Architecture (All Cases)

```
CLI (pipeline backbone)          Claude Desktop (agent layer)
─────────────────────           ────────────────────────────
dataraum-context ingest    →    MCP server (4 tools)
dataraum-context profile   →    get_context / query / get_metrics / annotate
dataraum-context serve     →    Natural language → cached graph resolution
```

**Why CLI + MCP, not Cowork or a custom UI:**

- CLI is scriptable, diffable, auditable — it IS the reproducibility story
- MCP via Claude Desktop shows the agent interaction naturally
- Cowork is the "works once, forgets everything" baseline we position against
- Custom frontend is premature — prove the value loop first

**Baseline comparison (all cases):** Run every query in plain Claude Desktop without dataraum MCP. Document where the AI makes different interpretive choices on re-run. This is the "why dataraum" evidence.

---

## Test Case 1: Monthly Financial Close

### The Story

A mid-size company with three European entities closes their books monthly. The data arrives cleanly from SAP and banking APIs. Every field is typed. Every date is ISO. And yet the CFO gets a different consolidated revenue number depending on which analyst runs the report, because nobody has pinned down the dozen judgment calls embedded in "consolidated revenue."

### Data Sources

| Source | Origin | Format | Notes |
|--------|--------|--------|-------|
| General Ledger | SAP export via API | Structured CSV, typed fields | Clean format. Ambiguous semantics. |
| ECB exchange rates | `data.ecb.europa.eu` — EUR/USD and EUR/CHF daily | CSV | Real public data. No weekend rates (by design, not a bug). |
| Intercompany ledger | SAP intercompany module | Structured CSV | Matching logic is the challenge, not the format. |

### Synthetic Data Generation Brief

#### GL Export (gl_month{N}.csv) — ~2,000 rows/month

Columns: `posting_date` (ISO), `account_number`, `account_name`, `cost_center`, `amount` (decimal), `currency` (ISO 4217), `document_type`, `entity`, `line_description`, `reference`

All fields properly typed. No format issues. Instead, inject these ontological traps:

**Revenue recognition ambiguity:**
- Entity DE-01 books a €240K annual maintenance contract as a single revenue entry in January. Entity CH-01 books an identical contract type as 12 monthly entries of CHF 22K. Both are correct per their local accounting practice. But consolidated "monthly revenue" is overstated in January and understated Feb-Dec unless you know to spread DE-01's entry.
- Include 3-4 entries with `document_type: "credit_memo"` that are revenue reversals from prior periods. They have valid posting dates in the current month. Do they reduce current month revenue or are they prior-period adjustments? The data doesn't tell you — it's an accounting policy decision.

**Cost center ambiguity:**
- Cost center "CC-400" is labeled "Shared Services" and appears in all three entities. In DE-01 it's IT infrastructure. In AT-01 it's facilities management. Same code, different meaning, different P&L line. The GL data is perfectly valid — the cost center mapping is entity-dependent.
- One cost center ("CC-710") was created mid-year for a new product line. In month 1 it has 0 entries. In month 2, expenses that were previously under "CC-500" (R&D General) now appear under "CC-710." This isn't a data error — it's a reorganization. But your month-over-month R&D trend just showed a 30% drop unless you know to combine them.

**Intercompany complexity:**
- Entity DE-01 sells software licenses to CH-01 and marks them as revenue (account 4000-series). CH-01 books them as cost (account 6000-series). Both are correct. But the amounts don't exactly match: DE-01 booked €50,000 and CH-01 booked CHF 48,500 — because they used different exchange rates on different dates. The difference is a legitimate FX effect, not an error. But it needs to be identified as such, not flagged as a reconciliation break.
- 5% of intercompany entries are genuinely one-sided (booked by one entity, not yet received by the other). These ARE errors but they look identical in format to the properly matched ones.

**Entity resolution:**
- Customer "Deutsche Telekom AG" in DE-01's GL is the same as "T-Mobile Business" in AT-01's GL and "DT Group" in CH-01's GL. All three are valid legal names for different entities within the same corporate group. For customer concentration reporting, these must be unified — but the GL data has no shared key.

#### ECB Exchange Rates — real data, real gaps

Download actual ECB daily rates. These have no weekend or holiday rates by design. The ontological question: when converting a transaction posted on Saturday (batch processing), which rate applies? Friday's close? Monday's rate? This is a policy decision that changes numbers.

#### Intercompany Ledger (intercompany_month{N}.csv) — ~200 rows/month

Columns: `source_entity`, `target_entity`, `amount`, `currency`, `transaction_type`, `reference`, `posting_date` (ISO), `matching_status`

All properly typed. The traps:

- Matching is based on `reference` field, but DE-01 uses format "IC-2024-0001" while CH-01 uses "INTER/2024/001" for the same transaction. Neither is wrong.
- Some transactions have a `matching_status` of "partial" — meaning the amounts are close but not identical, typically due to FX timing. The tolerance threshold for "close enough" is a policy decision: is CHF 48,500 vs €50,000 a match (given the exchange rate) or a break?
- A transaction type "management_fee" appears in the intercompany ledger. Should this be eliminated on consolidation? In some group structures yes (it's an internal allocation), in others no (it's a genuine transfer price). The data can't tell you.

#### Month 2 variations

Generate month 2 with ~80% of the same patterns, plus:
- The annual maintenance contract from DE-01 has no entry (it was all booked in month 1). Is month 2 revenue zero for that contract or €20K (amortized)?
- A new entity (PL-01, Poland) appears with 50 GL entries. All properly formatted. But no intercompany mappings exist yet, and the cost center codes partially overlap with DE-01's codes (meaning different things).
- One credit memo references an invoice from 8 months ago. Prior-period adjustment or current-month reduction?

### Pipeline Execution

#### Act 1: First Month — Building the Computation Graph

```bash
# Ingest — all clean, all typed, no format issues
dataraum-context ingest --source gl_month1.csv --name "general_ledger" --type csv
dataraum-context ingest --source ecb_rates.csv --name "exchange_rates" --type csv
dataraum-context ingest --source intercompany_month1.csv --name "intercompany" --type csv

# Profile with financial reporting ontology
dataraum-context profile --all --ontology financial_reporting

# Serve MCP
dataraum-context serve
```

**In Claude Desktop (via MCP):**

**Query 1: "What's our consolidated revenue by entity for this month?"**

This is the money question. The agent must surface (not silently resolve) these decision points:

- "Entity DE-01 has a €240K annual contract booked as a single entry. Should I recognize the full amount in this month or amortize over 12 months? This affects revenue by ~€220K."
- "I found 3 credit memos totaling €45K with current-month posting dates but referencing prior-period invoices. Treat as current-month revenue reduction or exclude as prior-period?"
- "Exchange rate for CHF conversion: should I use transaction-date rates, month-end rate, or monthly average? Difference is ~€8K on consolidated revenue."

**Calibration check:** The agent must NOT silently pick an answer. Each of these is a quality gate. The human decides. The decision is encoded in the graph.

**Query 2: "Show me R&D spend by entity."**

- Agent should detect that CC-400 ("Shared Services") means different things in different entities
- Agent should flag this: "Cost center CC-400 maps to IT Infrastructure in DE-01 but Facilities in AT-01. Should I include IT Infrastructure as R&D-adjacent, or exclude both?"

**Calibration check:** The ontology ("financial_reporting") should enrich the context enough for the agent to recognize this isn't a simple sum.

**Query 3: "Reconcile intercompany transactions and show me the elimination entries."**

- Agent must handle the reference format mismatch (IC-2024-0001 vs INTER/2024/001) — but this is entity resolution, not format fixing
- Agent must surface the FX tolerance question: "15 transactions match by reference but differ in amount by 0.1-2.3%. Set a tolerance threshold for matching?"
- Agent must ask about management_fee elimination policy

**Calibration check:** Every matching decision is logged. The tolerance threshold becomes a parameter in the cached graph.

#### Act 2: Second Month — Reproducibility Under Change

```bash
dataraum-context ingest --source gl_month2.csv --name "general_ledger" --type csv --append
dataraum-context ingest --source intercompany_month2.csv --name "intercompany" --type csv --append
dataraum-context profile --incremental
```

**Query 4: "Run the same revenue consolidation for month 2."**

Expected behavior:
- Same graph executes. The annual contract amortization decision from month 1 applies automatically (€20K recognized, not €0 or €240K).
- Credit memo policy from month 1 carries forward.
- Exchange rate method (transaction-date / month-end / average) is the same.
- Quality gate fires for new entity PL-01: "New entity detected with 50 GL entries. Not yet configured for consolidation. Add to scope? If yes, what's the functional currency and intercompany elimination treatment?"

**Calibration check:** Month 2 numbers are comparable to month 1 BECAUSE the same judgment calls were applied. The new entity is caught, not silently included or excluded.

**Query 5: "Compare month 1 vs month 2 and explain the changes."**

- Because the computation graph is stable, the delta is meaningful
- Agent can distinguish: "Revenue decreased €35K. €20K is from the amortization treatment of DE-01's annual contract (expected). €15K is genuine decline in AT-01's recurring revenue."
- Without a stable graph, this explanation would be impossible — you wouldn't know if the change was real or methodological

**Query 6: "Project Q2 revenue by entity."**

- Projection uses the STABLE revenue definition across both months
- The annual contract amortization is baked into the baseline — the projection doesn't accidentally project from month 1's inflated number

### Success Criteria

- [ ] Agent surfaces ontological ambiguities as quality gates, not silent defaults
- [ ] Every judgment call (amortization, FX method, IC tolerance, credit memo treatment) is encoded in the graph
- [ ] Month 2 uses identical methodology to month 1 without re-prompting
- [ ] New entity triggers a quality gate, not a silent failure
- [ ] Month-over-month delta is explainable because the computation is stable
- [ ] Projection anchored to consistent revenue definition

---

## Test Case 2: Quarterly ESG / Regulatory Reporting

### The Story

A European company must report Scope 1, 2, and 3 carbon emissions quarterly under CSRD. The data arrives from well-structured systems — energy management platforms, corporate travel APIs, fleet management software. Every number is a number. Every date is a date. And yet the sustainability team can't tell the auditor whether the Munich office's Scope 2 number uses location-based or market-based methodology, because that decision was made in a spreadsheet formula three quarters ago by someone who's since left.

### Data Sources

| Source | Origin | Format | Notes |
|--------|--------|--------|-------|
| Energy consumption | Building management system API export | Structured CSV | Clean numbers. Ambiguous scope boundaries. |
| DEFRA conversion factors | `gov.uk` — published annually as XLSX | XLSX | Real reference data. Version matters enormously. |
| Fleet data | Fleet management system | Structured CSV | Typed fields. Scope classification is the challenge. |
| Business travel | Corporate travel management API | Structured CSV | Clean records. Category assignment is judgment. |
| Property portfolio | Facilities management system | Structured CSV | The boundary definition source. |

### Synthetic Data Generation Brief

#### Energy Consumption (energy_q{N}.csv) — ~500 rows/quarter

Columns: `facility_id`, `facility_name`, `date` (ISO), `energy_type` (enum: electricity/natural_gas/diesel), `consumption` (decimal), `unit` (kWh/m³/liters — consistently typed per energy_type), `meter_id`, `supplier`, `tariff_type`

All fields properly typed and consistently formatted. The ontological traps:

**Scope 2 methodology ambiguity:**
- Facility MUC-01 (Munich) has `tariff_type: "green"` — the supplier provides a renewable energy certificate. Under market-based Scope 2 accounting, this facility's electricity emissions are near-zero. Under location-based, they're the German grid average (~400g CO2/kWh). The data is identical either way — the number changes by 100% depending on the accounting method chosen.
- Facility VIE-01 (Vienna) switched suppliers mid-quarter. Old supplier was conventional, new supplier provides guarantees of origin. For the same quarter, should you apply two different emission factors? The data has accurate `supplier` fields for each record. The methodology choice is yours.

**Boundary ambiguity:**
- Facility ZRH-01 (Zurich HQ) consumes 450,000 kWh per quarter. But according to the property portfolio data, 35% of the floor space is subleased to two other companies. Does 100% of the energy go into your report, or 65%? The energy data has no concept of tenancy — it's the whole building.
- The company has a co-working membership at a WeWork in Berlin. No dedicated meter, no facility_id in the energy system. Should estimated energy from 15 desks be included? The GHG Protocol says it depends on your organizational boundary. The data system simply has no record of it.

**Temporal boundary:**
- The energy data for the end of the quarter arrives 3 weeks late (meter readings). Last quarter, the team estimated December's data based on November. This quarter, actual December data retroactively shows consumption was 15% higher than estimated. Do you restate Q4? The current quarter's data is accurate — the question is whether the prior quarter's graph should be re-executed.

#### Fleet Data (fleet_q{N}.csv) — ~200 rows/quarter

Columns: `vehicle_id`, `vehicle_type` (car/van/truck), `fuel_type` (diesel/petrol/electric/hybrid), `odometer_start`, `odometer_end`, `fuel_consumed` (liters), `period_start` (ISO), `period_end` (ISO), `assignment_type` (company_car/pool_vehicle/leased), `driver_employee_id`

All properly typed. The traps:

**Scope classification:**
- Company-owned vehicles (assignment_type: "company_car") are Scope 1. But 40% of the fleet is leased (assignment_type: "leased"). Are leased vehicles Scope 1 (operational control) or Scope 3 category 8 (leased assets)? Both are defensible. The answer depends on your organizational boundary approach — operational control vs financial control. Same data, different scope, different report section.
- Pool vehicles are used for both business travel and employee commuting. The data doesn't distinguish trip purpose. For Scope 1, it doesn't matter (all fuel burned is counted). But for Scope 3 category 7 (employee commuting), the commuting portion should be separated. There's no field in the data for this.
- Three electric vehicles have zero fuel_consumed but high odometer readings. Their Scope 1 emissions are zero. But the electricity they consumed should be in Scope 2 — and it's not in the energy data because they charge at public stations, not at company facilities. The data is correct in both systems. The gap is invisible.

**Hybrid vehicle complexity:**
- Five hybrid vehicles have both fuel_consumed (for petrol) and estimated kWh (for electric drive). The data has two consumption figures for one vehicle. The GHG Protocol requires you to account for both. But the kWh estimate is self-reported by the vehicle's onboard computer and may not match actual grid impact.

#### Business Travel (travel_q{N}.csv) — ~300 rows/quarter

Columns: `booking_id`, `employee_id`, `date` (ISO), `origin` (IATA/city), `destination` (IATA/city), `transport_mode` (flight/rail/car_rental), `class` (economy/business/first — for flights), `distance_km` (decimal), `cost_eur` (decimal)

Clean, structured data from the corporate travel API. The traps:

**Emission factor selection:**
- A flight from Zurich to London is 950 km. But emission factors differ dramatically based on: short-haul vs long-haul classification (DEFRA threshold is typically 3,700 km), economy vs business class (business has ~2-3x the emissions per passenger due to space allocation), and whether you include radiative forcing (a multiplier of 1.9 for high-altitude effects). The data gives you distance and class. The factor choice is policy.
- Rail travel within Europe: the emission factor varies by country (French rail is nearly zero due to nuclear, German rail is much higher). A trip from Paris to Frankfurt crosses both. Which factor applies?

**Scope 3 category ambiguity:**
- An employee flies to a client site for a project. Is this Scope 3 category 6 (business travel) or is it a project cost that should be allocated to Scope 3 category 1 (purchased goods/services) if the project is for a client? The travel data can't distinguish purpose.
- Hotel stays are in the travel data but are NOT transportation emissions — they're a separate emission source (Scope 3 category 5 or 6). Some teams include them, some don't. The data has both in the same feed.

#### DEFRA Conversion Factors — real data

Download actual DEFRA 2024 factors. Key ontological issue: DEFRA publishes factors for "well-to-tank" (WTT) and "tank-to-wheel" (TTW) separately. Comprehensive reporting requires both. But many teams only use one, understating emissions by 15-20%. The factor spreadsheet has both — the question is which rows you join.

#### Property Portfolio (property_q{N}.csv) — ~20 rows

Columns: `facility_id`, `facility_name`, `address`, `country`, `total_area_m2`, `occupied_area_m2`, `subleased_area_m2`, `ownership_type` (owned/leased/co-working), `lease_start` (ISO), `lease_end` (ISO or null)

This is the boundary definition source. It determines which energy data is in-scope and at what proportion. The traps:
- A facility has `ownership_type: "leased"` — is it in your operational boundary? Depends on your control approach.
- The co-working space has no facility_id in the energy system. Gap by design.

#### Quarter 2 variations

- A new facility (LIS-01, Lisbon) appears in energy data. Property portfolio shows it was onboarded mid-quarter. Partial-period reporting needed.
- DEFRA publishes updated 2025 factors mid-year. Do you retroactively recompute Q1 with new factors, or use 2024 factors for Q1 and 2025 for Q2? (Comparability vs accuracy trade-off.)
- One vehicle was sold mid-quarter. Fleet data has readings up to the sale date. The vehicle should drop out of scope — but its prior emissions are still in the Q1 graph.

### Pipeline Execution

#### Act 1: First Quarter — Establishing Methodology

```bash
dataraum-context ingest --source energy_q1.csv --name "energy_consumption" --type csv
dataraum-context ingest --source fleet_q1.csv --name "fleet" --type csv
dataraum-context ingest --source travel_q1.csv --name "business_travel" --type csv
dataraum-context ingest --source defra_2024.xlsx --name "emission_factors" --type xlsx
dataraum-context ingest --source property_q1.csv --name "property_portfolio" --type csv

dataraum-context profile --all --ontology sustainability
dataraum-context serve
```

**Query 1: "Calculate our Scope 2 emissions by facility."**

The agent must surface these decision points as quality gates:

- "Facility MUC-01 has a green tariff. Use location-based method (German grid average: ~680 tCO2e) or market-based method (residual mix with green certificate: ~12 tCO2e)? This is a 98% difference."
- "Facility ZRH-01 has 35% subleased area per property portfolio. Apply proportional allocation (295,000 kWh instead of 450,000 kWh) or report full building consumption?"
- "Facility VIE-01 changed suppliers mid-quarter. Apply single factor or split calculation at changeover date?"
- "DEFRA factors include both WTT and TTW components. Include well-to-tank emissions? This adds approximately 15% to the total."

Each decision → encoded in graph → applied consistently going forward.

**Query 2: "Calculate Scope 1 emissions from our fleet."**

- "40% of vehicles are leased. Classify as Scope 1 (operational control) or Scope 3 category 8 (leased assets)?"
- "3 electric vehicles consumed grid electricity at public charging stations — not captured in energy data. Estimate and include in Scope 2, or note as a known gap?"
- "Hybrid vehicles have dual fuel records. Include both petrol combustion (Scope 1) and estimated grid electricity (Scope 2)?"

**Query 3: "Calculate Scope 3 business travel emissions."**

- "Flight emission factors: should I apply radiative forcing multiplier (1.9x) for high-altitude climate impact? DEFRA includes this as an optional factor. It approximately doubles aviation emissions."
- "Flight ZRH-LHR: 950 km. Classify as short-haul or long-haul? DEFRA threshold is 3,700 km (short-haul). But some frameworks use 1,500 km."
- "Business class flights: apply class-specific multiplier (2.6x economy) or use average passenger factor?"
- "Hotel stays appear in travel data. Include in travel emissions or separate into Scope 3 category 5?"

**Query 4: "Generate the complete quarterly emissions report — Scope 1, 2, and 3."**

- Combines all three cached graphs
- Every number traces back to: source data → boundary decision → factor selection → calculation
- The report includes a methodology section generated from the encoded graph decisions

**Calibration check:** Print the methodology section. Does it accurately reflect every decision made in queries 1-3? Could an auditor read it and know exactly what was included, excluded, and why?

#### Act 2: The Auditor Test

**Query 5: "Show me exactly how the Scope 2 number for Munich was calculated, from source data to final figure."**

Expected lineage:
```
energy_consumption [facility_id=MUC-01, energy_type=electricity]
  → filter: date within Q1
  → sum: 680,000 kWh
  → boundary: 100% (no sublease for this facility)
  → method: market-based (decision: gate_001, decided 2024-03-15)
  → factor: DEFRA 2024, residual mix with GO certificate: 0.018 kg CO2e/kWh
  → WTT: included (decision: gate_004)
  → result: 12.24 tCO2e
```

**Calibration check:** Every node in the lineage references either source data or a named decision. Nothing is implicit.

#### Act 3: Second Quarter — Methodology Consistency

```bash
dataraum-context ingest --source energy_q2.csv --name "energy_consumption" --type csv --append
dataraum-context ingest --source fleet_q2.csv --name "fleet" --type csv --append
dataraum-context ingest --source travel_q2.csv --name "business_travel" --type csv --append
dataraum-context profile --incremental
```

**Query 6: "Run the same emissions report for Q2."**

- Same graphs execute on new data
- Quality gates fire for new issues only:
  - "New facility LIS-01 detected. Added mid-quarter (property portfolio shows onboarding April 15). Include from onboarding date only? Apply proportional period allocation?"
  - "Vehicle V-012 was sold mid-quarter. Exclude post-sale readings?"
- All Q1 methodology decisions carry forward automatically

**Query 7: "DEFRA has published 2025 factors. Should we update?"**

This is a graph modification decision:
- Option A: Recompute Q1 with 2025 factors (better accuracy, breaks comparability)
- Option B: Use 2024 for Q1, 2025 for Q2 (preserves comparability, mixed methodology)
- Option C: Report both in Q2 (transparency, more work)
- The decision is logged. The graph records which factor version was used for which period.

**Query 8: "Compare Q1 vs Q2 emissions and explain the changes."**

- Because the methodology is stable, the delta is real
- Agent can attribute: "Scope 2 increased 8%. 5% from new Lisbon facility. 3% from increased consumption in Munich (seasonal). No methodology changes."
- Without stable graphs: impossible to separate real changes from methodology drift

### Success Criteria

- [ ] Market-based vs location-based decision is a named, auditable gate — not a silent default
- [ ] Organizational boundary (operational vs financial control) is encoded once and applied to all scopes
- [ ] DEFRA factor version is explicitly tracked per calculation period
- [ ] Sublease proportional allocation uses property portfolio data, not hardcoded
- [ ] Q1 and Q2 methodology is provably identical where no gates were changed
- [ ] New facilities, sold vehicles, and factor updates all trigger quality gates
- [ ] Full lineage from any reported number to source rows + decision gates
- [ ] Radiative forcing, WTT inclusion, class multipliers — each is an explicit parameter, not implicit

---

## Test Case 3: Weekly SaaS Board Metrics

### The Story

A Series A startup reports weekly metrics to investors. Stripe data is clean. HubSpot data is clean. Product analytics data is clean. Last month, MRR "jumped" 12% in the board deck because the analyst included a one-time implementation fee in the subscription revenue calculation. The week before, net retention looked amazing because a multi-year contract renewal was counted as expansion when it was actually a flat renewal at a higher list price. Nobody caught either error because the calculation was different every time.

### Data Sources

| Source | Origin | Format | Notes |
|--------|--------|--------|-------|
| Stripe billing data | Stripe Sigma export or API | Structured CSV matching Stripe schema | Clean JSON/CSV. Interpretation is everything. |
| Product usage events | Product analytics platform (Mixpanel/Amplitude-style) | Structured CSV | Typed events. Engagement definition is judgment. |
| HubSpot CRM deals | HubSpot API export | Structured CSV | Clean records. Pipeline logic is the challenge. |

### Synthetic Data Generation Brief

#### Stripe Data (stripe_week{N}.csv) — ~500 rows/week

Columns: `invoice_id`, `customer_id`, `customer_name`, `amount` (cents, integer), `currency` (ISO), `status` (paid/void/refunded/uncollectable), `description`, `subscription_id` (nullable), `plan_id` (nullable), `plan_interval` (month/year/null), `quantity`, `created` (ISO timestamp), `period_start` (ISO), `period_end` (ISO), `billing_reason` (subscription_create/subscription_cycle/subscription_update/manual/upcoming), `discount_amount` (cents), `tax_amount` (cents)

All fields perfectly typed per Stripe's schema. The ontological traps:

**MRR definition ambiguity:**
- Customer "Acme Corp" has `plan_interval: "year"`, `amount: 12000000` (€120,000/year). Their MRR contribution is €10,000/month. But the invoice shows €120K. A naive sum of subscription amounts gives you an MRR that's 12x too high for annual customers. The data is correct — the annualization logic is what matters.
- Customer "Beta Inc" upgraded mid-month. Stripe creates a prorated credit (-€350) for the old plan and a prorated charge (+€580) for the new plan. Both have `subscription_id` populated and `billing_reason: "subscription_update"`. The actual MRR change is the difference between old and new monthly rates, NOT the sum of proration line items. Naive summation double-counts the transition month.
- Invoice with `subscription_id: null` and `billing_reason: "manual"` for €25,000 — a one-time implementation fee. Same customer also has a subscription charge in the same week. Is the implementation fee revenue? Yes. Is it MRR? Absolutely not. But there's no field called "is_recurring" — you must infer from `subscription_id` and `billing_reason`.
- Customer "Gamma GmbH" pays in EUR. Your reporting currency is USD. Stripe records `amount: 5000` and `currency: "eur"`. For MRR reporting: convert at invoice date rate, at a fixed monthly rate, or at current rate? Each gives a different MRR and a different month-over-month growth rate. The choice also affects whether MRR changes reflect real business growth or just FX movements.

**Churn and retention ambiguity:**
- Customer "Delta Corp" has `status: "paid"` for a subscription charge, but the subscription itself was set to `cancel_at_period_end` (not visible in the invoice data — it's a subscription-level attribute). They're paying this month. They will not pay next month. Are they churned? For current MRR: no. For retention forecasting: yes. For churn rate calculation: depends on when you count churn (cancellation request date or actual expiry date).
- Customer "Epsilon Ltd" went `past_due → paid` after a failed payment was retried successfully 5 days later. In the weekly snapshot, they appeared as at-risk. In the final data, they're fine. If your metric calculation ran on Tuesday (during the past_due window), you'd report involuntary churn that didn't happen. This is a temporal observation problem, not a data quality problem.
- Customer "Zeta Inc" downgraded from Enterprise ($5,000/mo) to Professional ($1,000/mo). For net revenue retention: this is -$4,000 contraction. But the customer simultaneously added 3 seats at $500 each on the Professional plan. The net change is -$2,500. But depending on whether you calculate NRR at the customer level or the subscription level, you get different numbers.

**Discount and tax treatment:**
- Several invoices have `discount_amount` > 0. Are discounted subscriptions counted at list price or net price for MRR? If you report net MRR, a discount expiring looks like expansion. If you report list MRR, you're overstating collectible revenue.
- Tax amounts vary by jurisdiction. MRR should exclude tax, but the `amount` field in Stripe includes tax in some configurations. The `tax_amount` field is the adjustment — but you have to know to subtract it.

#### Product Usage (usage_week{N}.csv) — ~1,000 rows/week

Columns: `user_id`, `customer_id`, `timestamp` (ISO), `event_type` (enum: login/query/export/api_call/dashboard_view), `feature` (string), `session_id`, `platform` (web/api/mobile)

Clean event data. The traps:

**Active user definition:**
- "DAU" / "WAU" — does a `login` event count, or does the user need to perform a value-action (query, export, api_call)? Dashboard_view is passive. Login might be accidental (SSO redirect). The event data is comprehensive — the definition of "active" is policy.
- A customer has 10 seats. 3 users logged in this week. Is this customer "active"? What if those 3 users only viewed dashboards and never ran a query? The activation threshold determines whether this is a healthy customer or a churn risk — and there's no field for "healthy."
- API calls from automated scripts (platform: "api") run 24/7. One customer generates 10,000 events/week, all automated. Another generates 50 events/week, all manual high-value analysis. By event count, the first is your most engaged customer. By business value, it's the second.

**Customer-user mapping:**
- `user_id` in usage data maps to individual users. `customer_id` maps to the paying account. Some users belong to multiple customers (consultants, agencies). Their activity should be counted for each customer they're active in — but the data might attribute all activity to their primary customer_id.

#### HubSpot Deals (hubspot_week{N}.csv) — ~100 rows

Columns: `deal_id`, `company_name`, `contact_name`, `amount` (decimal), `currency`, `stage` (enum: discovery/qualified/proposal/negotiation/closed_won/closed_lost), `probability` (decimal 0-1), `close_date` (ISO), `create_date` (ISO), `owner`, `deal_type` (new_business/renewal/expansion/professional_services), `contract_months` (integer)

Clean CRM data. The traps:

**Pipeline forecast ambiguity:**
- A deal is `stage: "negotiation"` with `probability: 0.6` and `amount: 120000`. The pipeline-weighted value is $72K. But `amount` is the total contract value over `contract_months: 24`. The ARR impact is $60K. The pipeline-weighted ARR impact is $36K. Using total contract value inflates the pipeline forecast by 2x.
- A renewal deal has `deal_type: "renewal"` and `amount: 55000`. The existing contract was $50,000. Is this $5,000 expansion or a flat renewal at an updated price (list price increased)? For forecasting, these are very different signals. The data doesn't distinguish real expansion from price-increase-driven renewal.

**Cross-source entity matching:**
- HubSpot has `company_name: "Acme Corporation"`. Stripe has `customer_name: "Acme Corp"`. Usage data has no customer name, only `customer_id: "cust_abc123"`. HubSpot has no Stripe customer_id. The join path is ambiguous — and getting it wrong means your pipeline can't be validated against actual conversion (did the deals we forecasted actually become Stripe subscriptions?).
- A HubSpot deal for "Acme Corp" closes. But Acme Corp already has a Stripe subscription (they're expanding). The "new business" vs "expansion" classification in HubSpot might not match reality if the sales rep didn't know about the existing subscription.

**Temporal logic:**
- A deal has `close_date: 2024-01-31` and `stage: "closed_won"`. But the Stripe subscription `created` date is `2024-03-15` (implementation took 6 weeks). For board metrics: is this Q1 revenue or Q1 bookings? Does the pipeline conversion metric count the deal as converted in Q1 (by close_date) or Q1+ (by revenue start)?

#### Week 2 and Week 3 variations

Week 2:
- A Stripe webhook-style schema change: `billing_reason` gets a new value `"subscription_threshold"` (usage-based billing threshold trigger). The graph's MRR filter doesn't know this category. Include or exclude?
- A customer who was `cancel_at_period_end` last week actually canceled. Their subscription charges disappear from the data. The graph should show this as churn — but only if the graph was tracking pending cancellations.

Week 3:
- A large annual contract renews ($180K/year). Last week it was in the pipeline. This week it's a Stripe invoice. The pipeline forecast should have predicted this. Does it match?
- A customer disputes a charge. Stripe creates a `status: "disputed"` record. Is disputed revenue still MRR until resolved?

### Pipeline Execution

#### Act 1: Establishing the Metric Definitions

```bash
dataraum-context ingest --source stripe_week1.csv --name "stripe_billing" --type csv
dataraum-context ingest --source usage_week1.csv --name "product_usage" --type csv
dataraum-context ingest --source hubspot_week1.csv --name "crm_pipeline" --type csv

dataraum-context profile --all --ontology saas_metrics
dataraum-context serve
```

**Query 1: "What's our MRR?"**

Quality gates that MUST fire:

- "Found annual subscriptions ($120K invoice, plan_interval='year'). Normalize to monthly ($10K) or use invoice amount? Normalization reduces reported MRR by ~$110K."
- "Found 3 invoices with no subscription_id (manual/one-time charges totaling $43K). Exclude from MRR? Including them inflates MRR by 8%."
- "Customer Beta Inc has proration charges from a mid-month upgrade. Use old plan rate, new plan rate, or net of prorations for their MRR contribution?"
- "5 subscriptions are in EUR. Convert at invoice-date rate or fixed rate? Using invoice-date rate introduces FX volatility into MRR trend."
- "Discount treatment: 12 subscriptions have active discounts totaling $2,400/month. Report gross MRR (list price) or net MRR (after discount)?"

Each decision → named parameter in the graph. Re-running "What's our MRR?" next week hits the SAME graph with these same parameters.

**Query 2: "What's our net revenue retention?"**

- Agent should REUSE the MRR graph's definition of revenue (same exclusions, same FX treatment)
- Additional gates: "Calculate NRR at customer level or subscription level? Customer 'Zeta Inc' downgraded one subscription but added another — customer-level NRR shows -$2,500, subscription-level shows -$4,000 and +$1,500 separately."
- "Time window for retention: compare to same-month-last-year, or to last month? Annual NRR is standard for board reporting."

**Query 3: "How many active customers do we have?"**

- "Define 'active': any event this week, or at least one value-action (query/export/api_call)? Using any-event: 142 customers. Using value-action only: 98 customers."
- "Customer with only automated API calls (10,000 events, all platform='api'): classify as active?"
- "3 users are associated with multiple customer accounts. Count activity for each customer or primary only?"

**Query 4: "What's the pipeline-weighted forecast for next quarter?"**

- "Deal amounts include multi-year contracts. Normalize to ARR for forecast? Without normalization, pipeline is overstated by ~40%."
- "Deal 'Acme Corp renewal' is classified as 'new_business' but Acme already has a Stripe subscription. Reclassify as 'expansion'?"
- "Closed-won deals with future contract start dates: include in current-quarter conversion rate or future-quarter?"

**Query 5: "Give me the weekly board summary."**

- Combines all cached graphs
- Produces: MRR, MRR growth %, NRR, active customers, activation rate, pipeline forecast
- Every metric traces to its graph and its encoded decisions

**Calibration check:** Print the metric definitions section. Read it. Is it what your board would agree to? If not, change the parameters — don't rebuild the graph.

#### Act 2: The Reproducibility Proof

**Query 6: "What's our MRR?" (same question, same week)**

- Expected: IDENTICAL number. Same graph, same data, same result.
- Run it 3 times. Same number 3 times. This is the demo moment.

**Query 7: "What's our monthly recurring revenue including implementation fees?"**

- Expected: Agent recognizes this is a DIFFERENT metric. Creates a new graph (or branches from MRR graph with the one-time exclusion parameter changed).
- The system distinguishes "same metric" from "different metric" — it doesn't silently redefine MRR.

**Baseline comparison:** Ask Claude Desktop (no dataraum) "What's our MRR?" twice. Document the two different SQL queries it generates. Show the audience.

#### Act 3: Weeks 2-3 — Stability Under Change

```bash
dataraum-context ingest --source stripe_week2.csv --name "stripe_billing" --type csv --append
dataraum-context ingest --source usage_week2.csv --name "product_usage" --type csv --append
dataraum-context ingest --source hubspot_week2.csv --name "crm_pipeline" --type csv --append
dataraum-context profile --incremental
```

**Query 8: "Run the weekly board summary for week 2."**

- Same graphs execute on new data
- Quality gate: "New billing_reason value detected: 'subscription_threshold' (usage-based billing). Classify as recurring (include in MRR) or usage-based (exclude)? 4 invoices affected, totaling $3,200."
- Quality gate: "Customer Delta Corp's subscription has ended (was pending cancellation last week). Recording as churn: MRR impact -$2,400."
- All other metric definitions unchanged.

**Query 9: "Compare week 1 vs week 2 metrics and explain changes."**

- Because computation is stable, deltas are meaningful
- "MRR decreased $2,400 (Delta Corp churn). Excluding the churn event, organic MRR grew $1,800 from 2 new subscriptions."
- "Active customers decreased by 1 (Delta Corp) but activation rate improved 2pp because a previously passive customer started running queries."
- Without stable graphs, you can't decompose changes into causes

**Week 3:**
```bash
dataraum-context ingest --source stripe_week3.csv --name "stripe_billing" --type csv --append
dataraum-context profile --incremental
```

**Query 10: "Project MRR for the next 8 weeks."**

- Projection built on 3 weeks of CONSISTENTLY DEFINED MRR
- The trend is real because the underlying metric didn't drift
- Show what happens without stable definitions: the projection would be fitting a curve to 3 data points where each point was computed differently

**Query 11: "A large renewal just closed ($180K/year). Was this in last week's pipeline forecast?"**

- Cross-reference: cached pipeline graph from week 2 → does the deal appear? At what probability?
- This validates the pipeline forecast against actual outcomes — only possible because both the forecast and the actuals use consistent definitions

### Success Criteria

- [ ] MRR graph explicitly parameterizes: annual normalization, one-time exclusion, proration handling, FX method, discount treatment, tax exclusion
- [ ] Same NL query hits same cached graph — verified by running 3x
- [ ] "MRR" and "MRR including implementation fees" resolve to provably different graphs
- [ ] NRR graph reuses MRR graph's revenue definition (not an independent interpretation)
- [ ] Active customer definition is a named parameter, not an implicit choice
- [ ] New billing_reason values trigger quality gates, not silent inclusion/exclusion
- [ ] Week-over-week delta is decomposable because methodology is stable
- [ ] Pipeline deals are joinable to Stripe outcomes via entity resolution graph
- [ ] Projection anchored to stable computation across all available weeks

---

## Cross-Cutting Calibration Checks

Apply to ALL three test cases:

### Ontological Consistency
- Every business judgment (what counts as revenue? what's in scope? how do you define active?) is an explicit, named parameter in the computation graph
- No silent defaults — every ambiguity surfaces as a quality gate on first encounter
- Subsequent runs apply the same decisions without re-prompting

### Reproducibility
- Same NL query → same graph → same result (verify 3x per test case)
- Slightly different NL phrasing of the same question → same graph
- Meaningfully different question → different graph (system distinguishes the two)

### Persistence & Reuse
- Computation graphs survive server restart
- New data flows through existing graphs
- Dependent graphs (e.g., NRR depends on MRR) reuse upstream definitions

### Audit Trail
- Any number → graph node → decision gate + source rows
- Decision gates record: what was decided, when, by whom, and what alternatives existed
- Graph modifications (methodology changes) are versioned events

### Drift & Change Detection
- New enum values, new entities, schema additions trigger quality gates
- The system distinguishes "new data conforming to known patterns" from "data that challenges existing assumptions"
- Methodology changes (e.g., DEFRA factor update, reclassification) are explicit graph modifications, not silent rewrites

### Baseline Comparison (Critical for Demos)
- For each test case, run the same top-level queries in Claude Desktop without dataraum
- Document: different SQL generated on re-run? Edge cases handled differently? Judgment calls made silently?
- This is the "why dataraum" evidence — show it side by side

---

## Execution Order

1. **Test Case 3 first** (SaaS metrics) — fastest iteration, most visceral "same question different answer" problem, broadest audience
2. **Test Case 1 second** (Financial close) — higher complexity, stronger enterprise story, builds on patterns from TC3
3. **Test Case 2 third** (ESG) — most complex boundary decisions, strongest regulatory/audit story, requires all patterns working

For each: validate Act 1 (graph building + quality gates) before proceeding. The graphs must be correct before reproducibility testing is meaningful.

---

## Data Generation Priority

The synthetic data scripts should focus on:

1. **Realistic record structures** matching actual API schemas (Stripe, HubSpot, SAP GL)
2. **Ontological traps** — correct-but-ambiguous records as described above
3. **Cross-source entity resolution challenges** — same real-world entity, different representations
4. **Temporal boundary conditions** — events that straddle periods, pending states, retroactive corrections
5. **NOT format issues** — all dates ISO, all numbers typed, all currencies ISO 4217

The messy-CSV era is over. The ontological-ambiguity era is where dataraum lives.
