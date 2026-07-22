"""Skip the search test suite unless the optional ``search`` extra is installed.

Every module here imports arciv.search.* (chromadb, onnxruntime, chonkie), so
without the extra they can't even be collected. collect_ignore_glob drops the
whole directory cleanly in a core-only run, matching how the CLI degrades the
``search`` command to a stub.
"""

import importlib.util

collect_ignore_glob: list[str] = []
if importlib.util.find_spec("chromadb") is None:
    collect_ignore_glob = ["*"]
