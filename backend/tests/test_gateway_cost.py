"""Cost computation is pure arithmetic — no network needed to test it."""

from unittest.mock import patch

from app.llm.gateway import _compute_cost_paise


def test_cost_is_zero_by_default():
    with patch("app.llm.gateway.settings.llm_cost_paise_per_token", 0.0):
        assert _compute_cost_paise(100_000) == 0


def test_cost_scales_with_tokens_and_rate():
    with patch("app.llm.gateway.settings.llm_cost_paise_per_token", 0.01):
        assert _compute_cost_paise(1000) == 10
        assert _compute_cost_paise(0) == 0


def test_cost_rounds_to_nearest_paise():
    with patch("app.llm.gateway.settings.llm_cost_paise_per_token", 0.003):
        # 150 * 0.003 = 0.45 -> rounds to 0
        assert _compute_cost_paise(150) == 0
        # 500 * 0.003 = 1.5 -> rounds to 2 (banker's rounding on .5 -> even)
        assert _compute_cost_paise(500) == round(500 * 0.003)


def test_cost_is_none_when_token_count_unknown():
    assert _compute_cost_paise(None) is None
