#!/usr/bin/env bash
# Quick Zone 2 test via the dataraum CLI.
#
# Usage:
#   ./scripts/test-zone2-cli.sh                    # full: generate + pipeline + check
#   ./scripts/test-zone2-cli.sh --pipeline-only     # skip generation, re-run pipeline
#   ./scripts/test-zone2-cli.sh --check-only        # just inspect existing scores
#
# Requires: uv, data already generated for --pipeline-only/--check-only

set -euo pipefail

STRATEGY="zone2-detection-v1"
DATA_DIR="data/${STRATEGY}"
OUTPUT_DIR="output/${STRATEGY}"
TARGET_PHASE="analysis_review"

# --- Parse flags ---
GENERATE=true
PIPELINE=true
CHECK=true

case "${1:-}" in
  --pipeline-only) GENERATE=false ;;
  --check-only)    GENERATE=false; PIPELINE=false ;;
esac

# --- Step 1: Generate test data ---
if $GENERATE; then
  echo "=== Generating test data (${STRATEGY}) ==="
  uv run python -m calibration.runner "${STRATEGY}" --generate-only --seed 42
  echo ""
fi

# --- Step 2: Run pipeline through analysis_review (Gate 2) ---
if $PIPELINE; then
  echo "=== Running pipeline → ${TARGET_PHASE} ==="
  uv run dataraum run "${DATA_DIR}" -o "${OUTPUT_DIR}" -p "${TARGET_PHASE}" -v
  echo ""
fi

# --- Step 3: Check scores ---
if $CHECK; then
  echo "=== Gate 2 Scores ==="
  uv run python3 -c "
import sqlite3, json, sys

db = '${OUTPUT_DIR}/metadata.db'
conn = sqlite3.connect(db)
row = conn.execute(
    \"SELECT outputs FROM phase_logs WHERE phase_name = 'analysis_review' ORDER BY completed_at DESC LIMIT 1\"
).fetchone()
conn.close()

if not row or not row[0]:
    print('ERROR: No analysis_review phase log found. Run the pipeline first.')
    sys.exit(1)

outputs = json.loads(row[0])
id_map = outputs.get('detector_id_map', {})

# Zone 2 detectors we care about
z2 = {'temporal_drift', 'dimensional_entropy', 'column_quality', 'dimension_coverage', 'derived_value'}

print()
print('--- Column-scoped (Zone 2 detectors) ---')
for dim_path, targets in outputs.get('gate_column_details', {}).items():
    det = id_map.get(dim_path, dim_path.rsplit('.', 1)[-1])
    if det not in z2:
        continue
    for target, score in targets.items():
        flag = ' ✓' if score > 0.3 else ' ✗' if score > 0 else ''
        print(f'  {det:25s} {target:45s} {score:.3f}{flag}')

print()
print('--- Table-scoped ---')
for dim_path, targets in outputs.get('gate_table_details', {}).items():
    det = id_map.get(dim_path, dim_path.rsplit('.', 1)[-1])
    if det in ('overall_score',):
        continue
    for target, score in targets.items():
        flag = ' ✓' if score > 0.3 else ''
        print(f'  {det:25s} {target:30s} {score:.3f}{flag}')

print()
print('--- View-scoped ---')
for dim_path, targets in outputs.get('gate_view_details', {}).items():
    det = id_map.get(dim_path, dim_path.rsplit('.', 1)[-1])
    for target, score in targets.items():
        flag = ' ✓' if score > 0.3 else ''
        print(f'  {det:25s} {target:35s} {score:.3f}{flag}')

print()
print('--- Pytest (detection recall) ---')
print('Run: uv run pytest calibration/ --strategy ${STRATEGY} -v')
"
  echo ""

  # --- Step 4: Run pytest ---
  echo "=== Running calibration tests ==="
  uv run pytest calibration/test_detector_recall.py --strategy "${STRATEGY}" -v
fi
