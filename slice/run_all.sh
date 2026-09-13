#!/usr/bin/env bash
# One re-run of everything on the same corpus and settings. Writes runtime/eval/runs/<run-id>/ so two runs can be compared.
# Requires: scripts/serve.sh (Open WebUI with the corpus ingested) and scripts/llm_server.sh start.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
RUN="${1:-run-$(date +%Y%m%d-%H%M%S)}"; OUT="runtime/eval/runs/$RUN"; mkdir -p "$OUT"
echo "run: $RUN"
.venv-hs231/bin/python slice/regression/run_bundle.py --label hs231 --out "$OUT/bundle-hs231.json"
.venv-hs31/bin/python  slice/regression/run_bundle.py --label hs31  --out "$OUT/bundle-hs31.json"
python3 slice/regression/diff_bundles.py "$OUT/bundle-hs231.json" "$OUT/bundle-hs31.json" --out "$OUT/diff.json" > /dev/null
.venv-hs31/bin/python slice/regression/explain.py "$OUT/diff.json" --out "$OUT/explain.json"
for split in dev eval; do
  .venv/bin/python eval/retrieval_eval.py --split "$split" --k 3 --out "$OUT/retrieval-$split.json" > /dev/null || true
done
git rev-parse --short HEAD > "$OUT/git.txt" 2>/dev/null || true
cp config/openwebui.env "$OUT/openwebui.env"
echo "done -> $OUT"
