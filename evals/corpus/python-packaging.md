# Python packaging cheatsheet

## pyproject basics

Everything lives in pyproject.toml now: metadata under `[project]`, the
build backend under `[build-system]`. Hatchling is a sane default backend.
Pin `requires-python` honestly — it gates resolver behavior for everyone
downstream.

## Console scripts

An entry in `[project.scripts]` like `mytool = "mytool.cli:main"` turns a
function into a shell command on install. The function should return an int
exit code and take no arguments; parse argv inside.

## Local installs with uv

`uv tool install .` puts the command on PATH in an isolated environment;
`uv tool install -e .` keeps it editable so source changes apply without a
reinstall. `uv sync` manages the project venv and lockfile for development
work.
