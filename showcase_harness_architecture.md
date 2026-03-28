# Showcase Harness Architecture

## Relationship to DAT-191

DAT-191 defines ground truth regression for the MCP tool surface — pytest-based, per-phase, asserting tool outputs against `ground_truth.yaml` and `entropy_map.yaml`. The showcase harness is not a separate system. It's the **demo-facing projection** of the same ground truth infrastructure.

```
dataraum-eval (DAT-191)          showcase harness
├── ground_truth.yaml       ←──  same data, same expected outcomes
├── entropy_map.yaml        ←──  same injections, same trap catalog
├── test_hypothesize.py     →    "agent proposes gift card = liability"
├── test_fix_loop.py        →    "user confirms, applied to 200 rows"
├── test_teach_*.py         →    "decision persists, auto-applies month 2"
└── test_session_e2e.py     →    full recorded MCP session
```

The eval proves correctness via pytest. The showcase demonstrates the experience via a recorded MCP session. Both use the same ground truth — if the eval passes, the showcase is verifiable.

## What a Showcase Is

A showcase is a **scenario + beat sheet + verification criteria**, not a script. The agent improvises through the MCP tools. The beat sheet defines what must happen (in order). The verification checks that it did.

### Scenario

A self-contained directory in `dataraum-eval`:

```
showcases/
  shopify-datev/
    scenario.yaml              # metadata: what this proves, domain, taxonomy
    data/                      # input files (synthetic or anonymized real)
      month1/
      month2/                  # variant with drift
    taxonomy/                  # target classification scheme
    ground_truth/
      classifications.yaml    # tx type → expected DATEV account mapping
      ambiguities.yaml        # items that MUST surface as hypothesize questions
      teach_decisions.yaml    # human resolutions + expected persistence keys
      drift_signals.yaml      # what month2 should flag vs month1
    beats.yaml                # ordered phases with verification hooks
```

### Beat Sheet

Not a conversation script — an ordered sequence of phases with tool expectations and verification hooks. The human follows the beats during recording; the agent responds naturally.

```yaml
scenario: shopify-datev
description: "Shopify transactions → DATEV Buchungssätze via classification loop"
proves: "hypothesize → fix → teach end-to-end with persistence and drift"

beats:
  - id: ingest
    phase: 1
    tools_expected: [add_source]
    human_action: "Upload 3 Shopify CSVs (orders, transactions, payouts)"
    verify:
      - "3 sources registered"
      - "order_id relationship detected across files"
      - "monetary columns identified with currency"

  - id: profile
    phase: 1
    tools_expected: [look, measure]
    human_action: "Ask agent to profile the data"
    verify:
      - "transaction types surfaced (sale, refund, shipping, gift card, etc.)"
      - "VAT complexity flagged"
      - "entropy scores computed for all dimensions"

  - id: classify
    phase: 3
    tools_expected: [hypothesize]
    human_action: "Ask agent to classify transactions against SKR04"
    verify_from: ground_truth/ambiguities.yaml
    must_surface:
      - id: gift_card_sale
        expected: "agent flags revenue vs liability ambiguity"
      - id: austrian_b2c_vat
        expected: "agent asks about DE 19% vs AT 20%"
      - id: shipping_revenue
        expected: "agent asks 4400 vs 4830"
      - id: partial_refund_allocation
        expected: "agent flags proportional allocation question"
    must_auto_classify:
      - id: standard_sale_de_19
        expected: "Soll 1200, Haben 4400, USt 19%"
      - id: payment_fee_shopify
        expected: "Soll 6855, Haben 1200"

  - id: resolve
    phase: 3
    tools_expected: [fix]
    human_action: "Resolve each ambiguity per teach_decisions.yaml"
    decisions:
      - gift_card_sale: "3480 Verbindlichkeiten (liability, not revenue)"
      - austrian_b2c_vat: "20% Austrian rate (destination principle)"
      - shipping_revenue: "4400 Erlöse (revenue, not other income)"
    verify:
      - "each decision applied to ALL matching transactions (not just the one shown)"
      - "fix scope count matches expected transaction count from ground truth"

  - id: persist
    phase: 3b/4
    tools_expected: [teach]
    human_action: "Ask agent to save decisions for reuse"
    verify:
      - "each decision persisted as config overlay"
      - "config keys match teach_decisions.yaml expected keys"
      - "report({ format: 'teachings' }) lists all persisted decisions"

  - id: validate_output
    phase: 2
    tools_expected: [validate]
    human_action: "Ask agent to validate the DATEV output"
    verify:
      - "debits = credits for every Buchungssatz"
      - "total revenue matches ground truth"
      - "total VAT matches ground truth"
      - "payout totals reconcile"

  - id: month2_rerun
    phase: 3b/4
    tools_expected: [hypothesize, teach]
    human_action: "Load month2 data, ask agent to classify"
    data: month2/
    verify_from: ground_truth/drift_signals.yaml
    must_auto_apply:
      - "all month1 teach decisions apply without re-asking"
      - "gift card transactions auto-classify to 3480"
      - "Austrian B2C auto-applies 20%"
    must_flag_drift:
      - id: new_payment_gateway
        expected: "new gateway (e.g. Apple Pay) triggers fresh hypothesize"
      - id: new_tax_rate
        expected: "changed rate or new country triggers ambiguity"
```

