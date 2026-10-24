#!/usr/bin/env bash
# Reproduce: ./proof/INFRA-02/lint.sh > proof/INFRA-02/lint.txt 2>&1   (from the repo root)
cd "$(dirname "$0")/../../backend" || exit 1
echo '$ ruff check .';        ruff check .
echo; echo '$ ruff format --check .'; ruff format --check .
echo; echo '$ python -m mypy   (strict; files = pareeksha tests)'; python3 -m mypy
