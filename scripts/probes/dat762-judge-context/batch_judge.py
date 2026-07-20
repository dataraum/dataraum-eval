"""Batched judge + continuous confidence [0,1], matching the engine convention
(column_annotation.yaml: one call per table, confidence is a float with bands).

Validates two things Philipp asked, cheaply (~15 calls, not 289):
 1. does batching hold the per-pair 0.81/0.98?
 2. does a continuous confidence flag calibrate — P(correct) rising with it?

Near-key% screen applied first (engine's NEAR_KEY_FRAC=0.9 + min-row guard), so
the judge only sees the 289 survivors, batched per table in chunks of 25.
"""
from __future__ import annotations
import json, sys, time
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import anthropic  # noqa: E402


def _retry(fn, tries=6):
    """Backoff on transient API errors (529 overloaded, rate limits). Never
    cache a failure — raise only after exhausting retries so the caller stops."""
    for k in range(tries):
        try:
            return fn()
        except (anthropic.InternalServerError, anthropic.RateLimitError,
                anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            if k == tries - 1:
                raise
            wait = min(2 ** k, 30)
            print(f"  transient {type(e).__name__}, retry {k+1}/{tries} in {wait}s")
            time.sleep(wait)
import judge2, rwd  # noqa: E402

CACHE = Path(__file__).parent / "results_batch.json"
CHUNK = 12
MAX_TOKENS = 8192
NEAR_KEY_FRAC, MIN_ROWS_NEARKEY, MIN_DISTINCT_DET = 0.9, 10, 3

SYSTEM = """You decide, for each candidate, whether a functional dependency is a \
MEANINGFUL dimension relationship — a real rule about what these columns are \
(a dimension and its attribute, a code and its name, a hierarchy level) — or a \
coincidence that holds only on the rows in front of you (a near-unique column \
determining everything trivially, a near-constant target, too few rows to break \
it).

Every candidate A -> B already holds EXACTLY in the data. That is the premise, \
not the question. The question is whether it MEANS something.

For each candidate return a confidence in [0.0, 1.0] — the house convention:
 - 0.85-1.0  decisive: the columns' meaning and values make it clearly a real
   dimension relationship (or clearly not).
 - 0.5-0.8   probable but not certain from the evidence shown.
 - 0.2-0.4   you are guessing; the evidence does not distinguish the cases.
Downstream systems gate on this number — act on high, surface the rest to the \
user. A confident-looking call on thin evidence is worse than an honest low one.

Answer with ONLY a JSON array, one object per candidate, in the given order:
[{"i": <index>, "meaningful": true|false, "confidence": <float>, "reason": "<one sentence>"}]"""


def col_line(f, role, name):
    p = f.a if role == "A" else f.b
    vals = ", ".join(f"`{v}`" for v in p.samples)
    return (f"    {role} `{name}`: {p.distinct:,} distinct / {p.non_null:,} rows, "
            f"top value {p.majority_share:.0%}, e.g. {vals}")


def batch_prompt(table, pairs):
    df = rwd.load_table(table)
    head = (f"Table `{table.split('.')[0]}` — columns: "
            f"{', '.join('`'+c+'`' for c in df.columns)}\n"
            f"{df.height:,} rows.\n\nCandidates:\n")
    body = []
    for i, c in enumerate(pairs):
        f = judge2.facts(table, c["lhs"], c["rhs"])
        body.append(f"[{i}] `{c['lhs']}` -> `{c['rhs']}` holds exactly.\n"
                    f"{col_line(f,'A',c['lhs'])}\n{col_line(f,'B',c['rhs'])}")
    return head + "\n".join(body)


def ask_batch(client, table, pairs):
    resp = _retry(lambda: client.messages.create(
        model=judge2.MODEL, max_tokens=MAX_TOKENS, system=SYSTEM,
        messages=[{"role": "user", "content": batch_prompt(table, pairs)}]))
    text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), None)
    if text is None:
        raise RuntimeError(
            f"no text block (stop_reason={resp.stop_reason}, "
            f"blocks={[b.type for b in resp.content]}) — chunk={len(pairs)} likely too big")
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].removeprefix("json").strip()
    arr = json.loads(raw)
    out = {}
    for o in arr:
        if not isinstance(o.get("meaningful"), bool) or not (0 <= float(o["confidence"]) <= 1):
            raise RuntimeError(f"bad item: {o}")
        out[int(o["i"])] = {"meaningful": o["meaningful"], "confidence": float(o["confidence"])}
    if len(out) != len(pairs):
        raise RuntimeError(f"got {len(out)} verdicts for {len(pairs)} pairs")
    return out


