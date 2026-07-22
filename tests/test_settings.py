"""Tests for settings helpers: env var parsing degrades gracefully."""

import pathlib

import arciv.settings as settings_module
from arciv.settings import _env_int, _resolve_search_home


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


class TestSearchHome:
    """Resolution order for the optional search extra's data home (D4)."""

    def test_explicit_override_wins_over_legacy(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARCIV_SEARCH_HOME", str(tmp_path / "custom"))
        monkeypatch.setenv("MICRORAG_HOME", str(tmp_path / "legacy"))
        assert _resolve_search_home() == (tmp_path / "custom").resolve()

    def test_legacy_microrag_home_env_is_honored(self, tmp_path, monkeypatch):
        # A prior MicroRag install keeps working without re-downloading.
        monkeypatch.delenv("ARCIV_SEARCH_HOME", raising=False)
        monkeypatch.setenv("MICRORAG_HOME", str(tmp_path / "legacy"))
        assert _resolve_search_home() == (tmp_path / "legacy").resolve()

    def test_defaults_under_data_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ARCIV_SEARCH_HOME", raising=False)
        monkeypatch.delenv("MICRORAG_HOME", raising=False)
        monkeypatch.setattr(settings_module, "DATA_DIR", tmp_path)
        # No prior ~/.microrag: home() points at an empty temp dir.
        monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: tmp_path))
        assert _resolve_search_home() == tmp_path / "search"

    def test_existing_microrag_dir_is_reused(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ARCIV_SEARCH_HOME", raising=False)
        monkeypatch.delenv("MICRORAG_HOME", raising=False)
        monkeypatch.setattr(settings_module, "DATA_DIR", tmp_path / "data")
        home = tmp_path / "home"
        (home / ".microrag").mkdir(parents=True)
        monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
        assert _resolve_search_home() == (home / ".microrag").resolve()
