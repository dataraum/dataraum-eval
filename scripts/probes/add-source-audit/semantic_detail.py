"""Every semantic + structural surface the run produced, in full.

One census pass. Each block is a surface a phase owns; the question for each is
the same — is what is in there RIGHT for this corpus, and is what is missing
explainable?

    uv run python scripts/probes/add-source-audit/semantic_detail.py rel-f1
"""

from __future__ import annotations

import argparse

from sqlalchemy import text

from calibration.tools._runs import load_run, workspace_session

BLOCKS: dict[str, str] = {
    "semantic roles (current_semantic_annotations)": """
        SELECT t.table_name || '.' || c.column_name AS col, sa.semantic_role,
               sa.confidence
        FROM current_semantic_annotations sa
        JOIN current_columns c ON c.column_id = sa.column_id
        JOIN current_tables t ON t.table_id = c.table_id
        ORDER BY t.table_name, c.column_position
    """,
    "role histogram": """
        SELECT semantic_role, count(*) FROM current_semantic_annotations
        GROUP BY 1 ORDER BY 2 DESC
    """,
    "table entities": """
        SELECT t.table_name, te.table_role, te.detected_entity_type, te.grain_columns, te.time_columns, te.detection_source
        FROM current_table_entities te
        JOIN current_tables t ON t.table_id = te.table_id
        ORDER BY t.table_name
    """,
    "column eligibility histogram": """
        SELECT status, triggered_rule, count(*) FROM current_column_eligibility
        GROUP BY 1,2 ORDER BY 3 DESC
    """,
    "eligibility non-ELIGIBLE detail": """
        SELECT t.table_name || '.' || c.column_name, ce.status, ce.reason
        FROM current_column_eligibility ce
        JOIN current_columns c ON c.column_id = ce.column_id
        JOIN current_tables t ON t.table_id = c.table_id
        WHERE ce.status <> 'ELIGIBLE'
        ORDER BY 1
    """,
    "relationships by type + confirmation": """
        SELECT relationship_type, confirmation_source, detection_method, count(*)
        FROM current_relationships GROUP BY 1,2,3 ORDER BY 4 DESC
    """,
    "concepts": """
        SELECT concept_id, name, kind, source FROM concepts ORDER BY source, name
    """,
    "column_concepts (meanings)": """
        SELECT t.table_name || '.' || c.column_name, left(cc.meaning, 90)
        FROM current_column_concepts cc
        JOIN current_columns c ON c.column_id = cc.column_id
        JOIN current_tables t ON t.table_id = c.table_id
        ORDER BY 1
    """,
    "enriched views": """
        SELECT view_name, is_grain_verified, json_array_length(dimension_table_ids::json) AS n_dims FROM current_enriched_views ORDER BY 1
    """,
    "slice definitions": """
        SELECT slice_type, fk_role, detection_source, count(*) FROM current_slice_definitions GROUP BY 1,2,3 ORDER BY 4 DESC
    """,
    "dimension hierarchies": """
        SELECT kind, canonical_label, role_verdict, identity_confidence, needs_confirmation, detection_source FROM current_dimension_hierarchies ORDER BY 1,2
    """,
    "bus matrix": """
        SELECT concept_label, conformed_group, attachment, needs_confirmation, confirmation_source FROM current_bus_matrix ORDER BY 1
    """,
    "driver rankings": """
        SELECT * FROM current_driver_rankings ORDER BY 1 LIMIT 25
    """,
    "measure aggregation lineage": """
        SELECT * FROM current_measure_aggregation_lineage LIMIT 20
    """,
    "materialization recipes": """
        SELECT layer, count(*) FROM current_materialization_recipes GROUP BY 1
    """,
    "entropy by detector": """
        SELECT detector_id, count(*) AS n, round(max(score)::numeric,3) AS max_score,
               round(avg(score)::numeric,3) AS avg_score
        FROM current_entropy_objects GROUP BY 1 ORDER BY 3 DESC
    """,
    "entropy readiness": """
        SELECT target, band, worst_intent_risk, intents::text
        FROM current_entropy_readiness
        WHERE target IN ('column:circuits.alt', 'column:standings.wins')
    """,
    "band vs max score": """
        SELECT r.band, count(*) AS n_columns,
               round(max(s.max_score)::numeric, 3) AS worst_max_score,
               count(*) FILTER (WHERE coalesce(s.max_score, 0) = 0) AS n_all_scores_zero
        FROM current_entropy_readiness r
        LEFT JOIN (
            SELECT column_id, max(score) AS max_score
            FROM current_entropy_objects GROUP BY 1
        ) s ON s.column_id = r.column_id
        WHERE r.column_id IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC
    """,
    "candidate relationships": """
        SELECT relationship_type, confirmation_source,
               count(*) AS n,
               round(min(confidence)::numeric,3) AS min_conf,
               round(max(confidence)::numeric,3) AS max_conf
        FROM current_relationships GROUP BY 1,2 ORDER BY 3 DESC
    """,
    "og_references exposure": """
        SELECT relationship_type, confirmation_source, count(*) AS edges
        FROM og_references GROUP BY 1,2 ORDER BY 3 DESC
    """,
    "candidate edges per table pair": """
        SELECT tf.table_name AS from_t, tt.table_name AS to_t, count(*) AS edges
        FROM og_references r
        JOIN current_tables tf ON tf.table_id = r.from_table_id
        JOIN current_tables tt ON tt.table_id = r.to_table_id
        GROUP BY 1,2 ORDER BY 3 DESC LIMIT 15
    """,
    "conformed dimension edges": """
        SELECT count(*) AS edges, count(DISTINCT dimension_attribute) AS attrs,
               string_agg(DISTINCT dimension_attribute, ', ') AS which
        FROM og_conformed_dimension
    """,
    "bank<->gl edges": """
        SELECT tf.table_name || '.' || cf.column_name AS src, tt.table_name || '.' || ct.column_name AS dst,
               r.relationship_type, r.confirmation_source, r.confidence
        FROM current_relationships r
        JOIN current_columns cf ON cf.column_id = r.from_column_id
        JOIN current_columns ct ON ct.column_id = r.to_column_id
        JOIN current_tables tf ON tf.table_id = cf.table_id
        JOIN current_tables tt ON tt.table_id = ct.table_id
        WHERE (tf.table_name, tt.table_name) IN
              (('bank_transactions','general_ledger'), ('general_ledger','bank_transactions'))
        ORDER BY 1,2
    """,
    "payment_id relationship": """
        SELECT tf.table_name || '.' || cf.column_name AS src,
               tt.table_name || '.' || ct.column_name AS dst,
               r.relationship_type, r.confirmation_source, r.confidence
        FROM current_relationships r
        JOIN current_columns cf ON cf.column_id = r.from_column_id
        JOIN current_columns ct ON ct.column_id = r.to_column_id
        JOIN current_tables tf ON tf.table_id = cf.table_id
        JOIN current_tables tt ON tt.table_id = ct.table_id
        WHERE cf.column_name LIKE '%payment%' OR ct.column_name LIKE '%payment%'
        ORDER BY 1,2
    """,
    "typed table rows": """
        SELECT table_name, layer, count(*) AS rows_in_catalog,
               count(DISTINCT table_id) AS distinct_ids
        FROM tables WHERE layer = 'typed' AND table_name LIKE '%results%'
        GROUP BY 1,2 ORDER BY 1
    """,
    "stockflow by table": """
        SELECT t.table_name, c.column_name, d.target_type, d.grain, d.n_rows
        FROM current_driver_rankings d
        JOIN current_columns c ON c.column_id = d.measure_column_id
        JOIN current_tables t ON t.table_id = d.measure_table_id
        WHERE c.column_name IN ('points','wins','position')
        ORDER BY 2, 1
    """,
    "temporal_behavior standings": """
        SELECT t.table_name || '.' || c.column_name AS col, round(e.score::numeric,3) AS score,
               e.evidence::text
        FROM current_entropy_objects e
        JOIN current_columns c ON c.column_id = e.column_id
        JOIN current_tables t ON t.table_id = c.table_id
        WHERE e.detector_id = 'temporal_behavior'
          AND t.table_name || '.' || c.column_name IN
              ('standings.wins','standings.points','standings.position',
               'results.points','results.grid','circuits.alt')
        ORDER BY 1
    """,
    "investigate columns": """
        SELECT target, round(worst_intent_risk::numeric,4) AS risk,
               substring(intents::text from 'node": "([a-z_]+)') AS top_driver
        FROM current_entropy_readiness
        WHERE band <> 'ready' AND column_id IS NOT NULL
        ORDER BY 2 DESC
    """,
    "temporal profiles": """
        SELECT t.table_name || '.' || c.column_name AS col,
               p.min_timestamp::text, p.max_timestamp::text, p.span_days,
               p.detected_granularity, p.gap_count, p.largest_gap_days, p.is_stale
        FROM current_temporal_column_profiles p
        JOIN current_columns c ON c.column_id = p.column_id
        JOIN current_tables t ON t.table_id = c.table_id
        ORDER BY 1
    """,
    "entry_id edges": """
        SELECT tf.table_name || '.' || cf.column_name AS from_col,
               tt.table_name || '.' || ct.column_name AS to_col,
               r.relationship_type, r.cardinality, r.confirmation_source, r.confidence
        FROM current_relationships r
        JOIN current_columns cf ON cf.column_id = r.from_column_id
        JOIN current_columns ct ON ct.column_id = r.to_column_id
        JOIN current_tables tf ON tf.table_id = cf.table_id
        JOIN current_tables tt ON tt.table_id = ct.table_id
        WHERE cf.column_name IN ('entry_id','account_id') AND r.relationship_type <> 'candidate'
        ORDER BY 1,2
    """,
    "validation results": """
        SELECT replace(sql_used, chr(10), ' | ') AS sql1 FROM current_validation_results WHERE validation_id = 'orphan_transactions'
    """,
    "detected cycles": """
        SELECT canonical_type, cycle_name, confidence, tables_involved::text FROM current_detected_business_cycles ORDER BY 1
    """,
    "folded cells": """
        SELECT b.concept_label, b.attachment, b.conformed_group, b.roles::text,
               b.attributes::text, t.table_name AS fact
        FROM current_bus_matrix b
        JOIN current_tables t ON t.table_id = b.fact_table_id
        ORDER BY b.conformed_group NULLS LAST, t.table_name
    """,
    "bus attachment": """
        SELECT attachment, confirmation_source, needs_confirmation,
               count(*) AS n, count(conformed_group) AS with_group
        FROM current_bus_matrix GROUP BY 1,2,3 ORDER BY 4 DESC
    """,
    "bus matrix conformed_group": """
        SELECT conformed_group, count(*) FROM current_bus_matrix GROUP BY 1
    """,
    "date alias raw members": """
        SELECT h.identity_confidence,
               m->>'column_name' AS column_name, m->>'column_id' AS column_id,
               t.table_name, c.column_position
        FROM current_dimension_hierarchies h,
             json_array_elements(h.members::json) m
        LEFT JOIN current_columns c ON c.column_id = (m->>'column_id')
        LEFT JOIN current_tables t ON t.table_id = c.table_id
        WHERE h.kind = 'alias' AND h.canonical_label = 'date'
        ORDER BY h.identity_confidence, column_id
    """,
    "alias hierarchies (member counts)": """
        SELECT canonical_label, kind, identity_confidence, needs_confirmation,
               json_array_length(members::json) AS n_members,
               (SELECT string_agg(t.table_name, ', ' ORDER BY t.table_name)
                  FROM json_array_elements(h.members::json) m
                  JOIN current_columns c ON c.column_id = (m->>'column_id')
                  JOIN current_tables t ON t.table_id = c.table_id) AS tables
        FROM current_dimension_hierarchies h
        WHERE kind = 'alias'
        ORDER BY canonical_label, identity_confidence
    """,
    "temporal_behavior circuits": """
        SELECT t.table_name || '.' || c.column_name AS col, e.score, e.evidence::text
        FROM current_entropy_objects e
        JOIN current_columns c ON c.column_id = e.column_id
        JOIN current_tables t ON t.table_id = c.table_id
        WHERE e.detector_id = 'temporal_behavior' AND t.table_name = 'circuits'
    """,
    "claim witnesses by kind": """
        SELECT detector_id, claim_field, reliability, count(*) FROM current_claim_witnesses GROUP BY 1,2,3 ORDER BY 4 DESC
    """,
    "snapshot heads": """
        SELECT * FROM metadata_snapshot_head ORDER BY 1
    """,
}


def main(strategy: str, only: str | None, schema: str | None = None) -> None:
    load_run(strategy)
    with workspace_session() as session:
        read = schema or (str(session.execute(text("SELECT current_schema()")).scalar()) + "_read")
        session.execute(text(f'SET search_path TO "{read}"'))
        for title, sql in BLOCKS.items():
            if only and only not in title:
                continue
            print(f"\n### {title}")
            try:
                # Re-arm after any prior rollback — a ROLLBACK drops search_path.
                session.execute(text(f'SET search_path TO "{read}"'))
                res = session.execute(text(sql))
                cols = list(res.keys())
                rows = res.fetchall()
            except Exception as err:  # noqa: BLE001 — census: report and continue
                print(f"  !! {type(err).__name__}: {str(err)[:200]}")
                session.rollback()
                continue
            print("  " + " | ".join(str(c) for c in cols))
            for r in rows:
                print("  " + " | ".join("" if v is None else str(v)[:100] for v in r))
            print(f"  ({len(rows)} rows)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("strategy")
    p.add_argument("--only", default=None)
    p.add_argument("--schema", default=None)
    main(**vars(p.parse_args()))
