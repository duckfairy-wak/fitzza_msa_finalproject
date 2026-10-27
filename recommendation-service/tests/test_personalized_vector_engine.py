import math
from unittest.mock import MagicMock

import numpy as np
import pytest

from app.services.personalized_vector_engine import (
    PersonalizedVectorEngine,
    _l2_normalize,
)
from app.services.user_history_service import UserActionHistory


def _create_unit_vector(dim: int, index: int) -> list[float]:
    """특정 차원만 1.0인 단위 벡터 생성 (직교 벡터)"""
    vec = [0.0] * dim
    vec[index] = 1.0
    return vec


def test_l2_normalize():
    vec = np.array([3.0, 4.0], dtype=np.float32)
    normed = _l2_normalize(vec)
    assert np.isclose(np.linalg.norm(normed), 1.0)
    assert np.isclose(normed[0], 0.6)
    assert np.isclose(normed[1], 0.8)

    # 영벡터 처리
    zero_vec = np.array([0.0, 0.0], dtype=np.float32)
    assert np.allclose(_l2_normalize(zero_vec), zero_vec)


def test_cold_start_from_precomputed_file():
    """사전 계산된 cold_start_vector.json 파일이 정상 로드되는지 검증"""
    engine = PersonalizedVectorEngine(qdrant_client=MagicMock())
    cold_vec = engine.get_cold_start_vector()

    assert len(cold_vec) == 512
    norm = np.linalg.norm(np.array(cold_vec))
    assert np.isclose(norm, 1.0, atol=1e-5)
    # 캐싱 확인
    assert engine.get_cold_start_vector() is cold_vec


def test_cold_start_deterministic():
    """사전 파일과 search_engine이 모두 없을 때 결정론적 단위 벡터로 폴백"""
    engine = PersonalizedVectorEngine(qdrant_client=MagicMock(), cold_start_path="")
    cold_vec = engine.get_cold_start_vector()

    assert len(cold_vec) == 512
    # L2 norm은 1.0이어야 함
    norm = np.linalg.norm(np.array(cold_vec))
    assert np.isclose(norm, 1.0, atol=1e-5)
    # 캐싱 확인
    assert engine.get_cold_start_vector() is cold_vec


def test_cold_start_with_search_engine():
    """사전 파일이 없을 때 search_engine.encode_text로 폴백"""
    mock_search_engine = MagicMock()
    mock_search_engine.encode_text.return_value = [0.1] * 512

    engine = PersonalizedVectorEngine(
        qdrant_client=MagicMock(),
        search_engine=mock_search_engine,
        cold_start_path="",
    )
    cold_vec = engine.get_cold_start_vector()

    assert len(cold_vec) == 512
    mock_search_engine.encode_text.assert_called_once_with(
        PersonalizedVectorEngine.DEFAULT_COLD_START_PROMPT
    )
    norm = np.linalg.norm(np.array(cold_vec))
    assert np.isclose(norm, 1.0, atol=1e-5)


def test_empty_history_returns_cold_start():
    engine = PersonalizedVectorEngine(qdrant_client=MagicMock())
    empty_history = UserActionHistory(user_id=123)

    result_vec = engine.compute_user_taste_vector(empty_history)
    cold_vec = engine.get_cold_start_vector()

    assert np.allclose(result_vec, cold_vec)


def test_synthesize_all_components():
    """월드컵, 관심(찜+장바구니), 구매 이력이 모두 있을 때 정확한 가중치 합성 검증"""
    engine = PersonalizedVectorEngine(qdrant_client=MagicMock())

    dim = 512
    # 각 소스별 직교 단위 벡터 준비
    v_wc = _create_unit_vector(dim, 0)       # 차원 0만 1.0
    v_wish = _create_unit_vector(dim, 1)     # 차원 1만 1.0
    v_cart = _create_unit_vector(dim, 1)     # 차원 1만 1.0 (관심 평균 = 차원 1이 1.0)
    v_purchase = _create_unit_vector(dim, 2) # 차원 2만 1.0

    vector_map = {
        10: v_wc,
        20: v_wish,
        21: v_cart,
        30: v_purchase,
    }

    history = UserActionHistory(
        user_id=1,
        worldcup_winner_id=10,
        wishlist_product_ids=[20],
        cart_product_ids=[21],
        purchased_product_ids=[30],
    )

    synthesized = engine.synthesize_user_taste_vector(history, vector_map)
    assert len(synthesized) == 512

    # L2 norm 검증
    norm = np.linalg.norm(np.array(synthesized))
    assert np.isclose(norm, 1.0, atol=1e-5)

    # 가중치 비율 검증 (비정규화 합성 시 [0.5, 0.3, 0.2, 0, ...])
    # 정규화 후에도 각 성분의 비율은 0.5 : 0.3 : 0.2 유지
    assert synthesized[0] > synthesized[1] > synthesized[2]
    expected_ratio_0_1 = 0.5 / 0.3
    actual_ratio_0_1 = synthesized[0] / synthesized[1]
    assert np.isclose(actual_ratio_0_1, expected_ratio_0_1, atol=1e-5)

    expected_ratio_1_2 = 0.3 / 0.2
    actual_ratio_1_2 = synthesized[1] / synthesized[2]
    assert np.isclose(actual_ratio_1_2, expected_ratio_1_2, atol=1e-5)


