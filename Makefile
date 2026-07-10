# Eidetic — common tasks. Activate the venv first (source .venv/Scripts/activate),
# or override PYTHON, e.g.  make demo PYTHON=./.venv/Scripts/python.exe
PYTHON ?= python

.PHONY: install demo test lint fmt

install:
	$(PYTHON) -m pip install -e ".[dev]"

## demo: the flagship fork-and-fix loop — records a "cold" run, forks it, prints "warm"
demo:
	$(PYTHON) examples/fork_demo.py

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check . && $(PYTHON) -m mypy src

fmt:
	$(PYTHON) -m ruff check . --fix
