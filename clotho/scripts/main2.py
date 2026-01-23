"""Topic modeling with KeyNMF on scraped markdown notes.

This script discovers latent topics across a corpus of scraped articles
using KeyNMF from turftopic. Unlike keyword extraction (per-document),
topic modeling finds shared themes across the entire corpus.
"""

import spacy
import torch
from loguru import logger
from sentence_transformers import SentenceTransformer
from sklearn.feature_extraction.text import CountVectorizer
from turftopic import KeyNMF
from turftopic.vectorizers.spacy import LemmaCountVectorizer

from clotho.notes import MarkdownNote
from config import MARKDOWN_DIR


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


def create_keynmf_model(
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

    logger.info(f"Initializing KeyNMF on {device}")

    # Use paraphrase model as recommended in KeyNMF docs
    encoder = SentenceTransformer("paraphrase-MiniLM-L6-v2", device=device)

    vectorizer = LemmaCountVectorizer(
        "en_core_web_sm", stop_words="english", lowercase=True, min_df=3
    )
    model = KeyNMF(
        n_components=n_topics,
        encoder=encoder,
        top_n=top_n_words,
        vectorizer=vectorizer,
        seed_phrase="technology",
    )

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
    n_topics = 10
    logger.info(f"Discovering {n_topics} topics")

    # Create and fit model
    model = create_keynmf_model(n_topics=n_topics)

    logger.info("Fitting KeyNMF model...")
    doc_topic_matrix = model.fit_transform(corpus)

    # Print discovered topics
    logger.info("\n" + "=" * 60)
    logger.info("DISCOVERED TOPICS")
    logger.info("=" * 60)
    model.print_topics()

    # Show document-topic assignments
    logger.info("\n" + "=" * 60)
    logger.info("DOCUMENT-TOPIC ASSIGNMENTS")
    logger.info("=" * 60)

    for i, filename in enumerate(filenames):
        # Get dominant topic for this document
        topic_scores = doc_topic_matrix[i]
        dominant_topic = topic_scores.argmax()
        score = topic_scores[dominant_topic]

        logger.info(
            f"  {filename[:50]:<50} → Topic {dominant_topic} (score: {score:.3f})"
        )

    # Optional: Group documents by topic
    logger.info("\n" + "=" * 60)
    logger.info("DOCUMENTS GROUPED BY TOPIC")
    logger.info("=" * 60)

    for topic_id in range(n_topics):
        # Find documents where this topic is dominant
        docs_in_topic = [
            filenames[i]
            for i in range(len(filenames))
            if doc_topic_matrix[i].argmax() == topic_id
        ]

        if docs_in_topic:
            logger.info(f"\nTopic {topic_id} ({len(docs_in_topic)} docs):")
            for doc in docs_in_topic[:5]:  # Show first 5
                logger.info(f"  - {doc}")
            if len(docs_in_topic) > 5:
                logger.info(f"  ... and {len(docs_in_topic) - 5} more")


if __name__ == "__main__":
    main()
