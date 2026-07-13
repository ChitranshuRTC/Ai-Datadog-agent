.PHONY: run test lint docker clean

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	python -m pytest

lint:
	ruff check app tests
	python -m compileall -q app tests

docker:
	docker compose up --build

clean:
	python -c "import shutil; [shutil.rmtree(path, ignore_errors=True) for path in ['.pytest_cache', '__pycache__']]"
