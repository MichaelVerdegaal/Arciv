"""Embed all scraped documents and store vectors in the database."""

import numpy as np
from loguru import logger
from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer

from clotho.db import PageDatabase
from config import DB_PATH, configure_logger

configure_logger(log_file=False)

MODEL_NAME = "perplexity-ai/pplx-embed-v1-0.6B"
MAX_TOKENS = 32000


def truncate_to_max_tokens(text: str, tokenizer: AutoTokenizer) -> str:
    """Truncate text to fit within MAX_TOKENS.

    Args:
        text: The text to potentially truncate.
        tokenizer: Tokenizer to use for encoding/decoding.

    Returns:
        The original text if within limits, otherwise truncated.
    """
    token_ids = tokenizer.encode(text)
    if len(token_ids) <= MAX_TOKENS:
        return text
    return tokenizer.decode(token_ids[:MAX_TOKENS], skip_special_tokens=True)


def main() -> None:
    """Embed all scraped pages and write vectors to the database."""
    logger.info(f"Loading model: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME, trust_remote_code=True)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)

    with PageDatabase(DB_PATH) as db:
        pages = db.get_scraped()

    pages_with_content = [p for p in pages if p.md_content]
    if not pages_with_content:
        logger.warning("No scraped pages with markdown content found")
        return

    logger.info(f"Embedding {len(pages_with_content)} documents")

    texts: list[str] = []
    truncated_count = 0
    for page in pages_with_content:
        assert page.md_content is not None  # checked above
        token_ids = tokenizer.encode(page.md_content)
        if len(token_ids) > MAX_TOKENS:
            truncated_count += 1
            text = tokenizer.decode(token_ids[:MAX_TOKENS], skip_special_tokens=True)
            logger.debug(
                f"Truncated {len(token_ids):,} -> {MAX_TOKENS:,} tokens | {page.url}"
            )
        else:
            text = page.md_content
        texts.append(text)

    if truncated_count:
        logger.info(f"Truncated {truncated_count} documents exceeding {MAX_TOKENS:,} tokens")

    # Encode all documents in one batch (sentence-transformers handles internal batching)
    logger.info("Encoding documents...")
    embeddings: np.ndarray = model.encode(texts, show_progress_bar=True, quantization="binary", batch_size=1)
    logger.info(f"Embedding shape: {embeddings.shape}")

    # Write embeddings to database
    logger.info("Writing embeddings to database...")
    pairs: list[tuple[bytes, str]] = [
        (emb.astype(np.float32).tobytes(), page.url)
        for emb, page in zip(embeddings, pages_with_content)
    ]

    with PageDatabase(DB_PATH) as db:
        db.update_embeddings_batch(pairs)

    logger.info(f"Stored {len(pairs)} embeddings in database")


if __name__ == "__main__":
    main()
