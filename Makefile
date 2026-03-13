# Calibration convenience targets
#
# Usage:
#   make generate-zone1-detection-v1   # Generate test data
#   make pipeline-zone1-detection-v1   # Run pipeline
#   make run-zone1-detection-v1        # Generate + pipeline
#   make test                          # Run tests (default strategy)
#   make test STRATEGY=baseline        # Run tests with specific strategy
#   make calibrate-zone1-detection-v1  # Generate + pipeline + test
#   make fix-zone1-detection-v1        # Apply fixes + re-run pipeline
#   make test-fix                      # Run fix calibration tests
#   make calibrate-fix-zone1-detection-v1  # Full loop + fix + test-fix

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

# Run calibration tests (recall + precision)
test:
	uv run pytest calibration/ --strategy $(STRATEGY) -v

# Full loop: generate + pipeline + test
calibrate-%: run-%
	uv run pytest calibration/ --strategy $* -v

# Full calibration including clean baseline for precision tests
calibrate-full: run-clean run-$(STRATEGY)
	uv run pytest calibration/ --strategy $(STRATEGY) -v

# Apply fixes and re-run pipeline
fix-%:
	uv run python -m calibration.runner $* --apply-fixes

# Run fix calibration tests
test-fix:
	uv run pytest calibration/test_fix_calibration.py --strategy $(STRATEGY) -v

# Full loop: generate + pipeline + test + fix + test-fix
calibrate-fix-%: calibrate-%
	uv run python -m calibration.runner $* --apply-fixes
	uv run pytest calibration/test_fix_calibration.py --strategy $* -v

# List available strategies
list-strategies:
	@ls strategies/*.yaml 2>/dev/null | xargs -I{} basename {} .yaml

.PHONY: test test-fix list-strategies
