---
name: python-test-runner
description: Run and validate the Python test suite in this repo using pytest, including coverage and targeted test selection. Use when a task involves Python code, tests, or CI gate verification.
---

# Python Test Runner

Use this skill whenever a beat involves Python code, test execution, or verifying the
CI test gate (`test-gate.yml`).

## Steps

1. Detect the project layout:
   - `pyproject.toml` / `setup.py` / `requirements.txt` → Python package
   - `tests/` or `test_*.py` → test files
2. Install dependencies:
   ```bash
   pip install pytest
   if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
   if [ -f pyproject.toml ]; then pip install -e .; fi
   ```
3. Run the full suite:
   ```bash
   python -m pytest -q
   ```
4. On failure, triage:
   - Read the first failure's traceback and the assertion message.
   - Fix the code (Maker role) or report (Checker role).
   - Re-run the specific failing test only: `python -m pytest -q <file>::<test> -x`
5. Check coverage when a code change is substantive:
   ```bash
   python -m pytest --cov=. --cov-report=term-missing -q
   ```
   (Only if `pytest-cov` is installed; never add deps without noting it.)

## Gate rule

A PR is not mergeable until `python -m pytest -q` exits 0 AND the Checker (and, for
code changes, the adversarial Checker per AGENTS.md §5) approves. If no tests exist yet,
say so and add tests in the same PR when feasible.
