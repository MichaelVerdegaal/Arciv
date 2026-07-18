"""Retrieval-quality evaluation for MicroRag.

Indexes the fixture corpus in evals/corpus through the real pipeline
(chunk -> embed -> store) into a throwaway database, runs the gold queries
from evals/queries.json, and scores file-level retrieval: did the file that
answers the query show up, and how high?

Requires the embedding model (run `microrag download` once). Fully offline.

Usage:
    uv run python -m evals.run [--json]
"""

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from microrag.constants import MODEL_DIR, ONNX_FILENAME, TOKENIZER_FILENAME
from microrag.embedder import OnnxEmbedder
from microrag.indexer import index_directory
from microrag.store import Store

EVALS_DIR = Path(__file__).parent
CORPUS_DIR = EVALS_DIR / "corpus"
QUERIES_FILE = EVALS_DIR / "queries.json"

# Chunk-level retrieval depth before deduplicating to source files. Deep
# enough that a relevant file ranked poorly still gets a reciprocal-rank
# score instead of counting as a hard miss.
RETRIEVE_CHUNKS = 25


@dataclass
class QueryResult:
    """Outcome of one gold query: the sources retrieved and the gold rank."""

    query: str
    expected: list[str]
    ranked_sources: list[str]
    rank: int | None  # 1-based rank of the first expected source, None = miss


def load_queries(path: Path = QUERIES_FILE) -> list[dict]:
    """Load the gold query set."""
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(
    corpus: Path,
    queries: list[dict],
    embedder: OnnxEmbedder,
    store: Store,
) -> list[QueryResult]:
    """Index the corpus into the store and score every gold query."""
    index_directory(corpus, embedder, store)
    depth = min(RETRIEVE_CHUNKS, store.count())

    results = []
    for entry in queries:
        expected = entry["source"]
        expected = [expected] if isinstance(expected, str) else list(expected)
        embedding = embedder.embed_query(entry["query"])
        _, metadatas, _ = store.query(embedding, depth)
        ranked = _ranked_sources(metadatas[0])
        results.append(
            QueryResult(
                query=entry["query"],
                expected=expected,
                ranked_sources=ranked,
                rank=_rank_of_expected(ranked, expected),
            )
        )
    return results


def _ranked_sources(metadatas: list[dict]) -> list[str]:
    """Deduplicate chunk metadata to source files, best rank first."""
    ranked: list[str] = []
    for meta in metadatas:
        if meta["source"] not in ranked:
            ranked.append(meta["source"])
    return ranked


def _rank_of_expected(ranked: list[str], expected: list[str]) -> int | None:
    """Return the 1-based rank of the first expected source, or None."""
    for position, source in enumerate(ranked, start=1):
        if source in expected:
            return position
    return None


def aggregate(results: list[QueryResult]) -> dict:
    """Compute hit@k and MRR over all query results."""
    total = len(results)

    def hit_at(k: int) -> float:
        return sum(1 for r in results if r.rank is not None and r.rank <= k) / total

    mrr = sum(1 / r.rank for r in results if r.rank is not None) / total
    return {
        "queries": total,
        "hit@1": round(hit_at(1), 3),
        "hit@3": round(hit_at(3), 3),
        "hit@5": round(hit_at(5), 3),
        "mrr": round(mrr, 3),
    }


def _load_embedder() -> OnnxEmbedder | None:
    """Load the real embedder, or explain what is missing."""
    model_path = MODEL_DIR / ONNX_FILENAME
    tokenizer_path = MODEL_DIR / TOKENIZER_FILENAME
    if not (model_path.exists() and tokenizer_path.exists()):
        print(
            f"Embedding model not found in {MODEL_DIR.resolve()}. "
            "Run: microrag download",
            file=sys.stderr,
        )
        return None
    return OnnxEmbedder(model_path=model_path, tokenizer_path=tokenizer_path)


def main(argv: list[str] | None = None) -> int:
    """Run the evaluation and print a report."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the report as one JSON object instead of text",
    )
    args = parser.parse_args(argv)

    embedder = _load_embedder()
    if embedder is None:
        return 66  # EX_NOINPUT, matching the CLI's convention

    queries = load_queries()
    with tempfile.TemporaryDirectory(prefix="microrag-eval-") as tmp:
        store = Store(Path(tmp) / "db", "eval")
        results = evaluate(CORPUS_DIR, queries, embedder, store)

    metrics = aggregate(results)
    if args.json:
        print(
            json.dumps(
                {
                    "metrics": metrics,
                    "per_query": [
                        {
                            "query": r.query,
                            "expected": r.expected,
                            "rank": r.rank,
                            "top": r.ranked_sources[:5],
                        }
                        for r in results
                    ],
                },
                ensure_ascii=False,
            )
        )
        return 0

    for key, value in metrics.items():
        print(f"{key}\t{value}")
    imperfect = sorted(
        (r for r in results if r.rank != 1),
        key=lambda r: (r.rank is not None, -(r.rank or 0)),
    )
    if imperfect:
        print("\nnot ranked first:")
        for r in imperfect:
            label = f"rank {r.rank}" if r.rank is not None else "MISS"
            print(f"  [{label}] {r.query!r}")
            print(
                f"          expected {', '.join(r.expected)}; got {r.ranked_sources[:3]}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
