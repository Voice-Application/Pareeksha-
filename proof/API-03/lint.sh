#!/usr/bin/env bash
# Run from backend/:  ../proof/API-03/lint.sh > ../proof/API-03/lint.txt 2>&1
set -u
echo '$ ruff check .'
ruff check .
echo '$ ruff format --check .'
ruff format --check .
echo '$ python3 -m mypy'
python3 -m mypy
