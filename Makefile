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
        install test test-unit test-integration test-security coverage audit audit-deps audit-secrets audit-images load load-users demo-gif e2e e2e-user e2e-agent eval-retrieval bench bench-freeze bench-report bench-ci api-types sqlite-demo rotate-keys create-user         lint format typecheck check hooks

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

# Security audit (ADR-0023): pinned tool versions and image digests; CI runs these same targets.
PIP_AUDIT := pip-audit@2.10.1
GITLEAKS_IMAGE := zricethezav/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f
TRIVY_IMAGE := aquasec/trivy:0.76.2@sha256:8f6bb947dbc528902e11f2f5be52f7b519f6a39d5d148f41166f2040499768fb
IMAGE_TAG ?= local
# Fixable HIGH/CRITICAL vulnerabilities fail the target.
TRIVY = MSYS_NO_PATHCONV=1 docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v nexus-trivy-cache:/root/.cache/trivy \
	$(TRIVY_IMAGE) image --quiet --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1

audit: audit-deps audit-secrets audit-images ## Dependency, secret and image audit (images from `make up`)

audit-deps: ## Known vulnerabilities in the locked Python and npm dependencies (pip-audit, npm audit)
	req=$$(mktemp) && (cd backend && uv export --frozen --no-emit-project --quiet -o "$$req") \
	  && uvx $(PIP_AUDIT) -r "$$req" --disable-pip --progress-spinner off; status=$$?; rm -f "$$req"; exit $$status
	$(FRONTEND) npm audit --audit-level=high

audit-secrets: ## Secrets anywhere in the git history (gitleaks)
	MSYS_NO_PATHCONV=1 docker run --rm -v "$(CURDIR):/repo:ro" \
	  -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0=/repo \
	  $(GITLEAKS_IMAGE) git /repo --redact --no-banner

audit-images: ## Fixable HIGH/CRITICAL CVEs in the images this repo builds (Trivy; IMAGE_TAG=local)
	$(TRIVY) nexus-backend:$(IMAGE_TAG)
	$(TRIVY) nexus-frontend:$(IMAGE_TAG)
	@# gosu only drops privileges in the PostgreSQL entrypoint; its maintainers document why the Go
	@# standard-library CVEs scanners report in it do not apply (https://github.com/tianon/gosu).
	$(TRIVY) --skip-files /usr/local/bin/gosu nexus-demo-db:$(IMAGE_TAG)

# Default selection skips the slow real-model specs (@llm, and the @demo recording); override, e.g.
# E2E_ARGS="--grep @llm --workers 1".
E2E_ARGS ?= --grep-invert "@llm|@demo"
E2E_ENV = NEXUS_E2E_EMAIL='$(call ENV_VAL,NEXUS_E2E_EMAIL)' NEXUS_E2E_PASSWORD='$(call ENV_VAL,NEXUS_E2E_PASSWORD)'

e2e-user: env ## Create the Playwright account from .env if it does not exist (stack up)
	@printf '%s\n' '$(call ENV_VAL,NEXUS_E2E_PASSWORD)' | $(COMPOSE) exec -T backend nexus-admin create-user \
	  --email '$(call ENV_VAL,NEXUS_E2E_EMAIL)' --name 'E2E Admin' --role admin --password-stdin --if-missing

e2e: e2e-user data/sqlite/retail_mini.sqlite ## Playwright end-to-end tests: every screen, both themes, desktop + 375 px, axe (stack up)
	$(FRONTEND) $(E2E_ENV) npx playwright test $(E2E_ARGS)

e2e-agent: e2e-user ## Reference question with the real model: API (pytest) and browser (Playwright) (stack up)
	$(BACKEND) PYTHONIOENCODING=utf-8 uv run pytest tests/e2e -m llm -s
	$(FRONTEND) $(E2E_ENV) npx playwright test --grep @llm --workers 1

demo-gif: e2e-user ## Record the reference question + follow-up with the real model -> docs/assets/demo.gif (stack up, ffmpeg)
	$(FRONTEND) $(E2E_ENV) npx playwright test --grep @demo --project desktop --workers 1
	node scripts/demo-gif.mjs frontend/test-results/demo/demo.json docs/assets/demo.gif

