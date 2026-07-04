"""langchain-text-splitters 包装。"""
from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter


class TextChunker:
    """将长文本切成 embedding-ready 的 chunks。

    Spec §4.1: 短 (<800 字) → 1 chunk；长 → 滑动窗口 800 + overlap 100
    """

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 100):
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", ".", " ", ""],
        )

    def split(self, text: str) -> list[str]:
        if not text:
            return []
        return self._splitter.split_text(text)
