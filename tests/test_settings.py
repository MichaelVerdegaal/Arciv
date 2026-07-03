"""Tests for settings helpers: env var parsing degrades gracefully."""

from arciv.settings import _env_int


class TestEnvInt:
    def test_missing_uses_default(self, monkeypatch):
        monkeypatch.delenv("ARCIV_TEST_INT", raising=False)
        assert _env_int("ARCIV_TEST_INT", 8) == 8

    def test_valid_int_is_parsed(self, monkeypatch):
        monkeypatch.setenv("ARCIV_TEST_INT", "16")
        assert _env_int("ARCIV_TEST_INT", 8) == 16

    def test_non_integer_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("ARCIV_TEST_INT", "lots")
        assert _env_int("ARCIV_TEST_INT", 8) == 8

    def test_zero_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("ARCIV_TEST_INT", "0")
        assert _env_int("ARCIV_TEST_INT", 8) == 8

    def test_negative_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("ARCIV_TEST_INT", "-5")
        assert _env_int("ARCIV_TEST_INT", 8) == 8
