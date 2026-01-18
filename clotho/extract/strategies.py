"""Keyword extraction strategy implementations.

This module defines the ExtractionStrategy protocol and concrete implementations
for various keyword extraction algorithms.
"""

from pathlib import Path
from typing import Protocol

from yake import KeywordExtractor as YakeExtractor

from config import STOPWORDS_FILE


class ExtractionStrategy(Protocol):
    """Protocol for keyword/topic extraction strategies.

    Implementations must return scores normalized to 0-1 range,
    where higher values indicate greater relevance.
    """

    def extract(self, text: str, n: int) -> list[tuple[str, float]]:
        """Extract top n keywords with normalized relevance scores.

        Args:
            text: The text to extract keywords from.
            n: Number of keywords to extract.

        Returns:
            List of (keyword, score) tuples sorted by relevance (highest first).
            Scores are normalized to the 0-1 range.
        """
        ...


class YakeStrategy:
    """YAKE-based keyword extraction.

    YAKE (Yet Another Keyword Extractor) is an unsupervised approach for
    automatic keyword extraction using text statistical features.

    Attributes:
        max_ngram: Maximum n-gram size for keywords.
        dedup_func: Deduplication function ("levs", "jaro", "seqm").
        dedup_threshold: Threshold for considering keywords as duplicates.
        window_size: Co-occurrence window size.
        stopwords: Set of stopwords to exclude.
    """

    DEFAULT_STOPWORDS_PATH: Path = STOPWORDS_FILE

    def __init__(
        self,
        *,
        max_ngram: int = 3,
        dedup_func: str = "levs",
        dedup_threshold: float = 0.7,
        window_size: int = 1,
        stopwords: set[str] | None = None,
    ) -> None:
        """Initialize the YAKE strategy.

        Args:
            max_ngram: Maximum n-gram size for keywords.
            dedup_func: Deduplication function ("levs", "jaro", "seqm").
            dedup_threshold: Threshold for considering keywords as duplicates.
            window_size: Co-occurrence window size.
            stopwords: Custom stopword set. If None, loads from default file.
        """
        self.max_ngram = max_ngram
        self.dedup_func = dedup_func
        self.dedup_threshold = dedup_threshold
        self.window_size = window_size
        self.stopwords = stopwords or self._load_default_stopwords()

    @classmethod
    def _load_default_stopwords(cls) -> set[str]:
        """Load stopwords from the default file as a set."""
        if cls.DEFAULT_STOPWORDS_PATH.exists():
            return set(
                cls.DEFAULT_STOPWORDS_PATH.read_text(encoding="utf-8").splitlines()
            )
        return set()

    def extract(self, text: str, n: int) -> list[tuple[str, float]]:
        """Extract keywords using YAKE algorithm.

        Args:
            text: The text to extract keywords from.
            n: Number of keywords to extract.

        Returns:
            List of (keyword, score) tuples with normalized scores.
        """
        extractor = YakeExtractor(
            n=self.max_ngram,
            top=n,
            dedupLim=self.dedup_threshold,
            dedupFunc=self.dedup_func,
            windowsSize=self.window_size,
            stopwords=self.stopwords,
        )
        raw_keywords = extractor.extract_keywords(text)
        return self._normalize_scores(raw_keywords)

    def _normalize_scores(
        self, keywords: list[tuple[str, float]]
    ) -> list[tuple[str, float]]:
        """Convert YAKE scores (lower=better) to normalized (higher=better, 0-1).

        YAKE produces scores where lower values indicate higher relevance.
        This method inverts and normalizes them to a 0-1 scale where higher
        values indicate greater relevance.

        Args:
            keywords: Raw YAKE output as (keyword, score) tuples.

        Returns:
            Normalized (keyword, score) tuples where higher scores are better.
        """
        if not keywords:
            return []

        scores = [score for _, score in keywords]
        min_score, max_score = min(scores), max(scores)

        if max_score == min_score:
            return [(kw, 1.0) for kw, _ in keywords]

        # Invert during normalization: lower YAKE score → higher normalized score
        return [
            (kw, 1.0 - (score - min_score) / (max_score - min_score))
            for kw, score in keywords
        ]
