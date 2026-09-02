"""The safety property that matters most about chaos injection: there is no
way to enable it outside APP_ENV=development, regardless of what env var or
header asks for it.
"""

from unittest.mock import patch

from app.testing import chaos


def test_off_by_default():
    assert chaos.active_fault() is None


def test_env_var_activates_a_fault_in_development():
    with patch("app.testing.chaos.settings.app_env", "development"), patch(
        "app.testing.chaos.settings.chaos_fault", "SLOW_LLM"
    ):
        assert chaos.active_fault() == chaos.ChaosFault.SLOW_LLM
        assert chaos.is_active(chaos.ChaosFault.SLOW_LLM) is True
        assert chaos.is_active(chaos.ChaosFault.FAIL_PAYMENT) is False


def test_impossible_to_enable_outside_development():
    """The actual safety guarantee: even with the env var AND a request
    header both asking for a fault, a non-development app_env refuses it."""
    with patch("app.testing.chaos.settings.app_env", "production"), patch(
        "app.testing.chaos.settings.chaos_fault", "SLOW_LLM"
    ):
        token = chaos.set_request_fault("FAIL_PAYMENT")
        try:
            assert chaos.active_fault() is None
            assert chaos.is_active(chaos.ChaosFault.SLOW_LLM) is False
            assert chaos.is_active(chaos.ChaosFault.FAIL_PAYMENT) is False
        finally:
            chaos.reset_request_fault(token)


def test_request_header_takes_precedence_over_env_var():
    with patch("app.testing.chaos.settings.app_env", "development"), patch(
        "app.testing.chaos.settings.chaos_fault", "SLOW_LLM"
    ):
        token = chaos.set_request_fault("TAMPERED_SIGNATURE")
        try:
            assert chaos.active_fault() == chaos.ChaosFault.TAMPERED_SIGNATURE
        finally:
            chaos.reset_request_fault(token)
        # header cleared -> falls back to the sticky env var
        assert chaos.active_fault() == chaos.ChaosFault.SLOW_LLM


def test_unknown_fault_name_is_ignored_not_crashed():
    with patch("app.testing.chaos.settings.app_env", "development"), patch(
        "app.testing.chaos.settings.chaos_fault", "NOT_A_REAL_FAULT"
    ):
        assert chaos.active_fault() is None
