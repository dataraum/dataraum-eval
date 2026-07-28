"""Tier-1: the stored_sign sign-partition witness (DAT-875, engine epic/dat-671-phase3).

The engine's own module docstring names TWO label-honesty caveats and says they are
calibration watch items. This file is the test team taking delivery of them: each is
reproduced as a deterministic probe over the REAL witness chain, in milliseconds, so the
claim is a repro rather than a paragraph.

The distinction that runs through all of it: what the witness measures with certainty is
the PARTITION — do the reconciling entities split across the two signs, or not. Mapping
that partition onto the NAMES ``natural_balance`` / ``ledger_signed`` requires knowing
something about the event side that the data does not carry.
"""

from __future__ import annotations

from typing import Any

import pytest
from dataraum.entropy.measurements.stored_sign import (
    LEDGER_SIGNED,
    NATURAL_BALANCE,
    resolved_stored_sign,
)

from calibration import stored_sign_rig as rig
from calibration.reliability_rig import estimate_reliabilities

_LABELS = (NATURAL_BALANCE, LEDGER_SIGNED)


def _label(pop: rig.Population, **kw: Any) -> str | None:
    return resolved_stored_sign(rig.adjudicate(pop, **kw))[0]


# ---------------------------------------------------------------------------
# the witness works — establish that before attacking it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stored", _LABELS)
def test_witness_recovers_the_convention_on_a_family_blind_event_column(stored: str) -> None:
    """The baseline the two caveats are deviations FROM.

    A raw debit/credit event side is how a journal stores its two sides, and under it the
    partition maps onto the names correctly: a natural-balance column splits its families
    across the two signs, a ledger-signed one does not.
    """
    pop = rig.make_population(n_debit=6, n_credit=6)
    assert _label(pop, stored=stored) == stored


def test_the_partition_itself_is_what_gets_measured() -> None:
    """Split vs uniform — the fact underneath both labels, stated once."""
    pop = rig.make_population(n_debit=6, n_credit=6)
    natural = rig.partition(pop, stored=NATURAL_BALANCE)
    ledger = rig.partition(pop, stored=LEDGER_SIGNED)

    assert (natural.primary, natural.mirror, natural.both) == (6, 6, 0)  # split
    assert (ledger.primary, ledger.mirror, ledger.both) == (12, 0, 0)  # uniform


# ---------------------------------------------------------------------------
# caveat 1 — the label is relative to the event side's normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stored", _LABELS)
def test_a_family_normalized_event_column_inverts_the_label(stored: str) -> None:
    """THE FINDING. Same population, same truth, same code — only the event column's
    normalization differs, and the resolved label flips to its opposite.

    The witness compares a measure against event amounts under a signed convention and
    its negation, so it reads the measure's sign RELATIVE to those amounts. The mapping
    split⇒natural_balance / uniform⇒ledger_signed silently assumes the event side is
    family-blind. Where it is not — an ``amount`` column already stated in each account's
    natural direction, which is a perfectly ordinary ERP export — a genuinely
    natural-balance measure reconciles uniformly and is labelled ``ledger_signed``, and
    vice versa.

    This is not a near-miss or a confidence wobble: the label is exactly inverted, with
    the witness's full confidence behind it. Not reachable on our finance corpus (its
    ``journal_lines`` carry a raw debit/credit pair) — the attack that would reach it is
    a generator-backlog item, and this probe is its ground-first evidence.
    """
    opposite = LEDGER_SIGNED if stored == NATURAL_BALANCE else NATURAL_BALANCE
    pop = rig.make_population(n_debit=6, n_credit=6)
    assert _label(pop, stored=stored, event_side=rig.FAMILY_NORMALIZED) == opposite


def test_the_inversion_is_confident_not_hesitant() -> None:
    """An inverted label that arrived with low confidence would be a lesser problem —
    a downstream consumer could gate on it. It does not: the posterior is as extreme as
    the correct reading's, because coverage (the only thing scaling this witness) is
    identical. There is nothing on the object to gate on."""
    pop = rig.make_population(n_debit=6, n_credit=6)
    right = rig.adjudicate(pop, stored=NATURAL_BALANCE)
    wrong = rig.adjudicate(pop, stored=NATURAL_BALANCE, event_side=rig.FAMILY_NORMALIZED)

    assert max(wrong.result.posterior) == pytest.approx(max(right.result.posterior))
    assert wrong.result.ignorance == pytest.approx(right.result.ignorance)


