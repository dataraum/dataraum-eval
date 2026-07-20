"""Frame a vertical for a wild corpus — eval's stand-in for the cockpit `frame` stage.

Discovered by the rel-f1 smoke (2026-07-20): a corpus in a domain the engine has not
been framed for **cannot reach the pipeline at all**. `semantic_per_column` fails loud
on `_adhoc` — "No concepts for vertical '_adhoc'" — because concept induction left the
engine under DAT-382 and now belongs to the cockpit `frame` stage, which eval does not
drive. Exactly one domain vertical ships (`finance`). Without this helper, Tier B can
only ever be graded under a finance ontology it has no business wearing.

So this writes the typed `concepts` rows a framed vertical is made of, the same table
the cockpit's frame stage writes through (`analysis/semantic/concept_store.py`,
`db_models.Concept` — keyed `(vertical, name)`, one active row each). It is not a
second seeding mechanism; it is the frame stage, driven from eval.

**A vertical is product configuration, not ground truth.** These concepts are what a
customer onboarding this data would declare about their own domain — a vocabulary the
engine grounds columns *against*. They are deliberately NOT part of
`metadata_truth.yaml` and nothing is graded against them. The declared-structure truth
(FKs, time columns) stays the only thing scored, per the Tier-B contract. Naming a
vocabulary is allowed; asserting the engine should reproduce our reading of someone
else's schema is not.

    uv run python scripts/frame_wild_vertical.py rel-f1
"""

from __future__ import annotations

import argparse
from typing import Any

# Concepts read off rel-f1's actual columns (corpora/relbench/rel-f1/schema.json),
# not off recollection of the sport: the four entities the schema keys on, the
# measures its fact tables carry, and the dimensions those measures slice by.
MOTORSPORT: list[dict[str, Any]] = [
    # --- entities: what the tables are grained on ---
    {"name": "driver", "kind": "entity", "description": "A competitor who races",
     "indicators": ["driver", "driverref", "forename", "surname"]},
    {"name": "constructor", "kind": "entity", "description": "A team that enters cars",
     "indicators": ["constructor", "constructorref", "team"]},
    {"name": "circuit", "kind": "entity", "description": "A track a race is held at",
     "indicators": ["circuit", "circuitref"]},
    {"name": "race", "kind": "entity", "description": "A single competitive event at a circuit",
     "indicators": ["race", "raceid", "round", "grand_prix"]},
    # --- measures: what gets aggregated ---
    {"name": "points", "kind": "measure",
     "description": "Championship points awarded for a result", "indicators": ["points"]},
    {"name": "wins", "kind": "measure", "description": "Count of race victories",
     "indicators": ["wins"]},
    {"name": "laps_completed", "kind": "measure", "description": "Laps completed in a race",
     "indicators": ["laps"]},
    {"name": "elapsed_time", "kind": "measure",
     "description": "Duration of a lap or race", "indicators": ["milliseconds", "time"],
     "unit_from_concept": "duration"},
    # --- dimensions: what measures are sliced by ---
    {"name": "finishing_position", "kind": "dimension",
     "description": "Order a competitor finished or is ranked in",
     "indicators": ["position", "positionorder", "rank", "grid"]},
    {"name": "season", "kind": "dimension", "description": "Championship year",
     "indicators": ["year", "season"]},
    {"name": "nationality", "kind": "dimension",
     "description": "Country a driver or constructor represents",
     "indicators": ["nationality", "country"]},
    {"name": "result_status", "kind": "dimension",
     "description": "How a competitor's race ended (finished, retired, disqualified)",
     "indicators": ["status", "statusid"]},
]

VERTICALS: dict[str, list[dict[str, Any]]] = {"rel-f1": MOTORSPORT}


def frame(strategy: str) -> int:
    """Write the corpus's concept vocabulary into its workspace, idempotently."""
    from dataraum.storage.upsert import insert_if_absent

    from calibration import runner
    from calibration.tools._runs import workspace_session

    concepts = VERTICALS.get(strategy)
    if concepts is None:
        raise SystemExit(
            f"No vertical framed for {strategy!r}. Known: {', '.join(sorted(VERTICALS))}"
        )

    runner.activate_workspace(strategy)
    from dataraum.analysis.semantic.db_models import Concept

    rows = [
        {
            "vertical": strategy,
            "name": c["name"],
            "kind": c["kind"],
            "description": c["description"],
            "indicators": c.get("indicators") or None,
            "exclude_patterns": c.get("exclude_patterns") or None,
            "unit_from_concept": c.get("unit_from_concept"),
            # 'frame', not 'seed' — this vertical ships no on-disk ontology, and
            # mislabelling it would make a re-seed think it owns these rows.
            "source": "frame",
        }
        for c in concepts
    ]
    with workspace_session() as session:
        from sqlalchemy import text

        written = insert_if_absent(
            session,
            Concept,
            rows,
            index_elements=["vertical", "name"],
            # The active-row partial index — same conflict target the seed path uses,
            # so re-framing is a no-op and never resurrects a superseded edit.
            index_where=text("superseded_at IS NULL"),
        )
        session.commit()

    print(f"[frame] vertical {strategy!r}: {len(rows)} concepts declared, {written} newly written")
    print("[frame] product configuration, NOT ground truth — nothing is graded against these")
    return written


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("strategy", help="Staged wild corpus to frame (e.g. rel-f1)")
    frame(parser.parse_args().strategy)
