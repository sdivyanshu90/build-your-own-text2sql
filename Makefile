# Text-to-SQL Engine — developer task runner.
# Run `make help` for the list of targets.

.DEFAULT_GOAL := help
PY ?= python
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: venv
venv: ## Create a virtualenv
	$(PY) -m venv $(VENV)

.PHONY: install
install: ## Install the package with dev extras (editable)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev]"

.PHONY: init-db
init-db: ## Create schema and load seed data (uses env config)
	$(BIN)/python scripts/init_db.py --drop --seed

.PHONY: migrate
migrate: ## Run Alembic migrations to head
	$(BIN)/alembic upgrade head

.PHONY: seed
seed: ## Load deterministic seed data
	$(BIN)/python scripts/seed.py --reset

.PHONY: run
run: ## Run the API (dev server)
	$(BIN)/uvicorn text_to_sql.main:app --reload --host 0.0.0.0 --port 8000

.PHONY: demo
demo: ## Run the example scenarios end-to-end
	$(BIN)/python scripts/run_examples.py

.PHONY: lint
lint: ## Ruff lint
	$(BIN)/ruff check src tests

.PHONY: format
format: ## Ruff format
	$(BIN)/ruff format src tests

.PHONY: typecheck
typecheck: ## mypy static type checking
	$(BIN)/mypy src

.PHONY: security-scan
security-scan: ## Bandit security scan
	$(BIN)/bandit -q -r src -c pyproject.toml

.PHONY: test
test: ## Run the full test suite with coverage
	$(BIN)/pytest --cov=text_to_sql --cov-report=term-missing --cov-report=xml

.PHONY: test-fast
test-fast: ## Run unit + security tests only
	$(BIN)/pytest -m "unit or security" -q

.PHONY: eval
eval: ## Run the golden evaluation harness
	$(BIN)/python -m tests.golden.run_eval

.PHONY: check
check: lint typecheck security-scan test ## Run all quality gates

.PHONY: docker-up
docker-up: ## Start the full stack (Postgres + API) via Docker Compose
	docker compose up --build

.PHONY: docker-down
docker-down: ## Stop the Docker Compose stack
	docker compose down -v

.PHONY: clean
clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache .hypothesis htmlcov .coverage coverage.xml
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
