"""Map each strategy name to its workspace schema, so a census names the right run."""

from __future__ import annotations

from calibration.runner import workspace_id_for

for strategy in ("clean", "clean-flat", "detection-v1", "detection-typing-v1", "rel-f1"):
    ws = workspace_id_for(strategy)
    print(f"{strategy:<22} ws_{ws.replace('-', '_')}")
