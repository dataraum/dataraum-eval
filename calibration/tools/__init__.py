"""Direct-Python query surface over a completed calibration run (post-MCP).

The engine's MCP server was retired in the product pivot (ADR-0002; deleted in
DAT-487) and the cockpit is the product's only client. The eval skills
(/investigate, /deliver, /accept) therefore read the engine as a LIBRARY — the
same live functions the detect path and the cockpit-era REST extraction wrap —
through these small CLIs:

    uv run python -m calibration.tools.look <strategy> [table]
    uv run python -m calibration.tools.measure <strategy> [--target table.column]
    uv run python -m calibration.tools.sql <strategy> "SELECT ..."

All three are READ-ONLY and require a completed run (the sidecar at
``output/<strategy>/calibration_run.json``); none of them ever triggers a
pipeline. Scores come from the head-resolved ``current_entropy_objects`` view
(the conftest path — never PhaseLog); readiness is the loss rollup.
"""