def surviving(cands):
    keep = []
    for c in cands:
        df = rwd.load_table(c["table"])
        p = judge2._profile(judge2._blank_sentinels(df.select([c["lhs"]]), [c["lhs"]]), c["lhs"])
        d, n = p.distinct, p.non_null
        if d < MIN_DISTINCT_DET: continue
        if n >= MIN_ROWS_NEARKEY and d >= NEAR_KEY_FRAC * n: continue
        keep.append(c)
    return keep


def main():
    cands = surviving(rwd.exact_candidates())
    by_t = defaultdict(list)
    for c in cands: by_t[c["table"]].append(c)
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    client = anthropic.Anthropic(api_key=judge2.load_key())
    calls = 0; t0 = time.time()
    for t, pairs in by_t.items():
        for s in range(0, len(pairs), CHUNK):
            chunk = pairs[s:s+CHUNK]
            ck = f"{t}#{s}"
            if ck in cache: continue
            res = ask_batch(client, t, chunk)
            cache[ck] = {f"{c['lhs']}->{c['rhs']}": res[i] for i, c in enumerate(chunk)}
            CACHE.write_text(json.dumps(cache, indent=1))
            calls += 1
    print(f"{len(cands)} pairs judged in {calls} batched calls ({time.time()-t0:.0f}s)\n")

    # grade
    verd = {}
    for t, pairs in by_t.items():
        for s in range(0, len(pairs), CHUNK):
            ck = f"{t}#{s}"
            for c in pairs[s:s+CHUNK]:
                verd[(t, c["lhs"], c["rhs"])] = cache[ck][f"{c['lhs']}->{c['rhs']}"]
    n_real = sum(c["meaningful"] for c in cands)
    acc = [c for c in cands if verd[(c["table"],c["lhs"],c["rhs"])]["meaningful"]]
    sr = sum(c["meaningful"] for c in acc)
    print(f"batched accept-all-meaningful: precision {sr/len(acc):.3f}  recall {sr/n_real:.3f}  "
          f"(per-pair baseline was 0.81/0.98)")
    print("\nCONFIDENCE CURVE — act only on meaningful calls with confidence >= X:")
    print(f"  {'X':>5} {'asserted':>8} {'precision':>9} {'recall':>7}")
    for X in (0.0, 0.5, 0.6, 0.7, 0.8, 0.9):
        act = [c for c in acc if verd[(c["table"],c["lhs"],c["rhs"])]["confidence"] >= X]
        if not act: continue
        s = sum(c["meaningful"] for c in act)
        print(f"  {X:>5.2f} {len(act):>8} {s/len(act):>9.3f} {s/n_real:>7.3f}")
    print("\nCALIBRATION — P(correct) by confidence bucket (all judged pairs):")
    buck = defaultdict(lambda: [0,0])
    for c in cands:
        v = verd[(c["table"],c["lhs"],c["rhs"])]
        correct = (v["meaningful"] == c["meaningful"])
        b = min(int(v["confidence"]*5)/5, 0.8)
        buck[b][0]+=correct; buck[b][1]+=1
    for b in sorted(buck):
        ok,tot = buck[b]
        print(f"  conf [{b:.1f},{b+0.2:.1f}): {ok}/{tot} correct = {ok/tot:.2f}")


if __name__ == "__main__":
    main()
