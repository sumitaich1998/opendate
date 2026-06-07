.PHONY: help install test lint format demo clean

PYTHON ?= python3

help:
	@echo "OpenDate — make targets:"
	@echo "  make install   Editable install with dev extras"
	@echo "  make test      Run the offline test suite (pytest)"
	@echo "  make lint      Lint with ruff"
	@echo "  make format    Auto-format with ruff"
	@echo "  make demo      Run one offline --mock loop cycle (sends nothing)"
	@echo "  make clean     Remove caches and build artifacts"

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format .

demo:
	$(PYTHON) -m opendate --mock run --cycles 1 --no-interactive

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
