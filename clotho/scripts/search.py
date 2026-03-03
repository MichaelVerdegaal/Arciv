"""Interactive semantic search over scraped documents."""

import numpy as np
from loguru import logger
from sentence_transformers import SentenceTransformer

from clotho.db import PageDatabase
from config import DB_PATH, configure_logger

configure_logger(log_file=False, console_level="WARNING")

MODEL_NAME = "perplexity-ai/pplx-embed-v1-0.6B"
TOP_K = 5
SNIPPET_LENGTH = 200


def load_corpus(db: PageDatabase) -> tuple[list[str], list[str], list[str], np.ndarray]:
    """Load all embedded pages from the database.

    Returns:
        Tuple of (urls, titles, domains, embeddings_matrix).
        embeddings_matrix has shape (n_docs, packed_dim) with dtype uint8.

    Raises:
        SystemExit: If no embedded documents are found.
    """
    rows = db._conn.execute(
        "SELECT url, title, domain, embedding FROM pages "
        "WHERE embedding IS NOT NULL"
    ).fetchall()

    if not rows:
        logger.error("No embedded documents found. Run embed_documents.py first.")
        raise SystemExit(1)

    urls: list[str] = []
    titles: list[str] = []
    domains: list[str] = []
    embeddings: list[np.ndarray] = []

    for row in rows:
        urls.append(row["url"])
        titles.append(row["title"] or "(no title)")
        domains.append(row["domain"])
        # Stored as float32 bytes (originally uint8 packed binary)
        vec = np.frombuffer(row["embedding"], dtype=np.float32).astype(np.uint8)
        embeddings.append(vec)

    matrix = np.stack(embeddings)
    return urls, titles, domains, matrix


def search(
    query: str,
    model: SentenceTransformer,
    corpus_matrix: np.ndarray,
    top_k: int = TOP_K,
) -> np.ndarray:
    """Encode a query and return indices of the top-k most similar documents.

    Uses Hamming similarity on binary-quantized embeddings: XOR the packed
    uint8 vectors and count matching bits. Higher match count = more similar.

    Args:
        query: Natural language search query.
        model: The same SentenceTransformer used for corpus embedding.
        corpus_matrix: Binary embeddings matrix, shape (n_docs, packed_dim), uint8.
        top_k: Number of results to return.

    Returns:
        Array of corpus indices sorted by descending similarity.
    """
    query_emb: np.ndarray = model.encode(
        [query], quantization="binary", show_progress_bar=False
    )
    query_vec = query_emb[0].astype(np.uint8)

    # Hamming similarity: count matching bits via XOR + popcount
    # XOR gives 1 where bits differ; we count zeros (matches) instead.
    xor = np.bitwise_xor(corpus_matrix, query_vec)
    # unpackbits along last axis, sum differing bits per document
    differing_bits = np.unpackbits(xor, axis=1).sum(axis=1)
    total_bits = corpus_matrix.shape[1] * 8
    matching_bits = total_bits - differing_bits

    top_indices = np.argsort(matching_bits)[::-1][:top_k]
    return top_indices


def format_snippet(text: str | None, length: int = SNIPPET_LENGTH) -> str:
    """Extract a short preview from markdown content.

    Args:
        text: Raw markdown content.
        length: Maximum snippet length in characters.

    Returns:
        A truncated, whitespace-normalized preview string.
    """
    if not text:
        return "(no content)"
    # Collapse whitespace, take first N chars
    clean = " ".join(text.split())
    if len(clean) <= length:
        return clean
    return clean[:length].rsplit(" ", 1)[0] + "..."


def print_results(
    indices: np.ndarray,
    urls: list[str],
    titles: list[str],
    domains: list[str],
    db: PageDatabase,
) -> None:
    """Print search results to the console.

    Args:
        indices: Array of corpus indices to display.
        urls: List of all corpus URLs.
        titles: List of all corpus titles.
        domains: List of all corpus domains.
        db: Database connection for fetching snippets and source notes.
    """
    for rank, idx in enumerate(indices, 1):
        url = urls[idx]
        page = db.get(url)
        snippet = format_snippet(page.md_content if page else None)
        sources = db.get_sources(url)

        print(f"\n  [{rank}] {titles[idx]}")
        print(f"      {url}")
        print(f"      domain: {domains[idx]}", end="")
        if sources:
            print(f"  |  notes: {', '.join(sources)}")
        else:
            print()
        print(f"      {snippet}")


def main() -> None:
    """Load model and corpus, then run an interactive search loop."""
    print(f"Loading model: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME, trust_remote_code=True)

    db = PageDatabase(DB_PATH)
    urls, titles, domains, corpus_matrix = load_corpus(db)
    print(f"Loaded {len(urls)} embedded documents.\n")

    try:
        while True:
            query = input("Search: ").strip()
            if not query:
                continue

            indices = search(query, model, corpus_matrix)
            print_results(indices, urls, titles, domains, db)
            print()
    except (KeyboardInterrupt, EOFError):
        print("\nBye.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
