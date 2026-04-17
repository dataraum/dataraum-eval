# Calibration convenience targets
#
# Usage:
#   make calibrate                         # Full: clean + detection-v1 + test
#   make calibrate-typing                  # Full: clean + detection-typing-v1 + test
#   make test                              # Run tests (default strategy)
#   make test STRATEGY=detection-typing-v1 # Run tests with specific strategy

STRATEGY ?= detection-v1
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

# Run calibration tests (recall + precision)
test:
	uv run pytest calibration/ --strategy $(STRATEGY) -v

# Full loop: generate + pipeline + test
calibrate: run-clean run-$(STRATEGY)
	uv run pytest calibration/ --strategy $(STRATEGY) -v

# Type-breaking calibration
calibrate-typing: run-clean run-detection-typing-v1
	uv run pytest calibration/ --strategy detection-typing-v1 -v

# List available strategies
list-strategies:
	@ls strategies/*.yaml 2>/dev/null | xargs -I{} basename {} .yaml

.PHONY: test list-strategies calibrate calibrate-typing
