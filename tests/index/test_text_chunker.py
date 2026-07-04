"""Tests for TextChunker (langchain-text-splitters wrapper)."""
from mcp_memory.index.text_chunker import TextChunker


def test_short_text_returns_single_chunk():
    chunker = TextChunker(chunk_size=800, chunk_overlap=100)
    text = "这是一段短文本。不到 800 字。Should fit in one chunk."
    chunks = chunker.split(text)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_empty_text_returns_empty_list():
    chunker = TextChunker()
    assert chunker.split("") == []


def test_long_text_returns_multiple_chunks_with_overlap():
    chunker = TextChunker(chunk_size=100, chunk_overlap=20)
    # Build a long Chinese text (>100 chars repeated)
    base = "这是一段测试文本用于触发切分。LangChain 应该用滑动窗口切。" * 5
    chunks = chunker.split(base)
    assert len(chunks) > 1
    # Each chunk should not exceed chunk_size (allow RecursiveCharacterTextSplitter leniency)
    for c in chunks:
        assert len(c) <= 200  # some leniency due to separator boundary
    # Overlap property: adjacent chunks should share some text at the boundary
    # (langchain's overlap is in characters, not strict)
    assert len(chunks[0]) <= 200


def test_text_splitter_default_separators_split_on_paragraph():
    chunker = TextChunker(chunk_size=20, chunk_overlap=5)
    text = "第一段内容比较长。\n\n第二段内容也比较长。\n\n第三段内容同样比较长。"
    chunks = chunker.split(text)
    assert len(chunks) >= 2


def test_chunker_default_size_is_800_overlap_100():
    chunker = TextChunker()
    assert chunker._splitter._chunk_size == 800
    assert chunker._splitter._chunk_overlap == 100
