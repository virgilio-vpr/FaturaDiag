.PHONY: up down migrate seed lint types test check eval-extraction openapi report-sample

up:
	docker compose up -d --build

down:
	docker compose down

migrate:
	docker compose exec backend uv run alembic upgrade head

seed:
	docker compose exec backend uv run python -m app.scripts.seed

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run lint-imports

test:
	cd backend && uv run pytest --cov=app --cov-report=term-missing

openapi:
	cd backend && uv run python -m app.scripts.export_openapi > ../frontend/openapi.json

types: openapi
	cd frontend && npx openapi-typescript openapi.json -o src/api/schema.d.ts

check: lint test

eval-extraction:
	cd backend && uv run python -m app.scripts.eval_extraction

report-sample:
	cd backend && uv run python -m app.scripts.report_sample
