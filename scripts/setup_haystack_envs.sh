#!/usr/bin/env bash
# Two isolated Haystack environments for the change-diagnosis Slice (candidate B): 2.31.0 (last 2.x) and 3.1.1 (current).
# Core package only; no torch, no model downloads. BM25 retrieval is in core for both versions.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
for spec in "hs231:haystack-ai==2.31.0" "hs31:haystack-ai==3.1.1"; do
  name="${spec%%:*}"; pkg="${spec#*:}"
  [[ -d ".venv-$name" ]] || python3.12 -m venv ".venv-$name"
  ".venv-$name/bin/pip" install --quiet --upgrade pip
  ".venv-$name/bin/pip" install --quiet "$pkg" pyyaml
  ".venv-$name/bin/python" -c "import haystack; print('$name', haystack.__version__)"
done
echo HS_ENVS_DONE
