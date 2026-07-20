"""DAT-762 identity RE-HISTOGRAM — the REDESIGNED confidence, billed once.

Runs the SHIPPED (worktree) dimension_alias.yaml DIRECTIONAL identity judge over
the held-out equal-cardinality bijection subset (ground-truthed via
rwd.exact_candidates), forced-tool, batched per table, cached + resumable.

Answers, on real data:
  (1) does p2series==p2type — the pair the OLD "decisiveness" prompt false-merged
      at 0.85 — now score LOW (< REL_CONFIRM_MIN = 0.7)?
  (2) do true aliases stay HIGH?
  (3) does the confidence land BIMODALLY with a dead zone around 0.7?
  (4) zero corrupt merges at 0.7?

A small labeled panel of CONSTRUCTED neutral bijections (the held-out slice has
only ONE real coincidental bijection) populates the low cluster so the shape is
visible. Real and constructed are reported separately — the held-out result stands
on its own.

Pinned to the WORKTREE prompt + tool schema, NOT the vendored engine copy.

    python rehist.py --dry     # ZERO LLM calls: population + 2 rendered prompts
    python rehist.py           # billed, resumable (append-only WAL)
    python rehist.py --smoke   # one batch only, inspect the wire
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import anthropic
import yaml

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import judge2  # noqa: E402  (facts, _profile, load_key, MODEL)
import rwd  # noqa: E402  (load_table, exact_candidates — truth-labelled)

WORKTREE = HERE.resolve().parents[2] / "vendor/dataraum-context/.claude/worktrees/dat762-lane"
PROMPT_PATH = WORKTREE / "packages/dataraum-config/llm/prompts/dimension_alias.yaml"

CACHE = HERE / "results_rehist.json"
WAL = HERE / "results_rehist.jsonl"

# Engine screens (identity lane): near-key removal + a distinct floor.
NEAR_KEY_FRAC, MIN_ROWS_NEARKEY, MIN_DISTINCT_DET = 0.9, 10, 3
# Support floor: a 1:1 over a handful of rows is trivial noise, not a real
# bijection. This corpus has a clean gap — degenerate pairs sit at n_rows<=9
# (sparse dblp columns), real bijections at n_rows>=35 — so 30 cleanly separates.
MIN_SUPPORT_ROWS = 30
REL_CONFIRM_MIN = 0.7  # the mirrored floor under test

_prompt = yaml.safe_load(PROMPT_PATH.read_text())
SYSTEM = _prompt["system_prompt"]
USER_TMPL = _prompt["user_prompt"]
TEMP = float(_prompt.get("temperature", 0.1))

# The NEW AliasIdentityBatchOutput schema (confidence-only, no same_dimension).
TOOL = {
    "name": "judge_aliases",
    "description": (
        "Return a calibrated [0,1] identity confidence and a one-sentence reason for "
        "every candidate bijection pair — high when the names and values plainly show "
        "one entity re-encoded, low when they are different attributes that align 1:1."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "pair_ref": {"type": "string"},
                        "confidence": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["pair_ref", "confidence", "reason"],
                },
            }
        },
        "required": ["verdicts"],
    },
}


# ---- population: held-out equal-cardinality bijections ------------------------
def _near_key(distinct: int, n: int) -> bool:
    return n >= MIN_ROWS_NEARKEY and distinct >= NEAR_KEY_FRAC * n


def bijection_population() -> list[dict]:
    """Unordered equal-card bijection pairs surviving the near-key screen, truth-labelled."""
    seen: set[tuple[str, frozenset[str]]] = set()
    out: list[dict] = []
    for c in rwd.exact_candidates():
        pair = frozenset((c["lhs"], c["rhs"]))
        key = (c["table"], pair)
        if len(pair) < 2 or key in seen:
            continue
        seen.add(key)
        f = judge2.facts(c["table"], c["lhs"], c["rhs"])
        if f.a.distinct != f.b.distinct:  # equal cardinality ⟹ bijection (FD already holds)
            continue
        if f.a.distinct < MIN_DISTINCT_DET or f.n_rows < MIN_SUPPORT_ROWS:
            continue
        if _near_key(f.a.distinct, f.n_rows) or _near_key(f.b.distinct, f.n_rows):
            continue
        out.append(
            {
                "table": c["table"],
                "a": c["lhs"],
                "b": c["rhs"],
                "truth": c["meaningful"],  # True = true alias, False = coincidental
                "card": f.a.distinct,
                "a_samples": f.a.samples,
                "b_samples": f.b.samples,
            }
        )
    return out


# A few CONSTRUCTED neutral bijections — labelled, to populate the low cluster.
CONSTRUCTED = [
    # true aliases (should score high)
    {"table": "constructed", "a": "country_code", "b": "country_name", "truth": True, "card": 3,
     "a_samples": ["DE", "FR", "US"], "b_samples": ["Germany", "France", "United States"]},
    {"table": "constructed", "a": "size_code", "b": "size_label", "truth": True, "card": 3,
     "a_samples": ["S", "M", "L"], "b_samples": ["Small", "Medium", "Large"]},
    {"table": "constructed", "a": "priority_level", "b": "priority_name", "truth": True, "card": 3,
     "a_samples": ["1", "2", "3"], "b_samples": ["Low", "Medium", "High"]},
    # coincidental bijections (should score low)
    {"table": "constructed", "a": "user_id", "b": "signup_date", "truth": False, "card": 3,
     "a_samples": ["U0", "U1", "U2"], "b_samples": ["2021-01-01", "2021-02-01", "2021-03-01"]},
    {"table": "constructed", "a": "product_id", "b": "first_seen_ts", "truth": False, "card": 3,
     "a_samples": ["P0", "P1", "P2"], "b_samples": ["2020-05-01", "2020-06-01", "2020-07-01"]},
    {"table": "constructed", "a": "device_id", "b": "owner_region", "truth": False, "card": 2,
     "a_samples": ["D0", "D1"], "b_samples": ["north", "south"]},
    {"table": "constructed", "a": "color", "b": "shape", "truth": False, "card": 3,
     "a_samples": ["red", "green", "blue"], "b_samples": ["circle", "square", "triangle"]},
]


def ref_of(p: dict) -> str:
    return f"{p['table']}#{p['a']}#{p['b']}"


def render_block(pairs: list[dict]) -> str:
    """Exactly DimensionIdentityJudge._format_alias_candidates (empty meanings)."""
    blocks: list[str] = []
    for p in pairs:
        blocks.append(f"- ref={ref_of(p)} table={p['table']}")
        for side, name, samples in (("a", p["a"], p["a_samples"]), ("b", p["b"], p["b_samples"])):
            s = ", ".join(str(v) for v in samples)
            blocks.append(f"    {side}: {name} — {p['card']:,} distinct" + (f", e.g. {s}" if s else ""))
    return "\n".join(blocks)


def prompt_for(pairs: list[dict]) -> str:
    return USER_TMPL.format(candidates=render_block(pairs))


def _retry(fn, tries=6):
    for k in range(tries):
        try:
            return fn()
        except anthropic.BadRequestError:
            raise  # a 400 is a permanent request error — never retry, never spend on it
        except (anthropic.InternalServerError, anthropic.RateLimitError,
                anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            if k == tries - 1:
                raise
            wait = min(2**k, 30)
            print(f"  transient {type(e).__name__}, retry {k + 1}/{tries} in {wait}s")
            time.sleep(wait)


def ask_batch(client, pairs: list[dict]) -> dict[str, dict]:
    # sonnet-5 deprecated `temperature` (the yaml's 0.1 is honoured by the engine
    # provider, which drops it for models that reject it); omit it here.
    resp = _retry(lambda: client.messages.create(
        model=judge2.MODEL, max_tokens=4096, system=SYSTEM,
        tools=[TOOL], tool_choice={"type": "tool", "name": "judge_aliases"},
        messages=[{"role": "user", "content": prompt_for(pairs)}]))
    tu = next((b for b in resp.content if getattr(b, "type", None) == "tool_use"), None)
    if tu is None:
        raise RuntimeError(f"no tool_use (stop={resp.stop_reason})")
    out = {}
    for v in tu.input["verdicts"]:
        c = float(v["confidence"])
        if not 0.0 <= c <= 1.0:
            raise RuntimeError(f"confidence out of range: {v}")
        out[v["pair_ref"]] = {"confidence": c, "reason": v.get("reason", "")}
    if len(out) != len(pairs):
        raise RuntimeError(f"got {len(out)} verdicts for {len(pairs)} pairs")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    real = bijection_population()
    pop = real + CONSTRUCTED
    by_table: dict[str, list[dict]] = {}
    for p in pop:
        by_table.setdefault(p["table"], []).append(p)

    rt = sum(p["truth"] for p in real)
    print(f"POPULATION: {len(real)} real held-out bijections ({rt} alias, {len(real) - rt} coincidental)"
          f" + {len(CONSTRUCTED)} constructed = {len(pop)} pairs over {len(by_table)} tables\n")
    for t, ps in by_table.items():
        tt = sum(p["truth"] for p in ps)
        print(f"  {t:28} {len(ps):>2} pairs ({tt} alias / {len(ps) - tt} coincidental)")
    # is the adversarial pair present?
    p2 = [p for p in real if {p["a"], p["b"]} == {"p2series", "p2type"}]
    print(f"\n  adversarial p2series==p2type present: {'YES' if p2 else 'NO'}"
          + (f" (truth={'alias' if p2[0]['truth'] else 'coincidental'})" if p2 else ""))

    if args.dry:
        print("\n" + "=" * 78 + "\nTWO RENDERED PROMPTS (system elided) — ZERO LLM CALLS\n" + "=" * 78)
        for t in list(by_table)[:2]:
            print(f"\n--- table={t} ---\n{prompt_for(by_table[t])}")
        print(f"\n(system prompt: {len(SYSTEM)} chars from {PROMPT_PATH.name}; temp={TEMP}; "
              f"tool=judge_aliases confidence-only)")
        return

    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    client = anthropic.Anthropic(api_key=judge2.load_key())
    calls, t0 = 0, time.time()
    for t, ps in by_table.items():
        todo = [p for p in ps if ref_of(p) not in cache]
        if not todo:
            continue
        res = ask_batch(client, todo)
        with WAL.open("a") as wal:
            for p in todo:
                r = res[ref_of(p)]
                rec = {"ref": ref_of(p), "table": t, "a": p["a"], "b": p["b"],
                       "truth": p["truth"], "card": p["card"], **r}
                cache[ref_of(p)] = rec
                wal.write(json.dumps(rec) + "\n")
        CACHE.write_text(json.dumps(cache, indent=1))
        calls += 1
        print(f"  {t}: {len(todo)} pairs judged (call {calls})")
        if args.smoke:
            break
    print(f"\n{len(cache)} cached in {calls} calls ({time.time() - t0:.0f}s) → {CACHE.name}")


if __name__ == "__main__":
    main()
