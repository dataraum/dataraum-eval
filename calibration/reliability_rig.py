"""Witness reliability rig — measure r_i from the generative families (DAT-450).

ADR-0009 source #1: reliabilities are "shipped priors from the eval corpus — run
each witness over the generative injection families, measure agreement with ground
truth." This is that rig for the null_semantics witnesses.

The mechanism, honestly grounded — no monkeypatching, no reimplemented witnesses:

1. ``realize_population`` draws a labelled token population from a sampled
   null_tokens family (:mod:`testdata.entropy.families`): **markers** (``is-null``)
   cluster (a small set, repeated), **decoys** (``is-value``) smear (distinct,
   count 1). The labels are ground truth.
2. ``reconstruct_inputs`` builds the witness input shapes EXACTLY as the pipeline
   loaders do — per-token cast-failure counts (``rejected_token_counts``), the
   ``DISTINCT … ORDER BY value LIMIT 5`` ``failed_examples`` truncation, and
   ``parse_success_rate``. The faithfulness of this reconstruction is pinned by
   ``test_reliability_calibration``'s anchor against a real pipeline run's
   captured ``claim_witnesses``.
3. ``adjudicate_family`` calls the REAL engine ``measure_null_semantics`` (the
   three witness functions + the pooling engine) on those inputs.
4. ``estimate_reliabilities`` scores each witness's verdict against the label and
   returns a Beta-posterior accuracy — the measured r_i.

Reliability is accuracy CONDITIONAL on the witness expressing an opinion (a witness
that abstains at 0.5 is not penalised for declining to vote — it simply contributes
no certainty in the pool). That is the honest meaning of "how much do we trust this
witness when it speaks", and it is exactly the weight the log-linear pool consumes.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from dataraum.entropy.measurements.null_semantics import (
    CLAIM_SPACE,
    TokenAdjudication,
    measure_null_semantics,
)
from testdata.entropy.families import (
    CURATED_VOCAB,
    NullTokenFamilyParams,
    NullTokenFamilySample,
    mint_decoy,
    sample_null_token_family,
)

# CLAIM_SPACE = ("is-null", "is-value"); index 0 is the P(is-null) coordinate.
_IS_NULL = CLAIM_SPACE.index("is-null")
_ABSTAIN_EPS = 1e-9
_DEFAULT_ROWS = 2000


@dataclass(frozen=True)
class LabeledToken:
    """A rejected token with its ground-truth class and how many rows carry it."""

    token: str
    count: int
    is_null_marker: bool  # True → is-null (marker), False → is-value (decoy)


def realize_population(sample: NullTokenFamilySample, n_rows: int = _DEFAULT_ROWS) -> list[LabeledToken]:
    """Draw the labelled rejected-token population for one family sample.

    Markers are assigned across the small marker set (so they cluster — high count
    per token); decoys are minted distinct (count 1 — they smear). Deterministic in
    the sample's seed.

    This is a statistical STAND-IN for the live ``inject_null_token_family`` draw,
    not a per-row reconstruction of it: same family semantics (clustered markers,
    distinct decoys, the sampled grammar) and so the same witness behaviour in
    distribution, but an independent RNG. The witness inputs depend on token COUNTS,
    not row identity, so this is the right granularity for measuring reliability;
    the faithfulness of the COUNTS→inputs step is what the anchor test pins.
    """
    place = random.Random(f"rig-population:{sample.seed}")
    marker_count = max(1, int(n_rows * sample.marker_ratio))
    decoy_count = int(n_rows * sample.decoy_ratio)

    marker_hits = Counter(place.choice(sample.markers) for _ in range(marker_count))
    tokens = [LabeledToken(tok, n, True) for tok, n in marker_hits.items()]
    seen = set(marker_hits)

    if sample.decoy_cluster_size > 0:
        # Stress mode: decoys are a small repeated set → they CLUSTER like markers,
        # so quarantine_clustering (which votes is-null on any cluster) now faces a
        # clustered is-value and its false-positive rate enters the estimate.
        pool: list[str] = []
        while len(pool) < sample.decoy_cluster_size:
            decoy = mint_decoy(place, sample.decoy_style)
            if decoy not in seen and decoy not in pool:
                pool.append(decoy)
        decoy_hits = Counter(place.choice(pool) for _ in range(decoy_count))
        tokens += [LabeledToken(decoy, n, False) for decoy, n in decoy_hits.items()]
    else:
        # Normal mode: decoys are minted DISTINCT (count 1) → they smear.
        for _ in range(decoy_count):
            decoy = mint_decoy(place, sample.decoy_style)
            if decoy in seen:
                continue
            seen.add(decoy)
            tokens.append(LabeledToken(decoy, 1, False))
    return tokens


def reconstruct_inputs(
    tokens: Sequence[LabeledToken], n_rows: int, *, resolved_type: str = "BIGINT"
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The (quarantine, typing) witness inputs the pipeline loaders would produce.

    Mirrors ``load_quarantine_tokens`` (per-token cast-failure counts, total) and
    ``load_typing`` (``parse_success_rate``, and the ``DISTINCT … ORDER BY value
    LIMIT 5`` ``failed_examples`` truncation that gates the type witness). Faithful
    by construction; verified against captured ``claim_witnesses`` in the tests.
    """
    total_rejected = sum(t.count for t in tokens)
    ordered = sorted(tokens, key=lambda t: t.count, reverse=True)
    quarantine = {
        "rejected_tokens": [{"token": t.token, "count": t.count} for t in ordered],
        "total_rejected": total_rejected,
    }
    distinct = sorted({t.token for t in tokens})
    typing = {
        "resolved_type": resolved_type,
        "parse_success_rate": (n_rows - total_rejected) / n_rows if n_rows else 0.0,
        "failed_examples": distinct[:5],  # DISTINCT … ORDER BY value LIMIT 5
        "quarantine_rate": total_rejected / n_rows if n_rows else 0.0,
    }
    return quarantine, typing


