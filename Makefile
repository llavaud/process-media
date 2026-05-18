PYTHON ?= python3
VENV   := .venv
BIN    := $(VENV)/bin
PIP    := $(BIN)/pip
PYBIN  := $(BIN)/python

SRC    := src tests

.DEFAULT_GOAL := help

.PHONY: help venv install test lint format check clean

help:  ## Show this help
	@awk 'BEGIN{FS=":.*##"; printf "Available targets:\n\n"} \
	     /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}' \
	     $(MAKEFILE_LIST)

venv: $(BIN)/activate  ## Create the virtual environment (idempotent)

$(BIN)/activate:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip

install: venv  ## Install the package in editable mode with dev extras
	$(PIP) install -e ".[dev]"

test: install  ## Run the test suite
	$(BIN)/pytest -q

lint: install  ## Lint with ruff
	$(BIN)/ruff check $(SRC)

format: install  ## Format with ruff
	$(BIN)/ruff format $(SRC)

check: lint test  ## Run lint and tests

clean:  ## Remove the virtual environment and cache artefacts
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache .coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name '*.egg-info' -prune -exec rm -rf {} +
