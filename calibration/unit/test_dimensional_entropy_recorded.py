"""Tier-2 grounding for dimensional_entropy → normalized mutual information (DAT-442, #19).

dimensional_entropy currently scores by COUNTING heuristic patterns (mutual
exclusivity, conditional dependency, correlated variance…) and weighting them
(0.8·mutex + 0.6·conditional + …) through a magic log2(1+x)/3.5 — ungrounded. The
grounded replacement is **normalized mutual information**: NMI(X;Y) measures how
much knowing one column reduces uncertainty about another, on a clean 0–1 scale.

This RECORDS, in ms against the frozen fixture, whether NMI is the right statistic
BEFORE the rewrite: it must read ≈1 on a real cross-column dependency (the
journal_lines debit/credit double-entry mutex) and ≈0 on independent pairs. If it
separates cleanly, the redesign is greenlit; the score then represents an
*undocumented* dependency and a teach (document_business_rule) closes it — the
teach-closure bar, not recall (dimensional_entropy measures intrinsic structure,
not injected corruption: the mutex is real in clean data too).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Hashable, Sequence

from calibration.unit.fixture import load_fixture, row_records


def _nmi(x: Sequence[Hashable], y: Sequence[Hashable]) -> float:
    """Normalized mutual information NMI(X;Y) = MI / sqrt(H(X)·H(Y)), in [0, 1].

    1.0 = one column perfectly determines the other; 0.0 = independent. Pure
    contingency-table estimate over aligned label sequences (no discretization
    needed for indicators / categoricals).
    """
    n = len(x)
    if n == 0:
        return 0.0
    px, py, pxy = Counter(x), Counter(y), Counter(zip(x, y, strict=True))
    hx = -sum((c / n) * math.log2(c / n) for c in px.values())
    hy = -sum((c / n) * math.log2(c / n) for c in py.values())
    if hx == 0.0 or hy == 0.0:
        return 0.0  # a constant column carries no information to share
    mi = sum(
        (c / n) * math.log2((c / n) / ((px[a] / n) * (py[b] / n))) for (a, b), c in pxy.items()
    )
    return max(0.0, mi / math.sqrt(hx * hy))


def _nonzero_indicator(rows: list[dict[str, str]], col: str) -> list[int]:
    """1 where the numeric column is non-zero, else 0 (the mutex carrier)."""
    out: list[int] = []
    for r in rows:
        raw = r.get(col)
        if raw is None or raw == "":
            out.append(0)
            continue
        try:
            out.append(1 if float(raw) != 0.0 else 0)
        except (TypeError, ValueError):
            out.append(0)
    return out


def test_nmi_captures_the_debit_credit_mutex() -> None:
    """The real double-entry rule: each journal line is a debit XOR a credit, so the
    non-zero indicators are perfectly dependent → NMI ≈ 1.0 (vs the heuristic's
    arbitrary 0.8 weight)."""
    conn = load_fixture()
    rows = row_records(conn, "detection-v1", "journal_lines")
    conn.close()
    debit_ind = _nonzero_indicator(rows, "debit")
    credit_ind = _nonzero_indicator(rows, "credit")
    nmi = _nmi(debit_ind, credit_ind)
    assert nmi > 0.9, (
        f"NMI(debit≠0; credit≠0) = {nmi:.4f} — expected ≈1.0 for the double-entry mutex; "
        f"NMI does not capture the real cross-column dependency"
    )


def test_nmi_separates_independent_pairs() -> None:
    """Independent slice keys (currency, cost_center) carry little mutual information
    → low NMI. NMI must SEPARATE real dependency (≈1) from independence (≈0), else
    it can't ground the score."""
    conn = load_fixture()
    rows = row_records(conn, "detection-v1", "journal_lines")
    conn.close()
    currency = [r.get("currency", "") for r in rows]
    cost_center = [r.get("cost_center", "") for r in rows]
    nmi = _nmi(currency, cost_center)
    assert nmi < 0.3, (
        f"NMI(currency; cost_center) = {nmi:.4f} — expected low for ~independent slice "
        f"keys; if this is high, NMI over-reports dependency on real categorical structure"
    )


def test_mutex_separates_from_independence_with_margin() -> None:
    """The decisive grounding: the mutex NMI sits a clear margin above an independent
    pair's NMI — the clean separation a grounded score needs."""
    conn = load_fixture()
    rows = row_records(conn, "detection-v1", "journal_lines")
    conn.close()
    mutex = _nmi(_nonzero_indicator(rows, "debit"), _nonzero_indicator(rows, "credit"))
    independent = _nmi(
        [r.get("currency", "") for r in rows], [r.get("cost_center", "") for r in rows]
    )
    assert mutex - independent > 0.5, (
        f"mutex NMI {mutex:.4f} vs independent NMI {independent:.4f} "
        f"(margin {mutex - independent:+.4f}) — NMI must separate real dependency from noise"
    )
