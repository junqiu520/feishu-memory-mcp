"""Reciprocal Rank Fusion — 融合两路召回结果。"""
from __future__ import annotations


def rrf_score(rank: int, k: int = 60) -> float:
    """RRF 公式：1/(k+rank)。rank 从 0 开始。"""
    return 1.0 / (k + rank)


def rrf_merge(
    retrieved_lists: list[list[tuple[str, float]]],
    k: int = 60,
    top_k: int | None = None,
) -> list[tuple[str, float]]:
    """多路召回融合。

    Args:
        retrieved_lists: 多路 [(item_id, score)] 列表，每路内部已按 score 排序
        k: RRF 平滑常数（默认 60）
        top_k: 返回前 K 个，None 表示全返回

    Returns:
        [(item_id, fused_score)] 按 fused_score 降序排序
    """
    scores: dict[str, float] = {}
    for lst in retrieved_lists:
        for rank, (item_id, _orig_score) in enumerate(lst):
            scores[item_id] = scores.get(item_id, 0.0) + rrf_score(rank, k)

    sorted_items = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    if top_k is not None:
        return sorted_items[:top_k]
    return sorted_items
