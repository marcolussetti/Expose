# Dorothea Makefile
# Common development tasks using uv

.PHONY: help test test-cov test-fast clean install lint format typecheck try compare package-check ci-local

help:
	@echo "Available commands:"
	@echo "  make test       - Run all tests"
	@echo "  make test-cov   - Run tests with coverage report"
	@echo "  make test-fast  - Run tests without slow/parity tests"
	@echo "  make clean      - Clean generated files and caches"
	@echo "  make install    - Install dependencies with uv"
	@echo "  make lint       - Run all pre-commit hooks (via prek): ruff, format, ty"
	@echo "  make typecheck  - Type-check src/ with ty"
	@echo "  make format     - Format code (via prek ruff-format)"
	@echo "  make install-hooks - Install prek hooks"
	@echo ""
	@echo "Manual checks (work in .sandbox/, which is gitignored):"
	@echo "  make try [GALLERY=dir] [ARGS=\"-d ...\"]  - Build a fresh copy of a gallery with this checkout"
	@echo "  make compare [GALLERY=dir]                - Build a copy with expose.sh and Dorothea (draft) and diff them"
	@echo "  make package-check                        - Build the wheel/sdist and run them via uvx and pipx"
	@echo "  make ci-local                             - Run every CI job locally with act"

# Run all tests
test:
	uv run pytest tests/ --no-cov

# Run tests with coverage
test-cov:
	@rm -rf .coverage htmlcov
	uv run pytest tests/ --cov=src/dorothea --cov-report=term --cov-report=html

# Run only fast tests (skip slow parity tests)
test-fast:
	uv run pytest tests/ -m "not slow" --no-cov

# Run only parity tests
test-parity:
	uv run pytest tests/ -m "slow" --no-cov

# Clean generated files
clean:
	@rm -rf .coverage htmlcov .pytest_cache
	@rm -rf tests/__pycache__ tests/.pytest_cache
	@find tests -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Install dependencies
install:
	uv pip install -e ".[dev]"

# Install pre-commit hooks (via prek)
install-hooks:
	prek install-hooks

# Run all pre-commit hooks on all files (via prek)
lint:
	prek run --all-files

# Type-check with ty
typecheck:
	uv run ty check src

# Format code only (via prek ruff-format hook)
format:
	prek run ruff-format --all-files

# Run full CI checks locally
ci: clean lint test-cov

# --- Manual checks -------------------------------------------------------------------------
# Throwaway work happens in $(SANDBOX); GALLERY defaults to the real-photo test gallery.
SANDBOX ?= .sandbox
GALLERY ?= tests/data/test_run
ARGS ?= -d

# Copy GALLERY into $(SANDBOX)/<name> without its _site or build cache
define fresh_copy
	@rm -rf $(SANDBOX)/$(1) && mkdir -p $(SANDBOX)/$(1)
	@cp -r "$(GALLERY)"/. $(SANDBOX)/$(1)/
	@rm -rf $(SANDBOX)/$(1)/_site $(SANDBOX)/$(1)/.dorothea-cache.json
endef

# Build a fresh copy of GALLERY with this checkout: make try ARGS="-d --ffmpeg bundled"
try:
	$(call fresh_copy,try)
	cd $(SANDBOX)/try && uv run --project "$(CURDIR)" dorothea $(ARGS)
	@echo "--- $(SANDBOX)/try/_site:"
	@find $(SANDBOX)/try/_site -mindepth 1 -maxdepth 2 -type d ! -path '*/img*' | sort

# Build GALLERY with expose.sh and with Dorothea (draft mode) and compare like the parity tests
compare:
	$(call fresh_copy,compare-shell)
	$(call fresh_copy,compare-python)
	cd $(SANDBOX)/compare-shell && bash "$(CURDIR)/tests/reference/expose.sh" -d > /dev/null
	cd $(SANDBOX)/compare-python && uv run --project "$(CURDIR)" dorothea -d > /dev/null
	uv run python -c "import sys; from pathlib import Path; \
	from tests.test_final_parity import compare_directories as c; \
	d = c(Path('$(SANDBOX)/compare-shell/_site'), Path('$(SANDBOX)/compare-python/_site')); \
	print('\n'.join(d) or 'No differences'); sys.exit(1 if d else 0)"

# Build the wheel and sdist, then run them the way users will (like the CI package job)
package-check:
	@rm -rf $(SANDBOX)/dist && uv build -q --out-dir $(SANDBOX)/dist
	uvx --isolated --from "$$(ls $(SANDBOX)/dist/*.whl)" dorothea --version
	uvx --isolated --from "$$(ls $(SANDBOX)/dist/*.whl)" expose --version
	uvx pipx run --no-cache --python 3.14 --fetch-python=missing --spec "$$(ls $(SANDBOX)/dist/*.whl)" dorothea --version
	$(call fresh_copy,package)
	cd $(SANDBOX)/package && uvx --isolated --from "$$(ls $(CURDIR)/$(SANDBOX)/dist/*.whl)" dorothea -d > /dev/null
	@test -s $(SANDBOX)/package/_site/index.html && echo "OK: built a gallery from the wheel"

# Run every CI job locally with act (needs docker)
ci-local:
	act -P ubuntu-latest=catthehacker/ubuntu:act-latest
