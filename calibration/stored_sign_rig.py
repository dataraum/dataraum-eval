"""Stored-sign witness rig — a labelled population for the DAT-875 sign partition.

The engine ships ``stored_sign`` on PLACEHOLDER priors: ``reliabilities.yaml`` carries
``provenance.measurements.stored_sign: {calibrated: false}`` and ``loss.yaml`` says the
same in prose. Measuring them is ours (DAT-450 archetype 3). This rig measures the half
that needs no LLM.

**Why this one is measurable for free.** ``stored_sign`` pools two witnesses:
``llm_claim`` (the catalogue agent — needs a real run, like temporal_behavior's) and
``sign_partition``, which is deterministic arithmetic over per-entity series. So the
data-grounded witness can be scored against a labelled synthetic population in
milliseconds, and only the LLM half has to wait for a budgeted pass.

**No reimplementation.** The rig builds series and then hands them to the REAL engine
code — ``lineage.reconcile.classify_series``, ``lineage.processor._sign_partition``,
``entropy.measurements.stored_sign`` — exactly as the null-token rig reconstructs the
real loader SQL rather than imitating it. A rig that reimplements the statistic measures
the rig.

**The generative model, stated so the number can be read honestly.** Each account has a
movement series in its OWN natural direction (``natural_moves``) and a family:

* debit-normal (assets, expenses) — natural direction IS the ledger's debit direction
* credit-normal (liabilities, equity, revenue) — natural direction is the ledger's credit
  direction, i.e. the negation

Two independent switches then generate the observable pair:

* ``stored`` — how the BALANCE column stores its values: ``natural_balance`` (each family
  in its own direction) or ``ledger_signed`` (one raw ledger direction for all).
* ``event_side`` — how the EVENT column states its amounts: ``family_blind`` (a raw
  debit/credit pair, which is how a journal stores its two sides) or
  ``family_normalized``.

The witness only ever sees the reconciliation of the two. Which is the whole point: it
measures the PARTITION, and the mapping from partition to the two NAMES is an assumption
about ``event_side`` that the data does not carry. See ``test_stored_sign_witness.py``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from dataraum.analysis.lineage.models import PATTERN_CUMULATIVE
from dataraum.analysis.lineage.processor import _sign_partition, _SignPartition
from dataraum.analysis.lineage.reconcile import classify_series
from dataraum.entropy.measurements.stored_sign import (
    LEDGER_SIGNED,
    NATURAL_BALANCE,
    ColumnStoredSignAdjudication,
    measure_stored_sign,
)

from calibration.reliability_rig import WitnessVote

# How the event column states its amounts. The witness's label mapping assumes the
# first; nothing in the data says which one holds (engine module docstring, caveat 1).
FAMILY_BLIND = "family_blind"
FAMILY_NORMALIZED = "family_normalized"

# Named for readability, deliberately NOT Literal: the values are the engine's own
# module-level constants, which are plain ``str``. Narrowing here would buy nothing and
# cost a type-ignore at every call site.
Stored = str  # NATURAL_BALANCE | LEDGER_SIGNED
EventSide = str  # FAMILY_BLIND | FAMILY_NORMALIZED

# Deliberately above reconcile.MIN_PERIODS (4) for the default strata: this rig is not
# measuring the period-count gate, which reconcile's own tests already pin.
_DEFAULT_PERIODS = 8


@dataclass(frozen=True)
class Account:
    """One entity: its family, and its movements in its OWN natural direction."""

    entity: str
    credit_normal: bool
    natural_moves: tuple[float, ...]
    opening: float = 0.0


@dataclass(frozen=True)
class Population:
    """A labelled reconciling population — the unit the estimator scores."""

    accounts: tuple[Account, ...]
    stratum: str

    @property
    def n_entities(self) -> int:
        return len(self.accounts)

    @property
    def families(self) -> set[bool]:
        return {a.credit_normal for a in self.accounts}

    @property
    def discriminable(self) -> bool:
        """Can the DATA tell the two conventions apart at all?

        Only where both families are present. In a single-family population the natural
        and ledger directions COINCIDE, so no partition can distinguish them — the
        engine's caveat 2. Scoring a witness on an undetermined population measures
        nothing, so the estimator excludes these and reports them separately.
        """
        return len(self.families) == 2


def series(
    account: Account,
    *,
    stored: Stored,
    event_side: EventSide,
    anchor_noise: float = 0.0,
    rng: random.Random | None = None,
) -> tuple[list[float], list[float]]:
    """One entity's ``(balance series y, event anchor m)`` under the two switches.

    ``anchor_noise`` perturbs the EVENT side as a fraction of each movement — the
    reconciliation noise ``FIRE_RESIDUAL_MAX`` is calibrated against. It is applied to
    the anchor, not the balance, because a balance that disagrees with its own movements
    is a different defect (a broken carry-forward) and not what this rig measures.
    """
    ledger_sign = -1.0 if account.credit_normal else 1.0
    raw_moves = [ledger_sign * n for n in account.natural_moves]

    anchor = list(account.natural_moves) if event_side == FAMILY_NORMALIZED else raw_moves
    if anchor_noise and rng is not None:
        anchor = [m * (1.0 + rng.uniform(-anchor_noise, anchor_noise)) for m in anchor]

    stored_moves = account.natural_moves if stored == NATURAL_BALANCE else raw_moves
    y: list[float] = []
    balance = account.opening
    for move in stored_moves:
        balance += move
        y.append(balance)
    return y, anchor


def _opposite(stored: Stored) -> Stored:
    return LEDGER_SIGNED if stored == NATURAL_BALANCE else NATURAL_BALANCE


def partition(
    population: Population,
    *,
    stored: Stored,
    event_side: EventSide = FAMILY_BLIND,
    anchor_noise: float = 0.0,
    seed: int = 0,
    contaminated: frozenset[str] = frozenset(),
) -> _SignPartition:
    """The measured voter partition — via the REAL engine reconciliation.

    ``contaminated`` names entities stored under the OPPOSITE convention to the rest of
    the column: the ordinary data-entry inconsistency of a few accounts keyed the other
    way. The claim space has no value for "inconsistent", so what the witness does with
    these is a question about the label, not about the arithmetic.
    """
    rng = random.Random(seed)
    by_entity = {
        a.entity: series(
            a,
            stored=_opposite(stored) if a.entity in contaminated else stored,
            event_side=event_side,
            anchor_noise=anchor_noise,
            rng=rng,
        )
        for a in population.accounts
    }
    results = classify_series(by_entity)
    return _sign_partition(by_entity, results, PATTERN_CUMULATIVE)


def adjudicate(
    population: Population,
    *,
    stored: Stored,
    event_side: EventSide = FAMILY_BLIND,
    anchor_noise: float = 0.0,
    seed: int = 0,
    contaminated: frozenset[str] = frozenset(),
    llm_claim: str | None = None,
    llm_confidence: float | None = None,
) -> ColumnStoredSignAdjudication:
    """Drive the full witness chain: series → partition → the pooled adjudication."""
    part = partition(
        population,
        stored=stored,
        event_side=event_side,
        anchor_noise=anchor_noise,
        seed=seed,
        contaminated=contaminated,
    )
    return measure_stored_sign(
        "ledger",
        "balance",
        llm_claim=llm_claim,
        llm_confidence=llm_confidence,
        n_entities=population.n_entities,
        fired_primary=part.primary,
        fired_mirror=part.mirror,
        fired_both=part.both,
    )


# ---------------------------------------------------------------------------
# populations
# ---------------------------------------------------------------------------


def make_population(
    *,
    n_debit: int,
    n_credit: int,
    periods: int = _DEFAULT_PERIODS,
    stratum: str = "mixed",
    seed: int = 0,
) -> Population:
    """A population of ``n_debit`` + ``n_credit`` accounts with random movements.

    Movements are drawn strictly positive in the account's natural direction — an
    account that both grows and shrinks is fine for the arithmetic, but a series whose
    movements sum to ~0 has a dead anchor and abstains, which would silently thin the
    population rather than test anything.
    """
    rng = random.Random(seed)
    accounts: list[Account] = []
    for family, count in ((False, n_debit), (True, n_credit)):
        for i in range(count):
            name = f"{'cr' if family else 'dr'}-{i}"
            moves = tuple(rng.uniform(50.0, 5_000.0) for _ in range(periods))
            accounts.append(
                Account(
                    entity=name,
                    credit_normal=family,
                    natural_moves=moves,
                    opening=rng.uniform(0.0, 10_000.0),
                )
            )
    return Population(accounts=tuple(accounts), stratum=stratum)


def credit_entities(population: Population, k: int) -> frozenset[str]:
    """The first ``k`` credit-normal entities — the only ones contamination can show on.

    A debit-normal account stores the same values under either convention (its natural
    direction IS the ledger's), so keying one "the other way" is not observable. Only the
    credit-normal side carries the flip.
    """
    return frozenset([a.entity for a in population.accounts if a.credit_normal][:k])


# The disclosed corpus composition. Each entry is a stratum the witness must survive,
# NOT a difficulty dial turned until the number looked good — the mix is stated here so
# the measured reliability can be read against it. `single_family` is generated and
# reported but never scored (see Population.discriminable).
STRATA: tuple[tuple[str, dict[str, int]], ...] = (
    # the easy case: two well-populated families, long series
    ("balanced", {"n_debit": 6, "n_credit": 6, "periods": 8}),
    # a minority family that is still a family — the MIN_FAMILY_ENTITIES boundary
    ("small_minority", {"n_debit": 9, "n_credit": 2, "periods": 8}),
    # short series: fewer periods, closer to reconcile.MIN_PERIODS
    ("short_series", {"n_debit": 5, "n_credit": 5, "periods": 5}),
    # lopsided and long — a big debit book with a thin credit tail
    ("lopsided", {"n_debit": 20, "n_credit": 3, "periods": 12}),
    # UNDETERMINED by construction: one family only (engine caveat 2)
    ("single_family", {"n_debit": 8, "n_credit": 0, "periods": 8}),
)


def corpus(seeds: range) -> list[tuple[Population, Stored]]:
    """The labelled corpus: every stratum x every truth label x every seed."""
    out: list[tuple[Population, Stored]] = []
    for seed in seeds:
        for stratum, kwargs in STRATA:
            pop = make_population(stratum=stratum, seed=seed, **kwargs)
            for stored in (NATURAL_BALANCE, LEDGER_SIGNED):
                out.append((pop, stored))
    return out


def votes(
    labelled: list[tuple[Population, Stored]],
    *,
    event_side: EventSide = FAMILY_BLIND,
    anchor_noise: float = 0.0,
    discriminable_only: bool = True,
) -> list[WitnessVote]:
    """Score the sign_partition witness against each labelled population.

    ``WitnessVote`` is reused verbatim from the null-token rig so the SAME estimator
    (Laplace-smoothed accuracy over opinionated votes) produces every shipped
    reliability. Its fields read ``p_is_null`` / ``label_is_null`` — here they carry
    P(natural_balance) and "the truth is natural_balance", which is the same first-class
    convention ``CLAIM_SPACE`` fixes. Renaming the shared dataclass to suit one rig would
    be worse than the mild awkwardness.
    """
    out: list[WitnessVote] = []
    for pop, stored in labelled:
        if discriminable_only and not pop.discriminable:
            continue
        adj = adjudicate(pop, stored=stored, event_side=event_side, anchor_noise=anchor_noise)
        for witness in adj.witnesses:
            if witness.witness_id != "sign_partition":
                continue
            p_natural = witness.distribution[0]
            out.append(
                WitnessVote(
                    witness_id=witness.witness_id,
                    p_is_null=p_natural,
                    label_is_null=(stored == NATURAL_BALANCE),
                )
            )
    return out
