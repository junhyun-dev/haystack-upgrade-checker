#!/usr/bin/env bash
# Shallow, single-tag checkout of the upstream source for reading and local patches. Never pushed anywhere.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
TAG="${1:-v0.11.3}"
[[ -d vendor/open-webui ]] && { echo "vendor/open-webui exists"; exit 0; }
git clone --depth 1 --branch "$TAG" --single-branch https://github.com/open-webui/open-webui.git vendor/open-webui
