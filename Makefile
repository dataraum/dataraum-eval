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

VENDOR_COMPOSE := vendor/dataraum-context/packages/infra/docker-compose.yml
# The eval stack runs as an ISOLATED docker project (own ports/volume) so it never
# touches the shared cockpit `infra` stack — clean-pg only wipes the eval project.
EVAL_PROJECT := dataraum-eval
EVAL_PORTS := calibration/compose.eval-ports.yml

# Wipe generated data, pipeline output, the local DuckLake parquet store,
# and the workspace overlay. Run `make clean-pg` separately for PG state.
clean:
	rm -rf data output lake_data workspace

# Drop the eval project's Postgres container + volume (wipes engine metadata for the
# ISOLATED eval stack only — never the shared cockpit `infra` stack).
clean-pg:
	docker compose -p $(EVAL_PROJECT) -f $(VENDOR_COMPOSE) -f $(EVAL_PORTS) --env-file .docker.env down -v

.PHONY: test list-strategies calibrate calibrate-typing clean clean-pg
