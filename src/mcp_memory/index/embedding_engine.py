"""sentence-transformers embedding engine.

Wraps sentence-transformers.SentenceTransformer with:
  - ThreadPoolExecutor so embed() doesn't block the MCP event loop
  - Per-call batch_size so a 19-record sync doesn't choke on a single
    giant network call
  - Retry with exponential backoff for transient HF Hub errors
    (SSL EOF, network blips, 429 rate limits)
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

log = logging.getLogger(__name__)


class EmbeddingEngine:
    """Embedding inference (CPU/GPU), non-blocking on MCP event loop."""

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        device: str = "cpu",
        max_workers: int = 2,
        batch_size: int = 4,
        max_retries: int = 3,
    ):
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self.max_retries = max_retries
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
        out: list[list[float]] = []
        # Process in batches; each batch retries on transient failures
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            vectors = await self._embed_batch_with_retry(batch)
            out.extend(vectors)
        return out

    async def _embed_batch_with_retry(self, batch: list[str]) -> list[list[float]]:
        loop = asyncio.get_event_loop()
        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                def _encode():
                    model = self._load_model()
                    return model.encode(batch, normalize_embeddings=True).tolist()
                return await loop.run_in_executor(self._pool, _encode)
            except Exception as e:
                last_err = e
                err_type = type(e).__name__
                if attempt < self.max_retries:
                    backoff = min(2 ** attempt, 30)
                    log.warning(
                        "embed batch failed (attempt %d/%d, %s: %s); "
                        "retrying in %ds",
                        attempt, self.max_retries, err_type, e, backoff,
                    )
                    await asyncio.sleep(backoff)
                else:
                    log.error(
                        "embed batch failed after %d attempts (%s: %s)",
                        self.max_retries, err_type, e,
                    )
        # Bubble up the last error; caller (SyncService) catches and logs.
        raise last_err  # type: ignore[misc]

    async def embed_query(self, query: str) -> list[float]:
        results = await self.embed([query])
        return results[0] if results else []

    def close(self) -> None:
        self._pool.shutdown(wait=True)
