#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
export PIP_CACHE_DIR="$PWD/cache/pip"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python setup_model.py "$@"
.venv/bin/python transcribe.py --preflight
