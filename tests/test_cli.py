"""UX-invariant tests for the CLI: stdout/stderr split, exit codes, next-step errors."""

import json
from pathlib import Path

import httpx
import numpy as np
import pytest

from microrag.cli import EX_NOINPUT, EX_OK, EX_UNAVAILABLE, EX_USAGE, main
from microrag.indexer import index_directory


class _FakeEmbedder:
    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return np.zeros((len(texts), 4), dtype=np.float32)


class _FakeStore:
    def upsert(self, ids, embeddings, documents, metadatas) -> None:
        pass

    def ids_for_source(self, source: str) -> list[str]:
        return []

    def delete(self, ids: list[str]) -> None:
        pass


@pytest.fixture
def empty_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run with an isolated MICRORAG_HOME: no model, no index."""
    monkeypatch.chdir(tmp_path)
    home = tmp_path / "microrag-home"
    monkeypatch.setattr("microrag.cli.MODEL_DIR", home / "model")
    monkeypatch.setattr("microrag.cli.DEFAULT_DB_DIR", home / "db")
    return tmp_path


def test_no_args_shows_help(empty_cwd: Path, capsys: pytest.CaptureFixture) -> None:
    assert main([]) == EX_OK
    assert "usage: microrag" in capsys.readouterr().out


def test_version_flag(capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "microrag" in capsys.readouterr().out


def test_index_missing_path(empty_cwd: Path, capsys: pytest.CaptureFixture) -> None:
    code = main(["index", str(empty_cwd / "nope")])
    captured = capsys.readouterr()
    assert code == EX_NOINPUT
    assert captured.out == ""
    assert "Path does not exist" in captured.err


def test_index_without_model_names_next_step(
    empty_cwd: Path, capsys: pytest.CaptureFixture
) -> None:
    notes = empty_cwd / "notes"
    notes.mkdir()
    code = main(["index", str(notes)])
    captured = capsys.readouterr()
    assert code == EX_NOINPUT
    assert captured.out == ""
    assert "microrag download" in captured.err


def test_query_without_index_names_next_step(
    empty_cwd: Path, capsys: pytest.CaptureFixture
) -> None:
    code = main(["query", "anything"])
    captured = capsys.readouterr()
    assert code == EX_NOINPUT
    assert captured.out == ""
    assert "microrag index" in captured.err


def test_query_dash_with_tty_stdin_is_usage_error(
    empty_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    import io

    class _TtyIn(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("sys.stdin", _TtyIn())
    code = main(["query", "-"])
    captured = capsys.readouterr()
    assert code == EX_USAGE
    assert captured.out == ""
    assert "microrag query -" in captured.err  # error shows an example pipe


def test_query_dash_reads_stdin(
    empty_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("some piped query"))
    # No index exists, so it proceeds past stdin handling to the missing-index error.
    code = main(["query", "-"])
    captured = capsys.readouterr()
    assert code == EX_NOINPUT
    assert "microrag index" in captured.err


def test_status_plain_output_is_tab_separated(
    empty_cwd: Path, capsys: pytest.CaptureFixture
) -> None:
    assert main(["status"]) == EX_OK
    out = capsys.readouterr().out
    assert "model_present\tfalse" in out
    assert "chunks\t0" in out


def test_status_json_output(empty_cwd: Path, capsys: pytest.CaptureFixture) -> None:
    assert main(["status", "--json"]) == EX_OK
    obj = json.loads(capsys.readouterr().out)
    assert obj["model_present"] is False
    assert obj["chunks"] == 0


def test_global_flags_work_before_and_after_subcommand(
    empty_cwd: Path, capsys: pytest.CaptureFixture
) -> None:
    assert main(["--json", "status"]) == EX_OK
    json.loads(capsys.readouterr().out)
    assert main(["status", "-q"]) == EX_OK
    capsys.readouterr()


def test_download_network_failure_is_clean(
    empty_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def _fail(**_kwargs) -> str:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("microrag.cli.hf_hub_download", _fail)
    code = main(["download"])
    captured = capsys.readouterr()
    assert code == EX_UNAVAILABLE
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert "microrag download" in captured.err


def test_microrag_home_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    import microrag.constants as constants

    try:
        monkeypatch.setenv("MICRORAG_HOME", "/custom/home")
        importlib.reload(constants)
        assert constants.MODEL_DIR == Path("/custom/home/model")
        assert constants.DEFAULT_DB_DIR == Path("/custom/home/db")
    finally:
        monkeypatch.delenv("MICRORAG_HOME")
        importlib.reload(constants)


def test_index_directory_keeps_stdout_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    (tmp_path / "a.md").write_text("# Title\n\nhello world\n", encoding="utf-8")
    files, chunks, pruned = index_directory(tmp_path, _FakeEmbedder(), _FakeStore())
    assert (files, chunks, pruned) == (1, 1, 0)
    assert capsys.readouterr().out == ""
