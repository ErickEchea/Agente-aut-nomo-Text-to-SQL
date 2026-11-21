# NEXUS AI — task runner. POSIX sh recipes (on Windows run from Git Bash).
SHELL := /bin/sh
.DEFAULT_GOAL := help

# Lazily evaluated once (detection starts a container, so it only runs for targets that need it).
PROFILE = $(eval PROFILE := $$(shell sh scripts/detect-profile.sh 2>/dev/null || echo cpu))$(PROFILE)
COMPOSE_FILES := -f docker-compose.yml $(if $(filter gpu,$(PROFILE)),-f docker-compose.gpu.yml,)
COMPOSE := docker compose $(COMPOSE_FILES)
ENV_VAL = $(shell sed -n 's/^$(1)=//p' .env 2>/dev/null)
LLM_MODEL = $(if $(filter gpu,$(PROFILE)),$(call ENV_VAL,NEXUS_LLM_MODEL_GPU),$(call ENV_VAL,NEXUS_LLM_MODEL_CPU))

BACKEND := cd backend &&
FRONTEND := cd frontend &&

.PHONY: help env up down restart clean ps logs seed reseed \
        install test test-unit test-integration test-security coverage e2e e2e-user e2e-agent eval-retrieval api-types create-user         lint format typecheck check hooks

help: ## List available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

env: ## Create .env with generated secrets (never overwrites)
	@sh scripts/init-env.sh

up: env ## Build and start the full stack, wait until every service is healthy
	@echo "Profile: $(PROFILE) — LLM: $(LLM_MODEL)"
	NEXUS_LLM_MODEL="$(LLM_MODEL)" $(COMPOSE) up -d --build --wait --wait-timeout 1800
	@$(COMPOSE) ps

down: ## Stop the stack (keeps data volumes)
	$(COMPOSE) down

restart: down up ## Restart the stack

clean: ## Stop the stack and DELETE all volumes (databases and downloaded models)
	$(COMPOSE) down -v --remove-orphans

ps: ## Show service status and health
	$(COMPOSE) ps

logs: ## Tail logs (all services, or s=<service>)
	$(COMPOSE) logs -f --tail=200 $(s)

seed: ## Load the demo data if missing or changed (idempotent)
	$(COMPOSE) run --rm demo-seed

reseed: ## Force regeneration and reload of the demo data
	$(COMPOSE) run --rm demo-seed nexus-seed-demo --force

install: ## Install backend and frontend dependencies for local development
	$(BACKEND) uv sync --frozen
	$(FRONTEND) npm ci

test: test-unit ## Run unit tests (backend + frontend)

test-unit: ## Backend and frontend unit tests
	$(BACKEND) uv run pytest -m "not integration and not llm"
	$(FRONTEND) npm run test

test-integration: ## Backend integration tests (Testcontainers; Docker required)
	$(BACKEND) uv run pytest -m integration

test-security: ## Attack suite: validator alone, DB layers alone, validator over a privileged role
	$(BACKEND) uv run pytest tests/security tests/integration/test_attack_suite_db.py tests/integration/test_demo_db_roles.py

coverage: ## All non-LLM tests + coverage gate (>= 85 % on agent, security and sql)
	$(BACKEND) uv run pytest --cov --cov-report= && uv run coverage report --fail-under=85 --include="src/nexus/agent/*,src/nexus/security/*,src/nexus/sql/*"

# Default selection skips the slow real-model specs; override, e.g. E2E_ARGS="--grep @llm --workers 1".
E2E_ARGS ?= --grep-invert @llm
E2E_ENV = NEXUS_E2E_EMAIL='$(call ENV_VAL,NEXUS_E2E_EMAIL)' NEXUS_E2E_PASSWORD='$(call ENV_VAL,NEXUS_E2E_PASSWORD)'

e2e-user: env ## Create the Playwright account from .env if it does not exist (stack up)
	@printf '%s\n' '$(call ENV_VAL,NEXUS_E2E_PASSWORD)' | $(COMPOSE) exec -T backend nexus-admin create-user \
	  --email '$(call ENV_VAL,NEXUS_E2E_EMAIL)' --name 'E2E Admin' --role admin --password-stdin --if-missing

e2e: e2e-user ## Playwright end-to-end tests: every screen, both themes, desktop + 375 px, axe (stack up)
	$(FRONTEND) $(E2E_ENV) npx playwright test $(E2E_ARGS)

e2e-agent: e2e-user ## Reference question with the real model: API (pytest) and browser (Playwright) (stack up)
	$(BACKEND) PYTHONIOENCODING=utf-8 uv run pytest tests/e2e -m llm -s
	$(FRONTEND) $(E2E_ENV) npx playwright test --grep @llm --workers 1

eval-retrieval: ## Measure schema retrieval (recall@5, completeness) per embedding model (stack up)
	$(BACKEND) NEXUS_APP_DB__HOST=127.0.0.1 NEXUS_APP_DB__PORT=$(call ENV_VAL,NEXUS_APP_DB_PORT) 	  NEXUS_APP_DB__NAME=nexus_app NEXUS_APP_DB__USER=nexus_app NEXUS_APP_DB__PASSWORD=$(call ENV_VAL,NEXUS_APP_DB_PASSWORD) 	  NEXUS_DEMO_DB__HOST=127.0.0.1 NEXUS_DEMO_DB__PORT=$(call ENV_VAL,NEXUS_DEMO_DB_PORT) NEXUS_DEMO_DB__NAME=retail 	  NEXUS_DEMO_DB__USER=nexus_reader NEXUS_DEMO_DB__PASSWORD=$(call ENV_VAL,NEXUS_DEMO_READER_PASSWORD) 	  NEXUS_OLLAMA__BASE_URL=http://127.0.0.1:$(call ENV_VAL,NEXUS_OLLAMA_PORT) PYTHONIOENCODING=utf-8 	  uv run nexus-eval-retrieval

create-user: ## Create a user: make create-user email=a@b.c name="Ana" role=analyst
	$(COMPOSE) exec backend nexus-admin create-user --email "$(email)" --name "$(name)" --role "$(role)"

api-types: ## Regenerate the OpenAPI snapshot and the frontend's TypeScript API types
	$(BACKEND) uv run python -m nexus.openapi ../frontend/src/api/openapi.json
	$(FRONTEND) npm run api:types

lint: ## Linters (ruff, eslint)
	$(BACKEND) uv run ruff check . && uv run ruff format --check .
	$(FRONTEND) npm run lint

format: ## Auto-format backend code
	$(BACKEND) uv run ruff format . && uv run ruff check --fix .

typecheck: ## Static type checks (mypy strict, tsc)
	$(BACKEND) uv run mypy
	$(FRONTEND) npm run typecheck

check: lint typecheck test ## Everything CI runs locally, except integration tests

hooks: ## Install pre-commit git hooks
	$(BACKEND) uv run pre-commit install --config ../.pre-commit-config.yaml
