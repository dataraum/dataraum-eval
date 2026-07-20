"""DAT-762 attempt 2 — the billed run. 390 x {V, VH} x 3 = 2,340 calls.

THIS SPENDS REAL MONEY. Every response is cached to disk the moment it lands.

Three rules this file exists to enforce, each a defect of attempt 1:

1. NEVER CACHE AN ERROR AS A VERDICT. Attempt 1 cached an exception as a verdict
   and it scored as a silent miss against one arm. Here a failure retries, then
   records an explicit {"error": ...} marker. Grading EXCLUDES markers and COUNTS
   them; the count is reported.

2. ONE facts() CALL PER CANDIDATE, SHARED BY BOTH ARMS. Not two calls that ought
   to agree — one object, rendered twice. Any V/VH difference is presentation by
   construction, not by assertion.

3. RESUME, NEVER RE-PAY. Every result is appended to a JSONL write-ahead log and
   flushed immediately; results_rwd.json is materialised from it. A restart skips
   every key already present.

Usage:
    python run_rwd.py --smoke 2      # 8 calls, inspect the wire, spend ~$0.05
    python run_rwd.py                # the full 2,340
    python run_rwd.py --retry-errors # re-attempt ONLY cached error markers
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import anthropic  # noqa: E402

import judge2  # noqa: E402
import rwd  # noqa: E402

HERE = Path(__file__).parent
CACHE_JSON = HERE / "results_rwd.json"
CACHE_WAL = HERE / "results_rwd.jsonl"

REPS = 3
ARMS = ("V", "VH")
MAX_ATTEMPTS = 4

_write_lock = threading.Lock()
_wal_fh = None


def key_of(table: str, lhs: str, rhs: str, arm: str, rep: int) -> str:
    return f"{table}:{lhs}:{rhs}:{arm}:{rep}"


# ------------------------------------------------------------------ cache


def load_cache() -> dict[str, dict]:
    """Merge the materialised JSON and the write-ahead log. WAL wins."""
    out: dict[str, dict] = {}
    if CACHE_JSON.exists():
        out.update(json.loads(CACHE_JSON.read_text()))
    if CACHE_WAL.exists():
        for line in CACHE_WAL.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # torn final line from a hard kill; the rest is good
            out[rec["key"]] = rec
    return out


def append_wal(rec: dict) -> None:
    """Durable write BEFORE anything else happens to the response."""
    global _wal_fh
    with _write_lock:
        if _wal_fh is None:
            _wal_fh = CACHE_WAL.open("a")
        _wal_fh.write(json.dumps(rec) + "\n")
        _wal_fh.flush()


def materialise(cache: dict[str, dict]) -> None:
    tmp = CACHE_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cache, indent=1, sort_keys=True))
    tmp.replace(CACHE_JSON)


# ------------------------------------------------------------------ one call


def grade_one(client, f, c: dict, arm: str, rep: int) -> dict:
    """One billed call. Returns a verdict record or an explicit error marker.

    Retries transient failures. A response that lands but cannot be parsed is
    also retried (max_tokens=400 with Sonnet-5's adaptive thinking on by default
    can truncate) — but if it never parses, it becomes an error marker, never a
    verdict.
    """
    prompt = judge2.ARMS[arm](f)
    base = {
        "key": key_of(c["table"], c["lhs"], c["rhs"], arm, rep),
        "table": c["table"],
        "lhs": c["lhs"],
        "rhs": c["rhs"],
        "arm": arm,
        "rep": rep,
    }

    last = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            out = judge2.ask(client, prompt)
            return {
                **base,
                "meaningful": out["meaningful"],
                "confidence": out["confidence"],
                "reason": out.get("reason", ""),
            }
        except (
            anthropic.RateLimitError,
            anthropic.APIStatusError,
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
        ) as exc:
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(min(2**attempt + random.uniform(0, 1), 30))
        except Exception as exc:  # noqa: BLE001 — parse/shape failures
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(1 + random.uniform(0, 1))

    # Exhausted. An explicit marker — grading excludes and counts these.
    return {**base, "error": last}


# ------------------------------------------------------------------ run


def build_worklist(cands: list[dict]) -> list[tuple[dict, str, int]]:
    work = []
    for c in cands:
        for arm in ARMS:
            for rep in range(REPS):
                work.append((c, arm, rep))
    return work


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", type=int, default=0, help="N candidates only, verbose")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--retry-errors", action="store_true")
    args = ap.parse_args()

    cands = rwd.exact_candidates()
    if args.smoke:
        cands = random.Random(762).sample(cands, args.smoke)

    cache = load_cache()
    print(f"cache: {len(cache)} records ({sum('error' in r for r in cache.values())} errors)")

    if args.retry_errors:
        for k in [k for k, r in cache.items() if "error" in r]:
            del cache[k]
        print(f"retry-errors: cleared markers, {len(cache)} kept")

    work = build_worklist(cands)
    todo = [(c, a, r) for c, a, r in work if key_of(c["table"], c["lhs"], c["rhs"], a, r) not in cache]
    print(f"candidates: {len(cands)}  calls: {len(work)}  todo: {len(todo)}  cached: {len(work) - len(todo)}")
    if not todo:
        materialise(cache)
        print("nothing to do.")
        return

    # ONE facts() per candidate, shared by both arms and all reps.
    print("profiling candidates (one facts() each, shared by V and VH)...")
    t0 = time.time()
    facts_by = {}
    for c in cands:
        facts_by[(c["table"], c["lhs"], c["rhs"])] = judge2.facts(c["table"], c["lhs"], c["rhs"])
    print(f"  {len(facts_by)} profiled in {time.time() - t0:.1f}s")

    client = anthropic.Anthropic(api_key=judge2.load_key())
    print(f"model: {judge2.MODEL}  max_tokens: {judge2.MAX_TOKENS}  workers: {args.workers}")

    done = 0
    errors = 0
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {
            pool.submit(grade_one, client, facts_by[(c["table"], c["lhs"], c["rhs"])], c, a, r): (c, a, r)
            for c, a, r in todo
        }
        for fut in as_completed(futs):
            rec = fut.result()
            append_wal(rec)  # durable BEFORE we touch it
            cache[rec["key"]] = rec
            done += 1
            if "error" in rec:
                errors += 1
                print(f"  ERROR {rec['key']}: {rec['error'][:120]}")
            if args.smoke:
                print(f"  {rec['key']}\n    {json.dumps({k: v for k, v in rec.items() if k not in ('key', 'table', 'lhs', 'rhs')})}")
            if done % 50 == 0 or done == len(todo):
                rate = done / (time.time() - t0)
                eta = (len(todo) - done) / rate / 60 if rate else 0
                print(
                    f"  {done}/{len(todo)}  {rate * 60:.0f}/min  eta {eta:.1f}min  errors {errors}",
                    flush=True,
                )
            if done % 100 == 0:
                materialise(cache)

    materialise(cache)
    print(f"\ndone. {done} calls, {errors} errors. cache: {len(cache)} records -> {CACHE_JSON.name}")


if __name__ == "__main__":
    main()
