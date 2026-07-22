"""Root conftest: puts the repo root on sys.path so tests can import evals/.

The retrieval evals live in evals/ (a dev tool, not shipped in the wheel), so
they are not part of the installed arciv package. pytest imports this conftest
from the repo root in prepend mode, which adds the root to sys.path and lets
tests/search/test_evals.py do ``from evals.run import ...``.
"""