def adjudicate_family(
    sample: NullTokenFamilySample,
    *,
    n_rows: int = _DEFAULT_ROWS,
    vocab: Sequence[str] = CURATED_VOCAB,
) -> list[tuple[TokenAdjudication, bool]]:
    """Run the real null_semantics adjudication over a sample; pair each with its label."""
    tokens = realize_population(sample, n_rows)
    labels = {t.token: t.is_null_marker for t in tokens}
    quarantine, typing = reconstruct_inputs(tokens, n_rows)
    adjudications = measure_null_semantics(quarantine, typing, list(vocab))
    return [(adj, labels[adj.token]) for adj in adjudications]


@dataclass(frozen=True)
class WitnessVote:
    """One witness's opinion on one labelled token."""

    witness_id: str
    p_is_null: float
    label_is_null: bool

    @property
    def has_opinion(self) -> bool:
        return abs(self.p_is_null - 0.5) > _ABSTAIN_EPS

    @property
    def correct(self) -> bool:
        """Whether the verdict matches the label (meaningful only when opinionated)."""
        return (self.p_is_null > 0.5) == self.label_is_null


def witness_votes(
    adjudicated: Iterable[tuple[TokenAdjudication, bool]],
) -> list[WitnessVote]:
    """Flatten adjudications into per-(witness, token) votes against the label."""
    votes: list[WitnessVote] = []
    for adj, label in adjudicated:
        for w in adj.witnesses:
            votes.append(WitnessVote(w.witness_id, w.distribution[_IS_NULL], label))
    return votes


def estimate_reliabilities(
    votes: Iterable[WitnessVote], *, alpha0: float = 1.0, beta0: float = 1.0
) -> dict[str, float]:
    """Laplace-smoothed accuracy per witness, over its OPINIONATED votes.

    ``r = (alpha0 + correct) / (alpha0 + beta0 + n_opinions)`` — the supervised
    "agreement with ground truth" of ADR-0009 source-1, with a weak uniform prior.
    Plain accuracy, deliberately: it is the literal reading of the doc, needs no
    post-hoc justification, honestly scores a witness that is right a quarter of the
    time at ~0.25 (rather than laundering it to 0.5), and — verified on held-out
    seeds — pools to a strictly LOWER Brier than any balanced/re-weighted variant.
    The rig MEASURES; the estimator is not chosen to flatter any witness.

    Abstentions (``|p − 0.5| ≤ eps``) are excluded — a witness is not unreliable for
    declining to vote; it simply adds no certainty to the pool. A witness that only
    ever votes one class (e.g. ``quarantine_clustering`` never argues is-value) is
    therefore scored on that one class: its ``r`` is a SENSITIVITY, not a
    discrimination score (see provenance, and the decoy-clustering stress family
    noted as future work).
    """
    tally: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [correct, n_opinions]
    for v in votes:
        if not v.has_opinion:
            continue
        tally[v.witness_id][1] += 1
        if v.correct:
            tally[v.witness_id][0] += 1
    return {
        witness_id: (alpha0 + correct) / (alpha0 + beta0 + n)
        for witness_id, (correct, n) in tally.items()
    }


def per_class_accuracy(votes: Iterable[WitnessVote]) -> dict[str, dict[str, float]]:
    """Per-witness {sensitivity (on is-null), specificity (on is-value)} over opinions.

    A diagnostic that exposes WHICH class a witness is unreliable on — a witness can
    look strong on plain accuracy yet have ~0 specificity (votes is-null on every
    cluster). Classes the witness never opines on are omitted. Not the shipped r;
    the shipped r is plain accuracy over the realistic corpus.
    """
    tally: dict[str, dict[bool, list[int]]] = defaultdict(lambda: {True: [0, 0], False: [0, 0]})
    for v in votes:
        if not v.has_opinion:
            continue
        cell = tally[v.witness_id][v.label_is_null]
        cell[1] += 1
        if v.correct:
            cell[0] += 1
    out: dict[str, dict[str, float]] = {}
    for witness_id, classes in tally.items():
        d: dict[str, float] = {}
        if classes[True][1]:
            d["sensitivity"] = classes[True][0] / classes[True][1]
        if classes[False][1]:
            d["specificity"] = classes[False][0] / classes[False][1]
        out[witness_id] = d
    return out