def test_an_llm_claim_that_is_right_is_overruled_by_the_inverted_partition() -> None:
    """The one witness that could have caught the inversion is pooled OUT.

    ``measure_stored_sign`` treats the partition as authoritative and overrules a
    disagreeing name-based claim — sound where the partition is identified, and exactly
    backwards here: the agent reads the column correctly, the partition is inverted by an
    assumption nobody checked, and the correct read is discarded. The ``overruled`` flag
    does record it, which is the seam a consumer could use.
    """
    pop = rig.make_population(n_debit=6, n_credit=6)
    adj = rig.adjudicate(
        pop,
        stored=NATURAL_BALANCE,
        event_side=rig.FAMILY_NORMALIZED,
        llm_claim=NATURAL_BALANCE,  # the truth
        llm_confidence=0.9,
    )
    assert adj.overruled
    assert resolved_stored_sign(adj)[0] == LEDGER_SIGNED


# ---------------------------------------------------------------------------
# caveat 2 — a single-family population cannot distinguish the two
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stored", _LABELS)
def test_a_single_family_population_always_reads_ledger_signed(stored: str) -> None:
    """Where every account is debit-normal the two conventions COINCIDE, so the truth is
    undetermined — and the witness answers ``ledger_signed`` either way.

    Being right by construction half the time is not the problem. The problem is the next
    test.
    """
    pop = rig.make_population(n_debit=8, n_credit=0)
    assert _label(pop, stored=stored) == LEDGER_SIGNED


def test_the_undetermined_label_is_indistinguishable_from_a_determined_one() -> None:
    """THE FINDING. Nothing on the emitted object separates "the data settled this" from
    "the data could not speak to it".

    A determined ``ledger_signed`` (mixed families, one sign explains all) and an
    undetermined one (single family, no split was possible) produce the same posterior,
    the same conflict and the same ignorance. So readiness reads the undetermined column
    as measured-clean, and any eval that counts labels counts it as covered — the engine
    said so itself. That makes it OUR bug too if we count naively, which is why the rig's
    estimator excludes this stratum rather than banking the free correctness.

    The evidence the witness does not use: whether the stored values themselves carry
    both signs. A mixed-family ledger-signed column has negative balances in it; a
    single-family one does not. That is a discriminator sitting in the same column, and
    it is not consulted. Not our fix to write — but the finding is weaker without it.
    """
    determined = rig.adjudicate(rig.make_population(n_debit=6, n_credit=6), stored=LEDGER_SIGNED)
    undetermined = rig.adjudicate(rig.make_population(n_debit=8, n_credit=0), stored=LEDGER_SIGNED)

    assert resolved_stored_sign(determined)[0] == resolved_stored_sign(undetermined)[0]
    assert undetermined.result.conflict == pytest.approx(determined.result.conflict)
    assert undetermined.result.ignorance == pytest.approx(determined.result.ignorance)
    assert max(undetermined.result.posterior) == pytest.approx(max(determined.result.posterior))


def test_the_single_family_stratum_is_excluded_from_the_estimator() -> None:
    """The eval-side consequence of caveat 2, pinned so nobody re-banks it later."""
    pops = rig.corpus(range(2))
    assert any(not p.discriminable for p, _ in pops), "the stratum must exist to be excluded"
    scored = rig.votes(pops)
    unscored = rig.votes(pops, discriminable_only=False)
    assert len(scored) < len(unscored)


# ---------------------------------------------------------------------------
# caveat 3 — ours, not the engine's: a mixed-convention column has no honest label
# ---------------------------------------------------------------------------


def test_two_miskeyed_accounts_relabel_the_whole_column() -> None:
    """THE FINDING, and the sharpest of the three. The flip threshold is an ABSOLUTE
    COUNT of 2 accounts, independent of how big the book is.

    A column keyed ``ledger_signed`` with two credit-normal accounts entered the other
    way is an ordinary data-entry inconsistency — precisely the class of defect this
    engine exists to surface. The witness sees a mirror-voting set of size 2, reads it as
    a second family, and relabels the ENTIRE column ``natural_balance``. The uniform
    branch is guarded against silence (``absence of mirror voters is not evidence of
    absence``); the split branch has no matching guard, because it assumes any two mirror
    voters ARE a family.

    Two of two hundred is 1%. The claim space has no ``inconsistent`` value, so there is
    no label the witness could have emitted that would have been true — which is the
    finding, not a request to add a guard.
    """
    pop = rig.make_population(n_debit=100, n_credit=100)
    assert _label(pop, stored=LEDGER_SIGNED) == LEDGER_SIGNED  # uncontaminated: correct

    two = rig.credit_entities(pop, 2)
    assert _label(pop, stored=LEDGER_SIGNED, contaminated=two) == NATURAL_BALANCE


