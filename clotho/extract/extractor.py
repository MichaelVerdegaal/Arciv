"""Keyword extraction with pluggable strategies.

This module provides a KeywordExtractor class that uses the Strategy pattern
to allow swapping extraction algorithms at runtime.
"""

from .strategies import ExtractionStrategy


class Extractor:
    """Extracts keywords or topics using configurable strategies.

    This class implements the Strategy pattern, allowing different keyword
    extraction algorithms to be used interchangeably. A default strategy
    can be set at initialization, but can be overridden per extraction call.

    Example:
        >>> from clotho.extract import Extractor, YakeStrategy
        >>> extractor = Extractor(default_strategy=YakeStrategy(max_ngram=2))
        >>> keywords = extractor.extract(text, n=15)
        >>> # Override at call time
        >>> keywords = extractor.extract(text, n=15, strategy=YakeStrategy(max_ngram=3))

    Attributes:
        default_strategy: The default extraction strategy to use.
    """

    def __init__(self, default_strategy: ExtractionStrategy | None = None) -> None:
        """Initialize the keyword extractor.

        Args:
            default_strategy: The default strategy to use for extraction.
                If None, a strategy must be provided to each extract() call.
        """
        self.default_strategy = default_strategy

    def extract(
        self,
        text: str,
        n: int = 10,
        *,
        strategy: ExtractionStrategy | None = None,
    ) -> list[tuple[str, float]]:
        """Extract keywords using the specified or default strategy.

        Args:
            text: The text to extract keywords from.
            n: Number of keywords to extract.
            strategy: Override strategy for this extraction. If None, uses
                the default_strategy.

        Returns:
            List of (keyword, score) tuples sorted by relevance (highest first).
            Scores are normalized to the 0-1 range.

        Raises:
            ValueError: If no strategy is provided and no default is set.
        """
        active_strategy = strategy or self.default_strategy
        if active_strategy is None:
            raise ValueError("No extraction strategy provided")
        return active_strategy.extract(text, n)