## Verification

Two modes:

### 1. Eval mode (pytest, automated)

Already defined in DAT-191. `test_hypothesize.py`, `test_fix_loop.py`, `test_teach_*.py`, `test_session_e2e.py` assert against ground truth directly. This runs in CI.

### 2. Showcase mode (post-recording check)

After a recorded MCP session, verify the session log against the beat sheet:

- Every `must_surface` ambiguity appeared in a `hypothesize` call
- Every `must_auto_classify` item was classified without human input
- Every `decision` in `resolve` was applied with correct scope
- Every `persist` key exists in the teach overlay
- Month 2 auto-applied all month 1 decisions
- Month 2 flagged all expected drift signals

This can be manual (reviewer checks the recording against beats.yaml) or semi-automated if tool responses are logged as structured JSON.

## The Flywheel

Once the first scenario (shopify-datev) is built:

| New showcase | What changes | What stays |
|---|---|---|
| Trial balance → HGB | data/, taxonomy/, ground_truth/ | Beat structure, verification pattern, harness |
| E-invoicing → XRechnung | data/, taxonomy/, ground_truth/ | Beat structure, verification pattern, harness |
| ESG → ESRS | data/, taxonomy/, ground_truth/ | Beat structure, verification pattern, harness |
| Any new domain | data/, taxonomy/, ground_truth/ | Beat structure, verification pattern, harness |

Each new showcase is: new synthetic data with seeded traps + new target taxonomy + new ground truth file. The beat sheet is domain-agnostic — ingest → profile → classify → resolve → persist → validate → rerun-with-drift is the universal structure.

## MCP Tool Surface Requirements

For the showcase to be verifiable, tool responses must include structured fields (not just prose):

### hypothesize
- `classification`: what it thinks the item is
- `confidence`: numeric
- `alternatives`: other plausible classifications with reasoning
- `ambiguity_flag`: boolean — is this auto-classified or surfaced for human resolution?
- `intent_deltas`: predicted score impact (already in DAT-191 spec)

### fix
- `resolution`: what was decided
- `scope`: which records it was applied to
- `affected_count`: how many records changed
- `evidence_chain`: references to hypothesize call that surfaced this

### teach
- `config_key`: where the decision was persisted
- `config_value`: what was saved
- `reuse_scope`: "all future sessions" / "this taxonomy" / etc.
- `loadable`: boolean — confirmed round-trippable

If these fields exist in tool responses, verification is mechanical. If they don't, showcase verification requires human judgment on prose.

## First Scenario: Shopify → DATEV

### Synthetic data spec

Generate 3 CSVs matching Shopify export structure with seeded traps from the strategy doc:

| Trap | Seeded in | Ground truth assertion |
|---|---|---|
| Gift card sale | orders.csv: 5 gift card orders | hypothesize must flag as liability (3480) not revenue (4400) |
| Partial refund | transactions.csv: 3 partial refunds on multi-item orders | hypothesize must flag proportional allocation |
| Multi-currency | orders.csv: 10 GBP orders, 5 USD orders | hypothesize must flag EUR conversion requirement |
| Austrian B2C | orders.csv: 8 orders with AT shipping address | hypothesize must ask DE 19% vs AT 20% |
| Payment timing | orders.csv: Dec orders + transactions.csv: Jan settlement | hypothesize must flag period assignment |
| Klarna fees | transactions.csv: different fee structure from Shopify Payments | hypothesize must flag different account code |
| Shipping as revenue | orders.csv: shipping charges on 80% of orders | hypothesize must ask 4400 vs 4830 |
| Discount types | orders.csv: coupon discounts + volume discounts | hypothesize must flag revenue reduction vs expense |
| Return vs refund | transactions.csv: 2 returns (goods back) + 2 refunds (money only) | hypothesize must flag different treatment |

Month 2 variant adds:
- 3 Apple Pay transactions (new gateway → drift signal)
- 2 Swiss customer orders (new country → VAT ambiguity)
- Gift cards now auto-classify (teach from month 1 applies)

### Ground truth file

Every transaction in the synthetic data maps to an expected DATEV Buchungssatz (Soll, Haben, Betrag, Steuerschlüssel). This is the oracle. Eval asserts against it. Showcase demonstrates it.
