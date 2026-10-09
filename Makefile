.PHONY: dev-api dev-web test lint build up down cli

dev-api: ## Backend with autoreload on :8080
	cd backend && uv run uvicorn app.main:app --reload --port 8080

dev-web: ## Vite dev server (proxies /api to :8080)
	cd frontend && npm run dev

test: ## Backend tests
	cd backend && uv run pytest -q

lint:
	cd backend && uv run ruff check .

build: ## Build the Docker image
	docker compose build

up: ## Run the container
	docker compose up -d

down:
	docker compose down

cli: ## e.g. make cli ARGS="list"
	cd backend && uv run python cli.py $(ARGS)
