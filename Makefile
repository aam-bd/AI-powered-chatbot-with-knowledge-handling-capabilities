.PHONY: up down logs test eval lint

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

test:
	docker compose exec api pytest tests/ -v

eval:
	docker compose exec api python -m eval.run_eval

lint:
	docker compose exec api ruff check app/ || flake8 app/ || python -m compileall app/
