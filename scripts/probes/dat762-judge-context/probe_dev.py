"""DAT-762 judge-context spike — the DEV leg (protocol: PROTOCOL.md, frozen).

Runs the four core arms (N / V / VR / VH) over the frozen DAT-757 cell inventory,
3 repetitions per cell per arm, and reports the pre-registered dev gates.

Nothing here defines evidence: the arms come from `channels.py`, the cells and the
statistic/scoring definitions from the frozen DAT-757 instrument. This file only
calls, caches, scores and reports.

    uv run --with anthropic python -u scripts/probes/dat762-judge-context/probe_dev.py
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from channels import ARMS, CORE_ARMS, SYSTEM, hypothesis_block, pair_facts  # noqa: E402  — arms; also sets up sys.path
from cells import CELLS, Cell  # noqa: E402  — frozen inventory
from probe_ablation import c1_verdict, correct, load_all, load_key  # noqa: E402  — frozen instrument

MODEL = "claude-sonnet-5"
MAX_TOKENS = 400
RESULTS = HERE / "results_dev.json"
REPORT = HERE / "RESULTS_DEV.md"
OLD_RESULTS = HERE.parents[0] / "dat757-channel-ablation" / "results.json"
REPS = (1, 2, 3)
VERDICTS = ("MERGE", "HIERARCHY", "ROLE", "REJECT")

# pre-registered gate sets (PROTOCOL.md "Dev gate")
VETO_KLASSES = ("D-quasi-identifier", "E-free-text", "P-proxy-bijection")
STATS_KLASSES = ("F-dirty-hierarchy", "H-weak-true", "J-true-fk")

_LINES: list[str] = []


def emit(s: str = "") -> None:
    print(s)
    _LINES.append(s)


# --------------------------------------------------------------------------- #
# the judge — probe_ablation.ask's robustness, one schema field wider          #
# --------------------------------------------------------------------------- #
def ask(client, user_msg: str) -> dict:
    for attempt in range(4):
        try:
            # Claude 5 rejects `temperature` (400: deprecated) — model-default
            # sampling; instability is measured by the repetition, not suppressed.
            resp = client.messages.create(
                model=MODEL, max_tokens=MAX_TOKENS,
                system=SYSTEM, messages=[{"role": "user", "content": user_msg}],
            )
            # BUG FIX (noted in the report): probe_ablation.ask assumes content[0] is
            # the text block. claude-sonnet-5 sporadically emits a ThinkingBlock first
            # at model-default sampling, which raised AttributeError -> all 4 retries
            # failed -> an "ERROR" verdict was CACHED and would have scored as a silent
            # miss. Take the first text block, and record whether the model thought.
            blocks = [c for c in resp.content if getattr(c, "type", None) == "text"]
            if not blocks:
                raise ValueError(f"no text block: {[getattr(c, 'type', '?') for c in resp.content]}")
            thought = any(getattr(c, "type", None) == "thinking" for c in resp.content)
            txt = blocks[0].text.strip()
            if txt.startswith("```"):
                txt = txt.strip("`").removeprefix("json").strip()
            out = json.loads(txt)
            assert out.get("verdict") in VERDICTS
            out["_thinking"] = thought  # measured, not requested — see report
            return out  # confidence stored as returned; only verdict is validated
        except Exception as e:  # noqa: BLE001 — retry API/parse hiccups, then surface
            if attempt == 3:
                return {"verdict": "ERROR", "direction": None, "confidence": None,
                        "reason": str(e)[:200]}
            time.sleep(3 * (attempt + 1))
    return {"verdict": "ERROR", "direction": None, "confidence": None, "reason": "unreachable"}


# --------------------------------------------------------------------------- #
# scoring helpers                                                              #
# --------------------------------------------------------------------------- #
def ok(cell: Cell, r: dict, strict: bool = True) -> bool:
    return correct(cell, r["verdict"], r.get("direction"), strict)


def score(cells: list[Cell], res: dict, arm: str, rep: int, strict: bool) -> int:
    return sum(ok(c, res[(c.id, arm, rep)], strict) for c in cells)


def rng_fresh() -> np.random.Generator:
    # fresh per call: profile samples identical across arms for the same cell,
    # so arms differ only in framing, never in which rows they saw.
    return np.random.default_rng(762)


def dist(verds: list[str]) -> str:
    c = Counter(verds)
    return ",".join(f"{v}x{n}" for v, n in c.most_common())


def modal_conf(res: dict, cid: str, arm: str) -> str:
    c = Counter(str(res[(cid, arm, r)].get("confidence") or "?") for r in REPS)
    return c.most_common(1)[0][0]


def band(cells: list[Cell], res: dict, arm: str, strict: bool = True) -> list[int]:
    return [score(cells, res, arm, r, strict) for r in REPS]


def cellfmt(cells: list[Cell], res: dict, arm: str) -> str:
    s = band(cells, res, arm, True)
    lx = band(cells, res, arm, False)
    out = f"{min(s)}-{max(s)} r1={s[0]}"
    if lx != s:
        out += f" ({min(lx)}-{max(lx)} r1={lx[0]})"
    return out


def c1fmt(cells: list[Cell], c1: dict) -> str:
    s = sum(correct(c, c1[c.id]["verdict"], c1[c.id].get("direction"), True) for c in cells)
    x = sum(correct(c, c1[c.id]["verdict"], c1[c.id].get("direction"), False) for c in cells)
    return f"{s}/{len(cells)}" + (f"({x})" if x != s else "")


def mean_strict(cells: list[Cell], res: dict, arm: str) -> float:
    return float(np.mean(band(cells, res, arm, True)))


# --------------------------------------------------------------------------- #
def main() -> None:
    print("# DAT-762 judge-context spike — dev leg\n\n## loading OBTs")
    data = load_all()
    cache = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}

    import anthropic  # noqa: PLC0415 (overlay dep)

    client = anthropic.Anthropic(api_key=load_key())

    # ---- collect: C1 (mechanical) + 4 arms x 3 reps (LLM, cached per call) ---
    print("\n## grading (cached calls are free; ~540 LLM calls cold)")
    res: dict[tuple[str, str, int], dict] = {}
    c1: dict[str, dict] = {}
    n_called = 0
    for cell in CELLS:
        reps = 2999 if cell.dataset == "rel-f1" else 999
        k1 = f"{cell.id}:C1"
        if k1 not in cache:
            v, d, why = c1_verdict(cell, data, reps)
            cache[k1] = {"verdict": v, "direction": d, "reason": why}
            RESULTS.write_text(json.dumps(cache, indent=1))
        c1[cell.id] = cache[k1]

        marks = []
        for arm in CORE_ARMS:
            for rep in REPS:
                k = f"{cell.id}:{arm}:r{rep}"
                # a cached transport/parse ERROR is never a verdict — always retried,
                # so a hiccup can't freeze into a score
                if k not in cache or cache[k].get("verdict") == "ERROR":
                    cache[k] = ask(client, ARMS[arm](cell, data, rng_fresh()))
                    RESULTS.write_text(json.dumps(cache, indent=1))  # resume-safe
                    n_called += 1
                res[(cell.id, arm, rep)] = cache[k]
            vs = [res[(cell.id, arm, r)]["verdict"] for r in REPS]
            marks.append(f"{arm}:{dist(vs)}")
        print(f"  {cell.id:3} [{cell.klass:18}] truth={cell.truth:9} "
              f"C1={c1[cell.id]['verdict']:9} | " + " | ".join(marks))
    print(f"\n  fresh LLM calls this run: {n_called}")

    errs = [(cid, a, r) for (cid, a, r), v in res.items() if v["verdict"] == "ERROR"]
    if errs:
        emit(f"> WARNING: {len(errs)} ERROR responses (excluded from nothing, scored as wrong): {errs}")

    klasses = sorted({c.klass for c in CELLS}, key=lambda k: k.split("-")[0])
    by_klass = {k: [c for c in CELLS if c.klass == k] for k in klasses}
    veto = [c for c in CELLS if c.klass in VETO_KLASSES or c.id == "G3"]
    stats_owned = [c for c in CELLS if c.klass in STATS_KLASSES]
    l_cells = by_klass["L-false-friend"]

    emit("# DAT-762 judge-context spike — dev leg results")
    emit()
    emit(f"Protocol: `PROTOCOL.md` (frozen). Judge `{MODEL}`, max_tokens={MAX_TOKENS}, "
         f"model-default sampling. {len(CELLS)} cells x {len(CORE_ARMS)} arms x {len(REPS)} reps "
         f"= {len(CELLS) * len(CORE_ARMS) * len(REPS)} gradings. C1 = mechanical stack v4 (no LLM).")
    emit()
    emit("Scoring: strict = verdict + direction (HIERARCHY truth is always `a->b`); "
         "lax = direction-insensitive. Ranges are min-max over the 3 reps; `r1` is the "
         "rep-1 point value (the grain the DAT-757 scorecard was measured at).")
    emit()
    emit("### Instrument notes (measured at pre-flight, before any LLM call; not fixed — "
         "the DAT-757 instrument is frozen and both artifacts hit every arm identically)")
    emit()
    emit("- **L3 (`number` vs `grid`)** renders `value_set_jaccard = 0.0` because `number` "
         "stringifies as float (\"6.0\") and `grid` as int (\"0\"), so the cell's "
         "\"overlapping integers\" premise is invisible to every judge. Pre-registered in "
         "PROTOCOL.md; scores reported, cell noted as compromised for class L.")
    emit("- **`col_profile` top-values tie-order is nondeterministic per render.** polars' "
         "`value_counts().sort(\"count\")` does not break ties stably, so each construction of "
         "the same arm can list equal-frequency values in a different order — and where the "
         "top-6 boundary falls inside a tie (near-key determinants: `raceId`, `SALESDOCUMENT`, "
         "`date`, `grid`), a different subset of tied values is shown. Verified at pre-flight: "
         "`random_samples` ARE identical across arms for every cell (the rng governs those, and "
         "it is constructed fresh per call), and n_rows/n_distinct/null_rate are identical; only "
         "the display order/membership of tied top-values moves. This is unbiased noise shared by "
         "V/VR/VH and by DAT-757's C3, not a systematic difference between arms — but it is a "
         "real contributor to the instability measured in section 4.")
    thk = {a: sum(1 for c in CELLS for r in REPS if res[(c.id, a, r)].get("_thinking"))
           for a in CORE_ARMS}
    measured = sum(1 for c in CELLS for a in CORE_ARMS for r in REPS
                   if "_thinking" in res[(c.id, a, r)])
    emit(f"- **The judge sometimes thinks unprompted.** `claude-sonnet-5` at model-default "
         f"sampling sporadically emits a `ThinkingBlock` before its text block, with no "
         f"thinking parameter requested. This surfaced as a bug: `probe_ablation.ask` reads "
         f"`content[0].text`, which raises on those responses — all 4 retries failed and an "
         f"`ERROR` verdict was cached, which would have scored as a silent miss (2 hits on "
         f"H2:V before the fix). `probe_dev.ask` now takes the first *text* block, never caches "
         f"an ERROR as a verdict, and records `_thinking`. Evidence, stated exactly: both cached "
         f"ERRORs exhausted all 4 retries and the final attempt of each raised the ThinkingBlock "
         f"error, so between 2 and 8 calls emitted a thinking block — all of them on the single "
         f"prompt H2:V, none anywhere else in 540 calls. The 2 post-fix re-calls of that same "
         f"prompt did NOT think (and returned ROLE x3 with the third rep — a stable verdict the "
         f"ERROR had been masking), so the behaviour is sporadic and time-clustered, not "
         f"prompt-determined. Spontaneous-thinking count per arm over the {measured} calls made "
         f"after the flag existed: {thk}. **This is a live confound for the protocol's VH-think "
         f"arm**, which assumes the core arms are non-thinking: they are almost always, but not "
         f"strictly, non-thinking, and the probe cannot certify which of the 538 pre-flag calls "
         f"thought.")

    # ---- 1. per-cell table -------------------------------------------------
    emit()
    emit("## 1. Per-cell verdicts (3-rep distribution; OK/MISS = rep-1 strict; conf = modal)")
    emit()
    emit("```")
    hdr = f"{'id':3} {'class':19} {'truth':9} {'C1':10}"
    for arm in CORE_ARMS:
        hdr += f" {arm + ' (3 reps)':34}"
    emit(hdr)
    for cell in CELLS:
        c1v = c1[cell.id]
        c1m = "OK" if correct(cell, c1v["verdict"], c1v.get("direction"), True) else c1v["verdict"][:6]
        line = f"{cell.id:3} {cell.klass:19} {cell.truth:9} {c1m:10}"
        for arm in CORE_ARMS:
            vs = [res[(cell.id, arm, r)]["verdict"] for r in REPS]
            m = "OK  " if ok(cell, res[(cell.id, arm, 1)]) else "MISS"
            line += f" {m} {dist(vs):20} {modal_conf(res, cell.id, arm):6}"
        emit(line)
    emit("```")

    # ---- 2. class x arm scorecard -----------------------------------------
    emit()
    emit("## 2. Class x arm scorecard (strict, range over reps; lax in parens where different)")
    emit()
    emit("```")
    emit(f"{'class':22} {'n':>2}  {'C1':>9}   " + "".join(f"{a:24}" for a in CORE_ARMS))
    for kl in klasses:
        sub = by_klass[kl]
        line = f"{kl:22} {len(sub):>2}  {c1fmt(sub, c1):>9}   "
        line += "".join(f"{cellfmt(sub, res, a):24}" for a in CORE_ARMS)
        emit(line)
    emit("")
    emit(f"{'VETO (D,E,P,G3)':22} {len(veto):>2}  {c1fmt(veto, c1):>9}   "
         + "".join(f"{cellfmt(veto, res, a):24}" for a in CORE_ARMS))
    emit(f"{'STATS-OWNED (F,H,J)':22} {len(stats_owned):>2}  {c1fmt(stats_owned, c1):>9}   "
         + "".join(f"{cellfmt(stats_owned, res, a):24}" for a in CORE_ARMS))
    emit("```")

    # ---- 3. overall --------------------------------------------------------
    emit()
    emit("## 3. Overall per arm (strict, all 45 cells)")
    emit()
    emit("```")
    emit(f"{'arm':5} {'rep1':>5} {'rep2':>5} {'rep3':>5}   {'range':>7} {'mean':>6}   {'lax mean':>8}")
    c1s = sum(correct(c, c1[c.id]["verdict"], c1[c.id].get("direction"), True) for c in CELLS)
    c1x = sum(correct(c, c1[c.id]["verdict"], c1[c.id].get("direction"), False) for c in CELLS)
    emit(f"{'C1':5} {c1s:>5} {'-':>5} {'-':>5}   {'-':>7} {c1s:>6} {c1x:>9}   (mechanical, deterministic)")
    for arm in CORE_ARMS:
        s = band(CELLS, res, arm, True)
        lx = band(CELLS, res, arm, False)
        emit(f"{arm:5} {s[0]:>5} {s[1]:>5} {s[2]:>5}   {min(s):>3}-{max(s):<3} "
             f"{np.mean(s):>6.1f} {np.mean(lx):>9.1f}")
    emit("```")

    # ---- 4. instability ----------------------------------------------------
    emit()
    emit("## 4. Instability (3 reps disagree) — reported, never majority-patched")
    emit()
    unstable = []
    for cell in CELLS:
        for arm in CORE_ARMS:
            vs = [res[(cell.id, arm, r)]["verdict"] for r in REPS]
            if len(set(vs)) > 1:
                unstable.append((cell.id, cell.klass, arm, dist(vs)))
    emit(f"{len(unstable)} of {len(CELLS) * len(CORE_ARMS)} (cell, arm) pairs are unstable "
         f"({100 * len(unstable) / (len(CELLS) * len(CORE_ARMS)):.0f}%).")
    emit()
    emit("```")
    for cid, kl, arm, d in unstable:
        emit(f"  {cid:3} [{kl:19}] {arm:3} -> {d}")
    per_arm = Counter(a for _, _, a, _ in unstable)
    emit("")
    emit("  per arm: " + ", ".join(f"{a}={per_arm.get(a, 0)}" for a in CORE_ARMS))
    emit("```")

    # ---- 5. Q1 — reproduction ---------------------------------------------
    emit()
    emit("## 5. Q1 — reproduction: N vs VR on class D (quasi-identifier)")
    emit()
    d_cells = by_klass["D-quasi-identifier"]
    emit("```")
    emit(f"  {'cell':4} {'truth':7} {'N (3 reps)':26} {'VR (3 reps)':26}")
    for c in d_cells:
        emit(f"  {c.id:4} {c.truth:7} "
             f"{dist([res[(c.id, 'N', r)]['verdict'] for r in REPS]):26} "
             f"{dist([res[(c.id, 'VR', r)]['verdict'] for r in REPS]):26}")
    emit("")
    for arm in CORE_ARMS:
        s = band(d_cells, res, arm, True)
        emit(f"  {arm:3} strict per rep {s} -> range {min(s)}-{max(s)}/4, mean {np.mean(s):.2f}")
    emit("```")

    if OLD_RESULTS.exists():
        old = json.loads(OLD_RESULTS.read_text())
        emit()
        emit("DAT-757 cached numbers for the same cells (read-only cross-reference; "
             "C2 == N surface, C3 == VR surface, different output schema, 2 reps):")
        emit()
        emit("```")
        emit(f"  {'cell':4} {'C2:r1':10} {'C2:r2':10} {'C3:r1':10} {'C3:r2':10}")
        for c in d_cells:
            vals = []
            for ch in ("C2", "C3"):
                for r in (1, 2):
                    e = old.get(f"{c.id}:{ch}:r{r}")
                    vals.append(e["verdict"] if e else "-")
            emit(f"  {c.id:4} " + " ".join(f"{v:10}" for v in vals))
        for ch, arm in (("C2", "N"), ("C3", "VR")):
            for r in (1, 2):
                got = [old.get(f"{c.id}:{ch}:r{r}") for c in d_cells]
                if all(got):
                    s = sum(correct(c, g["verdict"], g.get("direction"), True)
                            for c, g in zip(d_cells, got))
                    emit(f"  DAT-757 {ch} (={arm} surface) rep{r}: {s}/4 strict")
        emit("```")

    # ---- 6. Q2 — separation ------------------------------------------------
    emit()
    emit("## 6. Q2 — separation: N vs V (values, no stats) vs VR (values + raw stats)")
    emit()
    emit("```")
    emit(f"{'class':22} {'n':>2}  {'N mean':>7} {'V mean':>7} {'VR mean':>7}   "
         f"{'V-N':>6} {'VR-V':>6} {'VR-N':>6}")
    for kl in klasses + ["__ALL__"]:
        sub = CELLS if kl == "__ALL__" else by_klass[kl]
        mn, mv, mr = (mean_strict(sub, res, a) for a in ("N", "V", "VR"))
        emit(f"{kl:22} {len(sub):>2}  {mn:>7.2f} {mv:>7.2f} {mr:>7.2f}   "
             f"{mv - mn:>+6.2f} {mr - mv:>+6.2f} {mr - mn:>+6.2f}")
    emit("```")

    # ---- 7. Q3 — presentation ---------------------------------------------
    emit()
    emit("## 7. Q3 — presentation: VR vs VH (identical numbers, different framing)")
    emit()
    emit("```")
    emit(f"{'class':22} {'n':>2}  {'VR mean':>8} {'VH mean':>8}   {'VH-VR':>7}")
    for kl in klasses + ["__ALL__"]:
        sub = CELLS if kl == "__ALL__" else by_klass[kl]
        mr, mh = mean_strict(sub, res, "VR"), mean_strict(sub, res, "VH")
        emit(f"{kl:22} {len(sub):>2}  {mr:>8.2f} {mh:>8.2f}   {mh - mr:>+7.2f}")
    emit("```")

    # ---- 8. Q4 — the router's job -----------------------------------------
    emit()
    emit("## 8. Q4 — the router's job: stats-owned classes F, H, J")
    emit()
    n_so = len(stats_owned)
    emit("```")
    emit(f"{'arm':5} {'rep1':>5} {'rep2':>5} {'rep3':>5}  {'range':>7} {'mean':>6} {'mean frac':>10}  G-D2 (>=0.8)")
    c1_so = sum(correct(c, c1[c.id]["verdict"], c1[c.id].get("direction"), True) for c in stats_owned)
    emit(f"{'C1':5} {c1_so:>5} {'-':>5} {'-':>5}  {'-':>7} {c1_so:>6} {c1_so / n_so:>10.2f}  "
         f"{'PASS' if c1_so / n_so >= 0.8 else 'FAIL'} (reference, not an arm)")
    for arm in CORE_ARMS:
        s = band(stats_owned, res, arm, True)
        m = float(np.mean(s))
        emit(f"{arm:5} {s[0]:>5} {s[1]:>5} {s[2]:>5}  {min(s):>3}-{max(s):<3} {m:>6.2f} "
             f"{m / n_so:>10.2f}  {'PASS' if m / n_so >= 0.8 else 'FAIL'}"
             f"  (per-rep frac {min(s) / n_so:.2f}-{max(s) / n_so:.2f})")
    emit("")
    for kl in STATS_KLASSES:
        sub = by_klass[kl]
        emit(f"  {kl:22} n={len(sub)}  " + "  ".join(
            f"{a}={mean_strict(sub, res, a):.2f}" for a in CORE_ARMS))
    emit("```")

    # ---- 9. pre-registered dev gates --------------------------------------
    emit()
    emit("## 9. Pre-registered dev gates")
    emit()
    best = max(CORE_ARMS, key=lambda a: mean_strict(CELLS, res, a))
    emit(f"**Best arm by overall strict mean: `{best}` "
         f"({mean_strict(CELLS, res, best):.1f}/{len(CELLS)}).** Gates are evaluated for every "
         f"arm below so the pick is auditable; the protocol's gate applies to the best arm.")
    emit()
    n_mean = mean_strict(veto, res, "N")
    emit("```")
    emit(f"{'arm':5} {'G-D1 veto (D,E,P,G3), n=9':32} {'G-D2 F,H,J >=0.8':26} {'G-D3 false MERGE on L':24}")
    gate_pass = {}
    for arm in CORE_ARMS:
        v = band(veto, res, arm, True)
        vm = float(np.mean(v))
        g1 = vm >= n_mean
        so = float(np.mean(band(stats_owned, res, arm, True)))
        g2 = so / n_so >= 0.8
        fm = [(c.id, r) for c in l_cells for r in REPS if res[(c.id, arm, r)]["verdict"] == "MERGE"]
        g3 = len(fm) == 0
        gate_pass[arm] = (g1, g2, g3)
        emit(f"{arm:5} {f'{vm:.2f} vs N {n_mean:.2f} ({min(v)}-{max(v)}) ' + ('PASS' if g1 else 'FAIL'):32} "
             f"{f'{so:.2f}/{n_so} = {so / n_so:.2f} ' + ('PASS' if g2 else 'FAIL'):26} "
             f"{f'{len(fm)} false MERGE ' + ('PASS' if g3 else 'FAIL'):24}")
    emit("```")
    emit()
    for arm in CORE_ARMS:
        g1, g2, g3 = gate_pass[arm]
        emit(f"- **{arm}**: G-D1 {'PASS' if g1 else 'FAIL'} | G-D2 {'PASS' if g2 else 'FAIL'} "
             f"| G-D3 {'PASS' if g3 else 'FAIL'}"
             + ("  <- clears all three" if all((g1, g2, g3)) else ""))
    clears = [a for a in CORE_ARMS if all(gate_pass[a])]
    emit()
    emit(f"**Arms clearing all three gates: {clears if clears else 'NONE'}**")
    emit(f"G-D1 note: N (names-only) is the baseline, veto mean {n_mean:.2f}/{len(veto)}; "
         f"'>= N' is evaluated on the 3-rep mean, with the per-rep range shown.")

    # ---- 10. misgrades -----------------------------------------------------
    emit()
    emit("## 10. Misgrades (rep 1, strict) — the qualitative evidence")
    emit()
    for arm in dict.fromkeys([best, "N"]):
        emit(f"### arm {arm}")
        emit("```")
        n_miss = 0
        for cell in CELLS:
            r = res[(cell.id, arm, 1)]
            if not ok(cell, r):
                n_miss += 1
                got = r["verdict"] + (f"/{r.get('direction')}" if r.get("direction") else "")
                emit(f"  {cell.id:3} [{cell.klass:19}] got {got:16} want {cell.truth:9} "
                     f"conf={str(r.get('confidence')):6}")
                emit(f"      {r.get('reason', '')[:150]}")
        emit(f"  -- {n_miss} misgrades / {len(CELLS)} cells")
        emit("```")

    # ---- 11. failure attribution: which VH frame did each cell render? ------
    # Classified by calling the frozen hypothesis_block itself (no logic copied).
    emit()
    emit("## 11. Failure attribution — VH score by the frame the cell actually rendered")
    emit()
    emit("Not pre-registered; computed after the fact from `channels.hypothesis_block` to "
         "locate *where* VH fails. Reported as a mechanism, not as a gate.")
    emit()
    frame_of: dict[str, str] = {}
    for cell in CELLS:
        if cell.dataset.startswith("constructed"):
            frame_of[cell.id] = "no joint stats (K)"
            continue
        obt, _, scan = data[cell.dataset]
        blk = hypothesis_block(pair_facts(scan, obt, cell.a, cell.b), cell.a, cell.b)
        if "determine EACH OTHER" in blk:
            f = "frame_bidirectional"
        elif "no determination in either direction" in blk:
            f = "frame_no_finding"
        else:
            f = "frame_determination"
        frame_of[cell.id] = f
    emit("```")
    emit(f"{'rendered frame':24} {'n':>2}   {'N':>6} {'VR':>6} {'VH':>6}   VH frac")
    for fr in ("frame_determination", "frame_bidirectional", "frame_no_finding", "no joint stats (K)"):
        sub = [c for c in CELLS if frame_of[c.id] == fr]
        if not sub:
            continue
        vals = {a: mean_strict(sub, res, a) for a in ("N", "VR", "VH")}
        emit(f"{fr:24} {len(sub):>2}   " + " ".join(f"{vals[a]:6.2f}" for a in ("N", "VR", "VH"))
             + f"   {vals['VH'] / len(sub):.2f}")
        miss = [c.id for c in sub if mean_strict([c], res, "VH") < 1]
        if miss:
            emit(f"    VH misses: {miss}")
    emit("```")
    emit()
    emit("`frame_determination` offers four origins (real hierarchy / near-key artifact / "
         "vacuous skew / proxy determinant) — a menu that spans the truth space — and VH is "
         "perfect on every cell that renders it. `frame_bidirectional` offers three (two "
         "encodings of one identity / two concepts in lockstep / a copied value), all of which "
         "read the pair as one-thing-or-nothing: it contains **no 'real attribute edge' option** "
         "(class P's truth) and **no 'the statistic is vacuous on a degenerate domain' option** "
         "(L2's truth). Every VH miss with joint statistics (P1, P2, L2) renders that one frame, "
         "and both VH gate failures (G-D1 via P1, G-D3 via L2) trace to it.")

    # ---- 12. confidence calibration ----------------------------------------
    emit()
    emit("## 12. Confidence — is abstention measurable?")
    emit()
    tab = Counter()
    for cell in CELLS:
        for arm in CORE_ARMS:
            for r in REPS:
                e = res[(cell.id, arm, r)]
                tab[(str(e.get("confidence")), ok(cell, e))] += 1
    emit("```")
    emit(f"{'confidence':12} {'n':>4} {'correct':>8} {'wrong':>6} {'accuracy':>9}")
    for cf in ("high", "medium", "low", "None"):
        g, b = tab[(cf, True)], tab[(cf, False)]
        if g + b:
            emit(f"{cf:12} {g + b:>4} {g:>8} {b:>6} {g / (g + b):>9.2f}")
    vh_hi = sum(1 for cell in CELLS for r in REPS
                if not ok(cell, res[(cell.id, 'VH', r)])
                and res[(cell.id, 'VH', r)].get("confidence") == "high")
    vh_miss = sum(1 for cell in CELLS for r in REPS if not ok(cell, res[(cell.id, 'VH', r)]))
    emit("")
    emit(f"  VH misgrades stated at confidence=high: {vh_hi}/{vh_miss}")
    emit("```")
    emit()
    emit("Across all arms the field is directionally calibrated (high 0.83 > medium 0.45 > low "
         "0.00), so it carries real signal in aggregate. **But on the best arm it is useless as "
         "an abstain trigger: VH is high-confidence on every single one of its errors.** An "
         "abstain posture built on this field would abstain on none of VH's misgrades. The "
         "protocol asked whether abstention is measurable rather than bolted on later — measured, "
         "and for VH the answer is no.")

    REPORT.write_text("\n".join(_LINES) + "\n")
    print(f"\n\nwrote {REPORT}")


if __name__ == "__main__":
    main()
