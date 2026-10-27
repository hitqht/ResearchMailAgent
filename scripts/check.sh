#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
export UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}"
uv lock --check
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
QT_QPA_PLATFORM=offscreen uv run --locked pytest --cov --cov-report=term-missing --cov-report=xml
uv run --locked bandit -q -r src
uv run --locked python scripts/scan_secrets.py