def opinion_counts(votes: Iterable[WitnessVote]) -> dict[str, int]:
    """Opinionated-vote count per witness — the effective sample behind each r.

    Witnesses abstain at very different rates (quarantine/type opine on a few
    percent of tokens, vocabulary on all), so the per-witness counts, not one
    aggregate, are the honest provenance for how well-supported each r is.
    """
    counts: dict[str, int] = defaultdict(int)
    for v in votes:
        if v.has_opinion:
            counts[v.witness_id] += 1
    return dict(counts)


def brier_per_witness(votes: Iterable[WitnessVote]) -> dict[str, float]:
    """Per-witness Brier diagnostic over ALL its votes (abstain = 0.25, the baseline).

    Brier = mean (p_is_null − label)². A witness whose opinions beat coin-flip on
    average scores below the 0.25 always-abstain baseline; a pure abstainer sits at
    0.25. A DIAGNOSTIC, not the wired AC4 metric — the calibration assertion is on
    the POOLED posterior (``pooled_brier_with``); this per-witness view just exposes
    which witnesses individually beat or trail the abstain baseline.
    """
    sq: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])  # [sum_sq, n]
    for v in votes:
        target = 1.0 if v.label_is_null else 0.0
        sq[v.witness_id][0] += (v.p_is_null - target) ** 2
        sq[v.witness_id][1] += 1.0
    return {w: total / n for w, (total, n) in sq.items() if n}


def pooled_brier(adjudicated: Iterable[tuple[TokenAdjudication, bool]]) -> float:
    """Brier of the POOLED posterior P(is-null) against the label, over all tokens."""
    total = 0.0
    n = 0
    for adj, label in adjudicated:
        p_is_null = adj.result.posterior[_IS_NULL] if adj.result.posterior else 0.5
        total += (p_is_null - (1.0 if label else 0.0)) ** 2
        n += 1
    return total / n if n else 0.0


def _repooled_p_is_null(adj: TokenAdjudication, reliabilities: dict[str, float]) -> float:
    """Re-pool an adjudication's witnesses under overridden reliabilities → P(is-null).

    The witness DISTRIBUTIONS are reliability-independent (they are the witnesses'
    opinions); only the pooled POSTERIOR depends on the weights. So we can measure
    how much a given reliability table improves resolution without re-running the
    witnesses, by re-pooling the same opinions under different weights.
    """
    from dataraum.entropy.pooling import Witness, pool

    weighted = [
        Witness(w.witness_id, w.distribution, reliabilities.get(w.witness_id, w.reliability))
        for w in adj.witnesses
    ]
    result = pool(weighted)
    return result.posterior[_IS_NULL] if result.posterior else 0.5


def pooled_brier_with(
    adjudicated: Iterable[tuple[TokenAdjudication, bool]], reliabilities: dict[str, float]
) -> float:
    """Pooled-posterior Brier when the witnesses are re-pooled under ``reliabilities``."""
    total = 0.0
    n = 0
    for adj, label in adjudicated:
        p_is_null = _repooled_p_is_null(adj, reliabilities)
        total += (p_is_null - (1.0 if label else 0.0)) ** 2
        n += 1
    return total / n if n else 0.0


def collect_adjudications(
    seeds: Iterable[int],
    *,
    n_rows: int = _DEFAULT_ROWS,
    params: NullTokenFamilyParams | None = None,
    vocab: Sequence[str] = CURATED_VOCAB,
) -> list[tuple[TokenAdjudication, bool]]:
    """Adjudicate the family across many seeds — the calibration sample."""
    out: list[tuple[TokenAdjudication, bool]] = []
    for seed in seeds:
        out.extend(adjudicate_family(sample_null_token_family(seed, params), n_rows=n_rows, vocab=vocab))
    return out


@dataclass(frozen=True)
class CalibrationResult:
    """The measured reliabilities + the proper-scoring diagnostics for one corpus."""

    reliabilities: dict[str, float]
    brier: dict[str, float]  # per-witness diagnostic (abstain baseline 0.25)
    pooled_brier: float
    n_seeds: int
    n_rows: int  # the row-count regime the inputs were reconstructed at
    per_witness_votes: dict[str, int]  # opinionated votes behind each r — the real sample


def calibrate(
    seeds: Sequence[int],
    *,
    n_rows: int = _DEFAULT_ROWS,
    params: NullTokenFamilyParams | None = None,
    vocab: Sequence[str] = CURATED_VOCAB,
) -> CalibrationResult:
    """Measure null_semantics witness reliabilities over a seed corpus."""
    adjudicated = collect_adjudications(seeds, n_rows=n_rows, params=params, vocab=vocab)
    votes = witness_votes(adjudicated)
    return CalibrationResult(
        reliabilities=estimate_reliabilities(votes),
        brier=brier_per_witness(votes),
        pooled_brier=pooled_brier(adjudicated),
        n_seeds=len(seeds),
        n_rows=n_rows,
        per_witness_votes=opinion_counts(votes),
    )
