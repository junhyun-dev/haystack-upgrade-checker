#!/usr/bin/env bash
# Approved downloads (2026-09-11, user decision "후보 B 수용 … 일단 진행"): local LLM server + small models. Zero cost, no accounts.
#  L1  llama.cpp b10894 Ubuntu x64 CPU binary (MIT, 16.8MB)                 -> runtime/llama.cpp/
#  L1  Qwen/Qwen3-4B-GGUF Qwen3-4B-Q4_K_M.gguf (Apache-2.0, 2.5GB)          -> runtime/models/
#  E1  sentence-transformers/all-MiniLM-L6-v2 (Apache-2.0, 90.9MB)          -> runtime/cache/models/ (HF cache layout)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
mkdir -p runtime/llama.cpp runtime/models runtime/cache/models
LLAMA_TAG="b10894"
if [[ ! -x runtime/llama.cpp/llama-server ]]; then
  curl -L --fail --retry 3 -o runtime/llama.cpp/llama.tar.gz \
    "https://github.com/ggml-org/llama.cpp/releases/download/${LLAMA_TAG}/llama-${LLAMA_TAG}-bin-ubuntu-x64.tar.gz"
  tar -xzf runtime/llama.cpp/llama.tar.gz -C runtime/llama.cpp --strip-components=1
  rm -f runtime/llama.cpp/llama.tar.gz
  echo "$LLAMA_TAG" > runtime/llama.cpp/VERSION
fi
if [[ ! -f runtime/models/Qwen3-4B-Q4_K_M.gguf ]]; then
  curl -L --fail --retry 5 -C - -o runtime/models/Qwen3-4B-Q4_K_M.gguf.part \
    "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf"
  mv runtime/models/Qwen3-4B-Q4_K_M.gguf.part runtime/models/Qwen3-4B-Q4_K_M.gguf
fi
HF_HOME="$ROOT/runtime/cache/models" HF_HUB_OFFLINE=0 .venv/bin/python - <<'PY'
from huggingface_hub import snapshot_download
p = snapshot_download("sentence-transformers/all-MiniLM-L6-v2", allow_patterns=["*.json","*.txt","model.safetensors","1_Pooling/*"])
print("embedding model at", p)
PY
echo MODELS_DONE
