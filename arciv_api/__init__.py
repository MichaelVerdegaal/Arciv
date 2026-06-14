"""Arciv backend API: a thin FastAPI read layer over the arciv library.

Imports the same library functions the CLI uses (it never shells out) and
serves the archive over HTTP for the Astro frontend. Reads go through
short-lived read-only database connections; this package never writes to
the archive the CLI owns.
"""
