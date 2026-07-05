"""Index stage: extract links from files and register them in the database.

For every link found, a row is stored with the processed URL, the full
normalized path of the file it was found in, and the time it was indexed.
Pages are created in pending state; downloading them is the fetch stage's
job (see ``arciv.core.pipeline.fetch_pipeline``).
"""

from .index import (
    index_all,
    index_directory,
    index_file,
    index_source,
    register_urls,
)

__all__ = [
    "index_all",
    "index_directory",
    "index_file",
    "index_source",
    "register_urls",
]
