"""Tests for RRFMerger (Reciprocal Rank Fusion)."""
from mcp_memory.index.rrf_merger import rrf_merge, rrf_score


def test_rrf_score_basic():
    assert rrf_score(0) == 1 / 60
    assert rrf_score(1) == 1 / 61
    assert rrf_score(0) > rrf_score(10)


def test_rrf_score_custom_k():
    assert rrf_score(0, k=10) == 1 / 10
    assert rrf_score(5, k=10) == 1 / 15


def test_rrf_score_monotonic_decreasing():
    scores = [rrf_score(i) for i in range(20)]
    for i in range(len(scores) - 1):
        assert scores[i] > scores[i + 1]


def test_rrf_merge_single_list():
    lst = [("a", 1.0), ("b", 0.5), ("c", 0.1)]
    merged = rrf_merge([lst])
    assert [x[0] for x in merged] == ["a", "b", "c"]


def test_rrf_merge_overlapping_items():
    list1 = [("a", 1.0), ("b", 0.5), ("c", 0.1)]
    list2 = [("b", 1.0), ("d", 0.5)]
    merged = rrf_merge([list1, list2])
    # b appears in both with high rank → top score
    assert merged[0][0] == "b"
    item_ids = {x[0] for x in merged}
    assert item_ids == {"a", "b", "c", "d"}


def test_rrf_merge_with_top_k():
    lst = [("a", 1.0), ("b", 0.5), ("c", 0.1), ("d", 0.01)]
    merged = rrf_merge([lst], top_k=2)
    assert len(merged) == 2
    assert merged[0][0] == "a"
    assert merged[1][0] == "b"


def test_rrf_merge_empty_lists():
    merged = rrf_merge([])
    assert merged == []


def test_rrf_merge_empty_inner_lists():
    merged = rrf_merge([[], []])
    assert merged == []


def test_rrf_merge_order_independent():
    list1 = [("a", 1.0), ("b", 0.5), ("c", 0.1)]
    list2 = [("b", 1.0), ("d", 0.5)]
    list3 = [("c", 0.9), ("e", 0.4)]
    merged_a = rrf_merge([list1, list2, list3])
    # Swap order of input lists — same items in same ranks
    merged_b = rrf_merge([list3, list1, list2])
    # The set of items must be identical, and the score for each item must match
    assert {x[0] for x in merged_a} == {x[0] for x in merged_b}
    scores_a = dict(merged_a)
    scores_b = dict(merged_b)
    for k in scores_a:
        assert abs(scores_a[k] - scores_b[k]) < 1e-9, f"{k}: {scores_a[k]} != {scores_b[k]}"


def test_rrf_merge_three_way_overlap_dominates():
    list1 = [("x", 1.0), ("a", 0.5)]
    list2 = [("x", 1.0), ("b", 0.5)]
    list3 = [("x", 1.0), ("c", 0.5)]
    merged = rrf_merge([list1, list2, list3])
    # x is rank 0 in all three → highest fused score
    assert merged[0][0] == "x"


def test_rrf_merge_score_is_sum_of_rrf():
    # item "a" is rank 0 in list1 (1/60) and rank 2 in list2 (1/62)
    # score should be 1/60 + 1/62
    list1 = [("a", 1.0), ("b", 0.5), ("c", 0.1)]
    list2 = [("x", 1.0), ("y", 0.5), ("a", 0.1)]
    merged = rrf_merge([list1, list2])
    a_score = next(s for i, s in merged if i == "a")
    assert abs(a_score - (1 / 60 + 1 / 62)) < 1e-9
