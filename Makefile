# Calibration convenience targets
#
# Usage:
#   make generate-zone1-detection-v1   # Generate test data
#   make pipeline-zone1-detection-v1   # Run pipeline
#   make run-zone1-detection-v1        # Generate + pipeline
#   make test                          # Run tests (default strategy)
#   make test STRATEGY=baseline        # Run tests with specific strategy
#   make calibrate-zone1-detection-v1  # Generate + pipeline + test

STRATEGY ?= zone1-detection-v1
SEED ?= 42

# Generate test data for a strategy
generate-%:
	uv run python -m calibration.runner $* --generate-only --seed $(SEED)

# Run pipeline on generated data
pipeline-%:
	uv run python -m calibration.runner $* --pipeline-only

# Generate + pipeline
run-%: generate-% pipeline-%
	@echo "Run complete for $*"

# Run calibration tests
test:
	uv run pytest calibration/ --strategy $(STRATEGY)

# Full loop: generate + pipeline + test
calibrate-%: run-%
	uv run pytest calibration/ --strategy $* -v

# List available strategies
list-strategies:
	@ls strategies/*.yaml 2>/dev/null | xargs -I{} basename {} .yaml

.PHONY: test list-strategies
