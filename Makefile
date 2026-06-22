# Calibration — ONE runner. Full help: uv run python -m calibration.run --help
#
#   uv run python -m calibration.run -s detection-v1,clean   # run these + assert
#   uv run python -m calibration.run --all                   # every strategy
#   uv run python -m calibration.run -s detection-v1 --no-assert
#
# It brings the stack up ONCE (never `down -v`), runs each strategy in its own
# workspace, kills any leaked worker, then asserts. These make targets are thin
# conveniences over that one command.

STRATEGY ?= detection-v1

# Run `clean` + STRATEGY (override: make calibrate STRATEGY=detection-typing-v1), then assert.
calibrate:
	uv run python -m calibration.run -s clean,$(STRATEGY)

# Run every strategy in strategies/.
calibrate-all:
	uv run python -m calibration.run --all

list:
	uv run python -m calibration.run --list

# Wipe local generated dirs (data/ output/ lake_data/ workspace/). PG/Temporal untouched.
clean:
	rm -rf data output lake_data workspace

# Tear down the ISOLATED eval stack + volume (the ONLY `down -v`; never the shared cockpit
# `infra` stack). Use when the stack state is wedged — not part of a normal run.
reset:
	uv run python -m calibration.run --reset

.PHONY: calibrate calibrate-all list clean reset
