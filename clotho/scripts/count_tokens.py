"""Count tokens per document in the database using pplx-embed tokenizer."""

from transformers import AutoTokenizer

from clotho.db import PageDatabase
from config import DB_PATH, configure_logger

from loguru import logger

configure_logger(log_file=False)

MODEL_NAME = "perplexity-ai/pplx-embed-v1-0.6B"

tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)


def count_tokens(text: str) -> int:
    """Count tokens for a given text using the pplx-embed tokenizer.

    Args:
        text: The text to tokenize.

    Returns:
        Number of tokens.
    """
    return len(tokenizer.encode(text))


def main() -> None:
    """Load all pages with markdown content and log token statistics."""
    with PageDatabase(DB_PATH) as db:
        pages = db.get_scraped()

    if not pages:
        logger.warning("No scraped pages found in the database")
        return

    token_counts: list[int] = []

    for page in pages:
        if not page.md_content:
            continue
        tokens = count_tokens(page.md_content)
        token_counts.append(tokens)
        logger.info(f"{tokens:>7,} tokens | {page.url}")

    if not token_counts:
        logger.warning("No pages with markdown content found")
        return

    total = len(token_counts)
    minimum = min(token_counts)
    maximum = max(token_counts)
    average = sum(token_counts) / total

    logger.info("--- Token count summary ---")
    logger.info(f"Documents: {total:,}")
    logger.info(f"Min:       {minimum:,}")
    logger.info(f"Max:       {maximum:,}")
    logger.info(f"Average:   {average:,.0f}")


if __name__ == "__main__":
    main()
