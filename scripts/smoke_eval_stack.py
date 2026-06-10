"""Smoke: bring up the ISOLATED eval stack and confirm it coexists with cockpit's infra.

Verifies the DAT-445 shared-stack isolation: the calibration stack runs as its own
docker project (`dataraum-eval`) on remapped host ports (5433/7234/8334), alongside —
not on top of — the shared `infra`/cockpit stack.
"""

from __future__ import annotations

from calibration import stack

stack.up()
print(
    f"[smoke] eval stack healthy — postgres:{stack.POSTGRES_PORT} "
    f"temporal:{stack.TEMPORAL_PORT} s3:{stack.S3_PORT} project:{stack.EVAL_PROJECT}"
)
