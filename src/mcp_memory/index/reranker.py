"""bge-reranker-base 重排（线程池，默认开启）。"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any


class Reranker:
    """bge-reranker-base 重排（可选启用）。"""

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-base",
        device: str = "cpu",
        max_workers: int = 2,
    ):
        self.model_name = model_name
        self.device = device
        self._model: Any = None
        self._pool = ThreadPoolExecutor(max_workers=max_workers)

    def _load_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name, device=self.device)
        return self._model

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int | None = None,
    ) -> list[tuple[int, float]]:
        """重排：返回 [(index_into_documents, score)] 按 score 降序。"""
        if not documents:
            return []
        loop = asyncio.get_event_loop()

        def _score():
            model = self._load_model()
            pairs = [(query, doc) for doc in documents]
            scores = model.predict(pairs)
            indexed = [(i, float(s)) for i, s in enumerate(scores)]
            indexed.sort(key=lambda x: x[1], reverse=True)
            if top_k is not None:
                indexed = indexed[:top_k]
            return indexed

        return await loop.run_in_executor(self._pool, _score)

    def close(self) -> None:
        self._pool.shutdown(wait=True)
