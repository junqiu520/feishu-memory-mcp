"""SearchService — query (BM25 + vector + RRF + optional rerank).

Spec §4.2 flow.
"""
from __future__ import annotations

from typing import Any

from mcp_memory.index.embedding_engine import EmbeddingEngine
from mcp_memory.index.reranker import Reranker
from mcp_memory.index.rrf_merger import rrf_merge
from mcp_memory.storage.local_cache import LocalCache


class SearchService:
    """Hybrid recall + RRF + optional rerank orchestration."""

    def __init__(
        self,
        local_cache: LocalCache,
        embedding_engine: EmbeddingEngine,
        vector_index: Any,  # VectorIndex interface (Protocol)
        reranker: Reranker | None = None,
        default_top_k: int = 5,
        default_rerank: bool = True,
    ):
        self.cache = local_cache
        self.embed = embedding_engine
        self.vector = vector_index
        self.reranker = reranker
        self.default_top_k = default_top_k
        self.default_rerank = default_rerank

    async def query(
        self,
        query: str,
        top_k: int | None = None,
        filter: dict | None = None,
        mode: str = "hybrid_rerank",
    ) -> list[dict]:
        """Run a query and return a list of result dicts.

        Each result dict has: record_id, score, title, preview,
        matched_chunk_text, content_ref_url, tags, source, source_agent,
        created_at.
        """
        top_k = top_k or self.default_top_k
        filt = filter or {}
        candidate_ids = self.cache.list_by_filter(filt)
        if not candidate_ids:
            return []

        if mode == "bm25_only":
            return self._bm25_path(query, candidate_ids, top_k)
        elif mode == "vector_only":
            return await self._vector_path(query, candidate_ids, top_k)
        elif mode == "hybrid":
            return await self._hybrid_path(query, candidate_ids, top_k, use_rerank=False)
        else:  # hybrid_rerank
            return await self._hybrid_path(query, candidate_ids, top_k, use_rerank=True)

    def _bm25_path(
        self, query: str, candidate_ids: list[str], top_k: int
    ) -> list[dict]:
        results = self.cache.search_fts(query, candidate_ids=candidate_ids, limit=top_k)
        return self._assemble_results(results, top_k, bm25_only=True)

    async def _vector_path(
        self, query: str, candidate_ids: list[str], top_k: int
    ) -> list[dict]:
        qv = await self.embed.embed_query(query)
        results = await self.vector.search(
            qv, top_k=top_k, metadata_filter={"record_ids": candidate_ids}
        )
        return self._assemble_results(results, top_k)

    async def _hybrid_path(
        self,
        query: str,
        candidate_ids: list[str],
        top_k: int,
        use_rerank: bool,
    ) -> list[dict]:
        # 1. BM25
        bm25_raw = self.cache.search_fts(query, candidate_ids=candidate_ids, limit=50)
        # 2. Vector
        qv = await self.embed.embed_query(query)
        vec_raw = await self.vector.search(
            qv, top_k=50, metadata_filter={"record_ids": candidate_ids}
        )
        # 3. RRF merge
        fused = rrf_merge([bm25_raw, vec_raw], top_k=2 * top_k)
        # 4. Optional rerank
        if use_rerank and self.reranker is not None:
            docs = [self._doc_text_for(rid) for rid, _ in fused]
            reranked = await self.reranker.rerank(query, docs, top_k=top_k)
            fused = [(fused[idx][0], score) for idx, score in reranked]
        else:
            fused = fused[:top_k]
        return self._assemble_results(fused, top_k)

    def _doc_text_for(self, record_id: str) -> str:
        rec = self.cache.get_record(record_id)
        return rec.text if rec else ""

    def _assemble_results(
        self,
        scored: list[tuple[str, float]],
        top_k: int,
        bm25_only: bool = False,
    ) -> list[dict]:
        out: list[dict] = []
        for record_id, score in scored[:top_k]:
            rec = self.cache.get_record(record_id)
            if rec is None:
                continue
            out.append(
                {
                    "record_id": record_id,
                    "score": score,
                    "title": rec.title,
                    "preview": rec.preview,
                    "matched_chunk_text": rec.text[:300],
                    "content_ref_url": rec.content_ref.url if rec.content_ref else None,
                    "tags": rec.metadata.tags,
                    "source": rec.source.value,
                    "source_agent": rec.metadata.source_agent,
                    "created_at": rec.created_at,
                }
            )
        return out
