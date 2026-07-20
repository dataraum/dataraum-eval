"""DAT-762 identity gate, corrected to the grain the ENGINE actually uses.

The first identity_gate.py ran on the raw DIMENSION tables, where raceId/date are
UNIQUE keys. On that grain the finder's perm-BH test rejects them (FI stays 1.0
under every shuffle → p ≈ 1.0 → BH drops it), so they never reach the judge — the
gate tested a population the engine filters out.

The engine runs on the FACT-GRAIN enriched view, where a folded key and its
attributes REPEAT (once per fact row). There a coincidental bijection (an account
key lining up 1:1 with an opened-date) is NON-key, passes perm-BH, and DOES reach
the judge (verified by running discover_dimension_hierarchies). So this re-runs the
gate on fact-grain-shaped evidence, with the SHIPPED prompt (dimension_alias.yaml),
over both true code↔name aliases and coincidental bijections.

Pass: confidence(true alias) merges (≥0.8), confidence(coincidental) does not, with
a clear margin — the shipped prompt separates the class the engine now routes to it.
"""
from __future__ import annotations

import json
from pathlib import Path

import anthropic
import yaml

MODEL = "claude-sonnet-5"
PROMPT = (
    Path(__file__).resolve().parents[3]
    / "vendor/dataraum-context/.claude/worktrees/dat762-lane"
    / "packages/dataraum-config/llm/prompts/dimension_alias.yaml"
)

# Fact-grain candidates (values REPEAT — the folded-dimension shape). truth = is it
# a true relabeling alias? Distinct counts are the fact-grain distincts (small),
# rows are the fact rows.
CASES = [
    # true code↔name aliases (should merge)
    {"a": ("account_id", 3, ["A0", "A1", "A2"]), "b": ("account_name", 3, ["Cash", "Receivable", "Payable"]), "alias": True},
    {"a": ("status_code", 3, ["1", "2", "3"]), "b": ("status_label", 3, ["open", "closed", "pending"]), "alias": True},
    {"a": ("currency_code", 3, ["USD", "EUR", "GBP"]), "b": ("currency_name", 3, ["US Dollar", "Euro", "Pound"]), "alias": True},
    # coincidental bijections — 1:1 in the data, DIFFERENT dimensions (should not merge)
    {"a": ("account_id", 3, ["A0", "A1", "A2"]), "b": ("opened_date", 3, ["2020-01-01", "2020-02-01", "2020-03-01"]), "alias": False},
    {"a": ("region", 2, ["north", "south"]), "b": ("lead_manager_id", 2, ["M1", "M2"]), "alias": False},
    {"a": ("product_id", 3, ["P0", "P1", "P2"]), "b": ("first_sold_ts", 3, ["2021-03-01", "2021-06-01", "2021-09-01"]), "alias": False},
]
N_ROWS = 30


def system() -> str:
    return yaml.safe_load(PROMPT.read_text())["system_prompt"]


def load_key() -> str:
    env = Path(__file__).resolve().parents[3] / ".env"
    for line in env.read_text().splitlines():
        if line.startswith("ANTHROPIC_API_KEY"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("no key")


def block(i: int, c: dict) -> str:
    (an, ad, asv), (bn, bd, bsv) = c["a"], c["b"]
    return (
        f"- ref={i} table=facts\n"
        f"    a: {an} — {ad} distinct, e.g. {', '.join(asv)}\n"
        f"    b: {bn} — {bd} distinct, e.g. {', '.join(bsv)}"
    )


def main() -> None:
    client = anthropic.Anthropic(api_key=load_key())
    user = (
        "Candidate bijection pairs to judge:\n"
        + "\n".join(block(i, c) for i, c in enumerate(CASES))
        + '\n\nAnswer with ONLY a JSON array, one object per pair: '
        '[{"ref": <int>, "same_dimension": true|false, "confidence": <float>, "reason": "<one sentence>"}]'
    )
    resp = client.messages.create(
        model=MODEL, max_tokens=1500, system=system(),
        messages=[{"role": "user", "content": user}],
    )
    text = next(b.text for b in resp.content if getattr(b, "type", None) == "text")
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1].removeprefix("json").strip()
    arr = json.loads(raw)
    by = {int(v.get("ref", v.get("pair_ref", k))): v for k, v in enumerate(arr)}

    print(f"{'pair':<40} {'truth':>8} {'same?':>6} {'conf':>5}  reason")
    print("-" * 110)
    alias_conf, coincid_conf = [], []
    for i, c in enumerate(CASES):
        v = by[i]
        conf = float(v["confidence"])
        (alias_conf if c["alias"] else coincid_conf).append(conf)
        label = f"{c['a'][0]}<->{c['b'][0]}"
        print(f"{label:<40} {'ALIAS' if c['alias'] else 'COINCID':>8} "
              f"{str(v['same_dimension']):>6} {conf:>5.2f}  {v.get('reason','')[:60]}")
    print("\n--- SEPARATION (shipped prompt, fact-grain cases) ---")
    print(f"true aliases   conf: min {min(alias_conf):.2f}  mean {sum(alias_conf)/len(alias_conf):.2f}")
    print(f"coincidental   conf: max {max(coincid_conf):.2f}  mean {sum(coincid_conf)/len(coincid_conf):.2f}")
    margin = min(alias_conf) - max(coincid_conf)
    gate = min(alias_conf) >= 0.8 and max(coincid_conf) < 0.8
    print(f"margin {margin:+.2f} — GATE {'PASS' if gate else 'FAIL'} "
          f"(aliases ≥0.8 merge, coincidental <0.8 surface)")


if __name__ == "__main__":
    main()