# Benchmark CLI inside the backend image (same code, roles and Ollama as the API), bench/ and docs/ mounted
# (MSYS_NO_PATHCONV keeps Git Bash from rewriting the ./bench:/app/bench volume spec on Windows).
BENCH_RUN = MSYS_NO_PATHCONV=1 $(COMPOSE) run --rm --no-deps -v ./bench:/app/bench -v ./docs:/app/docs -e PYTHONIOENCODING=utf-8 backend
MODELS ?=
CONFIGS ?= qwen2.5-coder-7b qwen3-8b gemma4-e4b routed-qwen3-coder
SUBSET ?= full
BENCH_HARDWARE ?= NVIDIA RTX 5060 Laptop (8 GB VRAM), Ollama 0.40.16, Windows 11 + Docker Desktop

bench-freeze: ## Execute the gold SQL (validated, read-only) and freeze bench/golden/expected.json (stack up)
	$(BENCH_RUN) nexus-bench freeze

bench: ## Golden-set benchmark -> bench/results + docs/benchmark.md (CONFIGS="...", MODELS="...", SUBSET=full|ci|ids)
	$(BENCH_RUN) nexus-bench run $(if $(strip $(CONFIGS)),--configs $(CONFIGS),) $(if $(strip $(MODELS)),--models $(MODELS),) \
	  --subset $(SUBSET) --git-sha "$$(git rev-parse --short HEAD)"
	$(MAKE) bench-report

bench-report: ## Render docs/benchmark.md from bench/results
	$(BENCH_RUN) nexus-bench report --hardware "$(BENCH_HARDWARE)"

bench-ci: ## CI subset on the CPU model and the calibrated accuracy gate (stack up)
	$(BENCH_RUN) nexus-bench run --configs qwen2.5-coder-3b --subset ci --git-sha "$$(git rev-parse --short HEAD)"
	$(BENCH_RUN) nexus-bench check

LOAD_USERS ?= 4

load-users: env ## Create the load-test analyst accounts load-1..N@nexus.local if missing (stack up)
	@for i in $$(seq 1 $(LOAD_USERS)); do \
	  printf '%s\n' '$(call ENV_VAL,NEXUS_LOAD_PASSWORD)' | $(COMPOSE) exec -T backend nexus-admin create-user \
	    --email "load-$$i@nexus.local" --name "Load $$i" --role analyst --password-stdin --if-missing || exit 1; \
	done

load: load-users ## Load sanity check (k6): browsing while LOAD_USERS ask the agent -> docs/load-test.md (stack up)
	MSYS_NO_PATHCONV=1 $(COMPOSE) --profile tools run --rm -e LOAD_USERS=$(LOAD_USERS) \
	  -e NEXUS_LLM_MODEL="$(LLM_MODEL)" -e LOAD_HARDWARE="$(BENCH_HARDWARE)" k6 run /scripts/smoke.js

eval-retrieval: ## Measure schema retrieval (recall@5, completeness) per embedding model (stack up)
	$(BACKEND) NEXUS_APP_DB__HOST=127.0.0.1 NEXUS_APP_DB__PORT=$(call ENV_VAL,NEXUS_APP_DB_PORT) 	  NEXUS_APP_DB__NAME=nexus_app NEXUS_APP_DB__USER=nexus_app NEXUS_APP_DB__PASSWORD=$(call ENV_VAL,NEXUS_APP_DB_PASSWORD) 	  NEXUS_DEMO_DB__HOST=127.0.0.1 NEXUS_DEMO_DB__PORT=$(call ENV_VAL,NEXUS_DEMO_DB_PORT) NEXUS_DEMO_DB__NAME=retail 	  NEXUS_DEMO_DB__USER=nexus_reader NEXUS_DEMO_DB__PASSWORD=$(call ENV_VAL,NEXUS_DEMO_READER_PASSWORD) 	  NEXUS_OLLAMA__BASE_URL=http://127.0.0.1:$(call ENV_VAL,NEXUS_OLLAMA_PORT) PYTHONIOENCODING=utf-8 	  uv run nexus-eval-retrieval

create-user: ## Create a user: make create-user email=a@b.c name="Ana" role=analyst
	$(COMPOSE) exec backend nexus-admin create-user --email "$(email)" --name "$(name)" --role "$(role)"

sqlite-demo: ## Export the retail demo as data/sqlite/retail_mini.sqlite (a second engine to register)
	$(BACKEND) uv run nexus-export-sqlite --out ../data/sqlite/retail_mini.sqlite --sql-dir ../data/retail --scale 0.1

# Built on demand by targets that need a SQLite source (e2e registers it as a second engine).
data/sqlite/retail_mini.sqlite:
	$(MAKE) sqlite-demo

rotate-keys: ## Re-encrypt connection secrets with the newest NEXUS_CREDENTIALS_KEYS key (stack up)
	$(COMPOSE) exec backend nexus-admin rotate-keys

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
