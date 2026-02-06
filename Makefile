# PyExpose Makefile
# Common development tasks using uv

.PHONY: help test test-cov test-fast clean install lint format

help:
	@echo "Available commands:"
	@echo "  make test       - Run all tests"
	@echo "  make test-cov   - Run tests with coverage report"
	@echo "  make test-fast  - Run tests without slow/parity tests"
	@echo "  make clean      - Clean generated files and caches"
	@echo "  make install    - Install dependencies with uv"
	@echo "  make lint       - Run linting (ruff)"
	@echo "  make format     - Format code (ruff)"
	@echo "  make install-hooks - Install prek hooks"

# Run all tests
test:
	uv run pytest tests/ --no-cov

# Run tests with coverage
test-cov:
	@rm -rf .coverage htmlcov
	uv run pytest tests/ --cov=expose --cov-report=term --cov-report=html

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

# Run linting (requires ruff)
lint:
	uv run ruff check .

# Format code (requires ruff)
format:
	uv run ruff format .

# Run full CI checks locally
ci: clean lint test-cov