def test_one_miskeyed_account_abstains_and_the_second_one_makes_it_confident() -> None:
    """The boundary, pinned from both sides — and it is worse than a correct→wrong step.

    With ONE dissenter the witness abstains: "a single dissenting entity is neither a
    family nor noise we can name". That is the honest answer, and it is the right one.
    Add a second and the same ambiguity resolves — to the WRONG label, with confidence.

    So the transition is abstain → confidently wrong, at exactly
    ``MIN_FAMILY_ENTITIES``. The guard that fires at k=1 is what makes k=2 read as
    settled rather than as more of the same doubt.
    """
    pop = rig.make_population(n_debit=100, n_credit=100)
    assert _label(pop, stored=LEDGER_SIGNED, contaminated=rig.credit_entities(pop, 1)) is None
    assert (
        _label(pop, stored=LEDGER_SIGNED, contaminated=rig.credit_entities(pop, 2))
        == NATURAL_BALANCE
    )


def test_the_relabelled_column_reports_no_conflict_at_all() -> None:
    """And it arrives clean: 1% contamination, a wrong label, C = 0.

    Nothing downstream can tell this from a correctly-read column. Readiness sees a
    measured object with no conflict; the served sign normalization is inverted for every
    row of the column.
    """
    pop = rig.make_population(n_debit=100, n_credit=100)
    adj = rig.adjudicate(pop, stored=LEDGER_SIGNED, contaminated=rig.credit_entities(pop, 2))
    assert resolved_stored_sign(adj) == (NATURAL_BALANCE, False)  # label wrong, NOT contested
    assert adj.result.conflict == pytest.approx(0.0)


def test_a_disagreeing_llm_claim_is_the_only_thing_that_would_have_caught_it() -> None:
    """With the agent reading the column correctly, the pool DOES record a disagreement —
    but as ``overruled``, and the wrong label still wins. The seam exists; nothing uses it.
    """
    pop = rig.make_population(n_debit=100, n_credit=100)
    adj = rig.adjudicate(
        pop,
        stored=LEDGER_SIGNED,
        contaminated=rig.credit_entities(pop, 2),
        llm_claim=LEDGER_SIGNED,  # the truth
        llm_confidence=0.9,
    )
    assert adj.overruled
    assert resolved_stored_sign(adj)[0] == NATURAL_BALANCE


# ---------------------------------------------------------------------------
# the guards that DO hold — the witness is not careless, and that matters for the file
# ---------------------------------------------------------------------------


def test_a_lone_dissenter_abstains_rather_than_rounding_to_uniform() -> None:
    """One credit-normal account among debit-normal ones is not a family. The witness
    refuses both readings instead of rounding the dissenter away — the behaviour that
    keeps caveat 2 a disclosure problem rather than a mislabelling one."""
    pop = rig.make_population(n_debit=8, n_credit=1)
    assert _label(pop, stored=NATURAL_BALANCE) is None


def test_absence_of_mirror_voters_is_not_evidence_of_absence() -> None:
    """A short-series credit family is SILENCED, not absent — and the witness abstains
    because the unexplained remainder is big enough to hide a family.

    Worth pinning from our side: it is the guard that stops the ledger_signed label being
    manufactured by silence, and it is the one thing standing between caveat 2 and a
    genuinely wrong answer on a mixed book.
    """
    pop = rig.make_population(n_debit=6, n_credit=6)
    silenced = rig.Population(
        accounts=tuple(
            a
            if not a.credit_normal
            else rig.Account(a.entity, True, a.natural_moves[:2], a.opening)
            for a in pop.accounts
        ),
        stratum="silenced_family",
    )
    part = rig.partition(silenced, stored=NATURAL_BALANCE)
    assert part.mirror == 0  # the credit family never votes
    assert _label(silenced, stored=NATURAL_BALANCE) is None  # …and nothing is concluded


# ---------------------------------------------------------------------------
# the measurement itself
# ---------------------------------------------------------------------------


def test_sign_partition_reliability_is_measured_not_placeholder() -> None:
    """The rig produces a reliability in range on the discriminable strata.

    Asserted as a floor against the engine's uncalibrated fallback (0.8), not as an
    equality: the shipped number is whatever the rig measures, and pinning it exactly
    would make every future corpus change a test edit.
    """
    measured = estimate_reliabilities(rig.votes(rig.corpus(range(4))))
    assert set(measured) == {"sign_partition"}
    assert 0.0 <= measured["sign_partition"] <= 1.0
    assert measured["sign_partition"] > 0.8


def test_noise_degrades_the_witness_toward_abstention_not_toward_error() -> None:
    """Recall-as-ordering applied to a reliability: as reconciliation noise rises the
    witness must lose COVERAGE (abstain) rather than start voting wrong. A statistic that
    degrades into confident error is the one that cannot be trusted at the margin."""
    labelled = rig.corpus(range(4))
    clean = rig.votes(labelled)
    noisy = rig.votes(labelled, anchor_noise=0.9)

    assert len(noisy) < len(clean), "heavy noise must silence some populations"
    wrong = [v for v in noisy if not v.correct]
    assert not wrong, f"{len(wrong)} confident-and-wrong votes under noise"
