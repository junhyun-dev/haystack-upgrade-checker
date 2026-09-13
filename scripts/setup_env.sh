#!/usr/bin/env bash
# Reproduce the isolated environment: Python 3.12 venv, CPU-only torch, open-webui pinned to 0.11.3.
# Downloads Python packages only. No model files are downloaded (see config/openwebui.env, OFFLINE_MODE).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3.12 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip wheel
pip install --index-url https://download.pytorch.org/whl/cpu torch
pip install open-webui==0.11.3