def test_synthesize_dynamic_reweighting_only_worldcup():
    """월드컵 1등 이력만 있는 경우 가중치가 1.0으로 단독 배분되는지 검증"""
    engine = PersonalizedVectorEngine(qdrant_client=MagicMock())

    dim = 512
    v_wc = _create_unit_vector(dim, 5)
    vector_map = {10: v_wc}

    history = UserActionHistory(
        user_id=1,
        worldcup_winner_id=10,
        wishlist_product_ids=[],
        cart_product_ids=[],
        purchased_product_ids=[],
    )

    synthesized = engine.synthesize_user_taste_vector(history, vector_map)
    assert np.allclose(synthesized, v_wc)


def test_synthesize_dynamic_reweighting_interest_and_purchase():
    """월드컵 없이 관심(0.3)과 구매(0.2)만 있는 경우 3:2 (0.6 : 0.4) 비율 검증"""
    engine = PersonalizedVectorEngine(qdrant_client=MagicMock())

    dim = 512
    v_wish = _create_unit_vector(dim, 10)
    v_pur = _create_unit_vector(dim, 20)
    vector_map = {101: v_wish, 202: v_pur}

    history = UserActionHistory(
        user_id=1,
        worldcup_winner_id=None,
        wishlist_product_ids=[101],
        cart_product_ids=[],
        purchased_product_ids=[202],
    )

    synthesized = engine.synthesize_user_taste_vector(history, vector_map)

    # 비율 0.3 : 0.2 = 1.5
    assert np.isclose(synthesized[10] / synthesized[20], 1.5, atol=1e-5)
    norm = np.linalg.norm(np.array(synthesized))
    assert np.isclose(norm, 1.0, atol=1e-5)


def test_synthesize_fallback_when_vectors_missing_in_qdrant():
    """상품 ID는 있으나 Qdrant에 해당 벡터가 하나도 없는 경우 Cold-Start 폴백 검증"""
    engine = PersonalizedVectorEngine(qdrant_client=MagicMock())

    history = UserActionHistory(
        user_id=1,
        worldcup_winner_id=999,
        wishlist_product_ids=[888],
    )
    # vector_map이 비어있음
    synthesized = engine.synthesize_user_taste_vector(history, {})
    cold_vec = engine.get_cold_start_vector()

    assert np.allclose(synthesized, cold_vec)


def test_fetch_product_vectors_with_mock_qdrant():
    """Qdrant scroll 호출 및 포인트 파싱 검증"""
    mock_client = MagicMock()

    class MockPoint:
        def __init__(self, pid, vector):
            self.payload = {"product_id": pid}
            self.vector = vector

    p1 = MockPoint(100, [0.1] * 512)
    p2 = MockPoint(200, [0.2] * 512)
    mock_client.scroll.return_value = ([p1, p2], None)

    engine = PersonalizedVectorEngine(qdrant_client=mock_client)
    res = engine.fetch_product_vectors([100, 200, 300])

    assert 100 in res
    assert 200 in res
    assert 300 not in res
    assert len(res[100]) == 512
    assert res[100][0] == 0.1
    mock_client.scroll.assert_called_once()


def test_fetch_product_vectors_error_handling():
    """Qdrant 예외 발생 시 빈 딕셔너리로 안전하게 처리되는지 검증"""
    mock_client = MagicMock()
    mock_client.scroll.side_effect = RuntimeError("Qdrant connection timeout")

    engine = PersonalizedVectorEngine(qdrant_client=mock_client)
    res = engine.fetch_product_vectors([100])
    assert res == {}


def test_fetch_product_vectors_pagination():
    """복수 페이지 scroll 순회 검증"""
    mock_client = MagicMock()

    class MockPoint:
        def __init__(self, pid, vector):
            self.payload = {"product_id": pid}
            self.vector = vector

    p1 = MockPoint(100, [0.1] * 512)
    p2 = MockPoint(200, [0.2] * 512)

    # 1페이지: [p1], offset="page2" -> 2페이지: [p2], offset=None
    mock_client.scroll.side_effect = [
        ([p1], "page2"),
        ([p2], None),
    ]

    engine = PersonalizedVectorEngine(qdrant_client=mock_client)
    res = engine.fetch_product_vectors([100, 200])

    assert 100 in res
    assert 200 in res
    assert mock_client.scroll.call_count == 2

