"""Topic extraction using YAKE keyword extraction.

This module provides a TopicExtractor class that combines markdown cleaning
with YAKE keyword extraction for topic identification.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from yake import KeywordExtractor

from clotho.scrape.clean_markdown import MarkdownCleaner
from config import STOPWORDS_FILE


@dataclass
class Keyword:
    """A keyword extracted from text with its relevance score."""

    text: str
    score: float

    def __repr__(self) -> str:
        return f"Keyword({self.text!r}, score={self.score:.4f})"


class TopicExtractor:
    """Extract topics from markdown content using YAKE keyword extraction.

    Uses composition to combine MarkdownCleaner for text preprocessing
    and YAKE for keyword extraction. This design allows:
    - Easy swapping of the keyword extraction algorithm
    - Flexible text preprocessing pipelines
    - Independent testing of components

    Attributes:
        extractor: The underlying YAKE KeywordExtractor instance.
        stopwords: Set of stopwords used for filtering.
    """

    DEFAULT_STOPWORDS_PATH = STOPWORDS_FILE

    def __init__(
        self,
        *,
        top_n: int = 20,
        max_ngram: int = 3,
        stopwords: set[str] | None = None,
        dedup_func: str = "levs",
        dedup_threshold: float = 0.7,
        window_size: int = 1,
    ) -> None:
        """Initialize the topic extractor.

        Args:
            top_n: Maximum number of keywords to extract.
            max_ngram: Maximum n-gram size for keywords.
            stopwords: Custom stopword set. If None, loads from default file.
            dedup_func: Deduplication function ("levs", "jaro", "seqm").
            dedup_threshold: Threshold for considering keywords as duplicates.
            window_size: Co-occurrence window size.
        """
        self.stopwords = stopwords or self._load_default_stopwords()
        self.top_n = top_n

        self.extractor = KeywordExtractor(
            top=top_n,
            n=max_ngram,
            stopwords=self.stopwords,
            dedup_func=dedup_func,
            dedupLim=dedup_threshold,
            windowsSize=window_size,
        )

    @classmethod
    def _load_default_stopwords(cls) -> set[str]:
        """Load stopwords from the default file as a set."""
        if cls.DEFAULT_STOPWORDS_PATH.exists():
            return set(
                cls.DEFAULT_STOPWORDS_PATH.read_text(encoding="utf-8").splitlines()
            )
        return set()

    def preprocess(self, text: str) -> str:
        """Clean markdown text for keyword extraction.

        Removes formatting that could interfere with keyword detection.

        Args:
            text: Raw markdown content.

        Returns:
            Cleaned text suitable for keyword extraction.
        """
        return (
            MarkdownCleaner(text)
            .strip_bold_italic()
            .strip_inline_code()
            .cleanup_lists()
            .text
        )

    def extract(self, text: str, preprocess: bool = True) -> Sequence[Keyword]:
        """Extract keywords from text.

        Args:
            text: Markdown or plain text content.
            preprocess: Whether to apply markdown cleaning before extraction.

        Returns:
            Sequence of Keyword objects sorted by score (lower is more relevant).
        """
        if preprocess:
            text = self.preprocess(text)

        raw_keywords = self.extractor.extract_keywords(text)
        return [Keyword(text=kw, score=score) for kw, score in raw_keywords]

    def extract_top(
        self, text: str, n: int | None = None, preprocess: bool = True
    ) -> Sequence[Keyword]:
        """Extract the top N most relevant keywords.

        Args:
            text: Markdown or plain text content.
            n: Number of keywords to return. Defaults to top_n from init.
            preprocess: Whether to apply markdown cleaning before extraction.

        Returns:
            Sequence of the top N Keyword objects sorted by score.
        """
        keywords = self.extract(text, preprocess=preprocess)
        n = n or self.top_n
        return sorted(keywords, key=lambda k: k.score)[:n]
