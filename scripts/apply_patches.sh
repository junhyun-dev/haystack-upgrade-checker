#!/usr/bin/env bash
# Apply this project's local patches to the installed open-webui package in .venv (upstream wheel 0.11.3 + patches/*.patch).
# Each patch is small, flag-gated, and reversible with: scripts/apply_patches.sh --reverse
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
SITE="$(.venv/bin/python -c 'import open_webui,os; print(os.path.dirname(os.path.dirname(open_webui.__file__)))')"
for p in patches/*.patch; do
  if [[ "${1:-}" == "--reverse" ]]; then patch -R -p1 -d "$SITE" < "$p" && echo "reversed $p"
  else patch -N -p1 -d "$SITE" < "$p" && echo "applied $p"; fi
done
