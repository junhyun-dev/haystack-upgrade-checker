#!/usr/bin/env bash
# Public document bundle: Haystack versioned docs 2.31 and 3.1 plus MIGRATION.md (Apache-2.0), pinned by commit.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p corpus && cd corpus
if [[ ! -d haystack-docs-src ]]; then
  git clone --depth 1 --filter=blob:none --sparse https://github.com/deepset-ai/haystack.git haystack-docs-src
fi
cd haystack-docs-src
git sparse-checkout set docs-website/versioned_docs/version-2.31 docs-website/versioned_docs/version-3.1
COMMIT="$(git rev-parse HEAD)"; echo "$COMMIT" > ../haystack-docs-src.commit
cd ..
curl -sL "https://raw.githubusercontent.com/deepset-ai/haystack/$COMMIT/MIGRATION.md" -o MIGRATION.md
curl -sL "https://raw.githubusercontent.com/deepset-ai/haystack/$COMMIT/LICENSE" -o haystack-LICENSE
echo "corpus pinned at $COMMIT"
