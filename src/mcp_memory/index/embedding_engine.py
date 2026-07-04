"""sentence-transformers + bge-m3 包装（线程池跑 bge-m3）。"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any


class EmbeddingEngine:
    """bge-m3 embedding 推理（CPU/GPU），不阻塞 MCP 主循环。"""

    def __init__(self, model_name: str = "BAAI/bge-m3", device: str = "cpu", max_workers: int = 2):
        self.model_name = model_name
        self.device = device
        self._model: Any = None
        self._pool = ThreadPoolExecutor(max_workers=max_workers)

    def _load_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        loop = asyncio.get_event_loop()

        def _encode():
            model = self._load_model()
            return model.encode(texts, normalize_embeddings=True).tolist()

        return await loop.run_in_executor(self._pool, _encode)

    async def embed_query(self, query: str) -> list[float]:
        results = await self.embed([query])
        return results[0] if results else []

    def close(self) -> None:
        self._pool.shutdown(wait=True)
