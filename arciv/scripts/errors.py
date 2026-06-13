"""CLI error types that carry an exit code.

Raising one of these from a command bubbles up to ``main``, which prints
the message to stderr and returns the carried exit code. This keeps each
command's failure path a plain ``raise`` with a clear message, no
framework-specific exception types, and no tracebacks on expected errors.
"""

from .output import EXIT_FAILURE, EXIT_USAGE


class ArcivError(Exception):
    """A CLI error with an associated process exit code."""

    def __init__(self, message: str, exit_code: int = EXIT_FAILURE) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class UsageError(ArcivError):
    """A bad or missing argument combination (exit code 64)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, EXIT_USAGE)
