"""Verify a LIVE pipeline run consumed the shipped reliabilities artifact (DAT-450).

The rig + unit tests prove the values and the seam in isolation; this proves the
last leg end-to-end — that a real ``addSourceWorkflow`` loaded
``reliabilities.yaml`` and persisted ``ClaimWitnessRecord`` rows whose
``reliability`` equals the SHIPPED calibrated values, not the inline fallback.

    python scripts/check_reliability_consumption.py [strategy]   # default: detection-null-v1

Reads the run's session_id from the sidecar, queries claim_witnesses, and compares
the persisted per-witness reliabilities against the artifact loader.
"""

from __future__ import annotations

import sys

from dataraum.entropy.measurements.null_semantics import DEFAULT_RELIABILITIES
from dataraum.entropy.reliabilities import get_reliability_config, reset_reliability_config_cache

from calibration import runner as runner_mod


def main() -> int:
    strategy = sys.argv[1] if len(sys.argv) > 1 else "detection-null-v1"
    sidecar = runner_mod.sidecar_path(strategy)
    if not sidecar.exists():
        print(f"no sidecar for {strategy} — run the pipeline first")
        return 2
    run = runner_mod.CalibrationRun.from_json(sidecar.read_text())

    runner_mod.bootstrap_engine()
    reset_reliability_config_cache()
    shipped = get_reliability_config().for_measurement("null_semantics")
    fallback = {k: float(v) for k, v in DEFAULT_RELIABILITIES.items()}

    from dataraum.core.connections import ConnectionConfig, ConnectionManager
    from dataraum.entropy.db_models import ClaimWitnessRecord
    from sqlalchemy import select

    mgr = ConnectionManager(ConnectionConfig.for_workspace())
    mgr.initialize()
    try:
        with mgr.session_scope() as session:
            rows = list(
                session.execute(
                    select(ClaimWitnessRecord).where(
                        ClaimWitnessRecord.session_id == run.session_id,
                        ClaimWitnessRecord.detector_id == "null_semantics",
                    )
                ).scalars()
            )
    finally:
        mgr.close()

    if not rows:
        print(f"NO claim_witnesses rows for session {run.session_id} — null_semantics never fired")
        return 1

    # distinct persisted reliability per witness_id
    persisted: dict[str, set[float]] = {}
    for r in rows:
        persisted.setdefault(r.witness_id, set()).add(round(float(r.reliability), 4))

    print(f"strategy={strategy} session={run.session_id}  claim_witness rows={len(rows)}")
    print(f"shipped artifact:  {shipped}")
    print(f"inline fallback:   {fallback}")
    ok = True
    for witness_id, values in sorted(persisted.items()):
        expected = round(shipped.get(witness_id, -1), 4)
        match = values == {expected}
        is_fallback = values == {round(fallback.get(witness_id, -2), 4)}
        flag = "OK" if match else ("FALLBACK!" if is_fallback else "MISMATCH!")
        ok = ok and match
        print(f"  {witness_id:<22} persisted={sorted(values)}  expected={expected}  [{flag}]")

    print("\n" + ("PASS — live run consumed the shipped calibrated artifact" if ok
                  else "FAIL — persisted reliabilities are not the shipped values"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
