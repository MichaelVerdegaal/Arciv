"""Topic modeling with KeyNMF on scraped markdown notes.

This script discovers latent topics across a corpus of scraped articles
using KeyNMF from turftopic. Unlike keyword extraction (per-document),
topic modeling finds shared themes across the entire corpus.
"""

import os

import torch
from loguru import logger
from sentence_transformers import SentenceTransformer
from turftopic import KeyNMF, Topeax
from turftopic.vectorizers.spacy import LemmaCountVectorizer

from clotho.notes import MarkdownNote
from config import MARKDOWN_DIR, configure_logger

HF_TOKEN = os.getenv("HF_TOKEN")
print(f"Using HF Token: {HF_TOKEN is not None}")
configure_logger()


def build_corpus(notes: list[MarkdownNote]) -> tuple[list[str], list[str]]:
    """Build corpus from markdown notes.

    Args:
        notes: List of MarkdownNote instances

    Returns:
        Tuple of (texts, filenames) for tracking which doc is which
    """
    texts = []
    filenames = []

    for note in notes:
        # Skip empty notes
        if not note.text.strip():
            logger.warning(f"Skipping empty note: {note.filename}")
            continue

        texts.append(note.text)
        filenames.append(note.filename)

    return texts, filenames


def create_topic_model(
    n_topics: int = 10,
    top_n_words: int = 10,
    device: str | None = None,
) -> KeyNMF:
    """Create a KeyNMF model configured for topic modeling.

    Args:
        n_topics: Number of topics to discover
        top_n_words: Number of top words to extract per document for NMF
        device: Device for embedding model ('cuda' or 'cpu')

    Returns:
        Configured KeyNMF instance
    """
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    logger.info(f"Initializing topic model on {device}")

    # Embedding model needs to be small, and be able to do semantic similarity
    encoder = SentenceTransformer(
        "google/embeddinggemma-300m",
        device=device,
        prompts={
            "query": "task: clustering  | query: {content}",
            "passage": "task: clustering  | query: {content}",
        },
        default_prompt_name="query",
        model_kwargs={"dtype": torch.bfloat16},
    )
    # encoder = SentenceTransformer("paraphrase-MiniLM-L6-v2", device=device)

    vectorizer = LemmaCountVectorizer(
        "en_core_web_sm",
        stop_words="english",
        lowercase=True,
        min_df=3,
        ngram_range=(1, 1),
    )
    model = KeyNMF(
        n_components=n_topics,
        encoder=encoder,
        top_n=top_n_words,
        vectorizer=vectorizer,
    )
    # model = Topeax(
    #     encoder=encoder, perplexity=30, vectorizer=vectorizer, random_state=42
    # )

    return model


def main() -> None:
    """Run topic modeling on scraped notes."""
    logger.info("=" * 60)
    logger.info("KeyNMF Topic Modeling on Scraped Notes")
    logger.info("=" * 60)

    # Load all scraped markdown notes
    logger.info(f"Loading notes from: {MARKDOWN_DIR}")
    scraped_notes: list[MarkdownNote] = MarkdownNote.get_note_files(MARKDOWN_DIR)
    logger.info(f"Found {len(scraped_notes)} markdown files")

    # Build corpus
    corpus, filenames = build_corpus(scraped_notes)
    logger.info(f"Built corpus with {len(corpus)} non-empty documents")

    if len(corpus) < 2:
        logger.error("Need at least 2 documents for topic modeling")
        return

    # Determine number of topics
    n_topics = 7
    logger.info(f"Discovering {n_topics} topics")

    # Create and fit model
    model = create_topic_model(n_topics=n_topics)

    logger.info("Fitting topic model...")
    _ = model.fit_transform(corpus)

    # Print discovered topics
    logger.info("\n" + "=" * 60)
    logger.info("DISCOVERED TOPICS")
    logger.info("=" * 60)
    model.print_topics()


if __name__ == "__main__":
    main()
