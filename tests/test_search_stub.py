"""The missing-extra stub for `arciv search`: the one behavior only a core install has.

tests/search/ is collect-ignored exactly when the extra is absent, so the stub
is covered here in the core suite instead, by forcing the stub path onto a
fresh Typer app. This runs identically with the extra installed.
"""

import typer
from loguru import logger
from typer.testing import CliRunner

import arciv.cli.search as search_module
from arciv.cli.output import EXIT_USAGE


def _stub_app(monkeypatch) -> typer.Typer:
    """A fresh parent app with the stub registered (extra forced absent)."""
    monkeypatch.setattr(search_module, "search_extra_installed", lambda: False)
    app = typer.Typer()
    search_module.register_search(app)
    return app


def _invoke(app: typer.Typer, args: list[str], messages: list[str]):
    """Invoke with loguru captured into ``messages`` (the fresh app has no
    callback to configure logging, and loguru's default sink holds the real
    stderr object, which CliRunner cannot intercept)."""
    logger.remove()
    logger.add(messages.append, format="{message}")
    try:
        return CliRunner().invoke(app, args)
    finally:
        logger.remove()


def test_stub_prints_install_hint_and_exits_usage(monkeypatch) -> None:
    messages: list[str] = []
    result = _invoke(_stub_app(monkeypatch), ["search"], messages)
    assert result.exit_code == EXIT_USAGE
    assert result.stdout == ""
    assert any("arciv[search]" in m for m in messages)  # names the install step


def test_stub_swallows_subcommand_args_and_flags(monkeypatch) -> None:
    # `arciv search query foo -k 3` on a core install must reach the stub's
    # hint, not die on an unknown-command/option parse error (exit 2).
    messages: list[str] = []
    result = _invoke(
        _stub_app(monkeypatch), ["search", "query", "foo", "-k", "3"], messages
    )
    assert result.exit_code == EXIT_USAGE
    assert any("arciv[search]" in m for m in messages)


def test_stub_still_appears_in_parent_help(monkeypatch) -> None:
    result = CliRunner().invoke(_stub_app(monkeypatch), ["--help"])
    assert result.exit_code == 0
    assert "search" in result.output
