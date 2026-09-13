# Experiments (not applied)

- `0002-hybrid-keep-fused-order.patch` — keep the BM25+vector fused (RRF) order in hybrid search when no reranking model exists.
  Result on dev (7 questions, k=3): recall@3 0.714 at BM25 weight 0.5 and 0.357 at 0.7, versus 0.786 for dense + per-file dedup.
  Reverted; evidence in `runtime/eval/issues/hybrid-fused-w*.json`. Upstream hybrid without a reranker re-sorts candidates by dense
  similarity (`RerankCompressor.acompress_documents`), and with the fused order BM25 pulls unrelated pages, so neither helps here.
  The standard fix is a cross-encoder reranking model (`RAG_RERANKING_MODEL`), which is a new model download and needs approval.
