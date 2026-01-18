"""Extraction with pluggable strategies.

This module provides an Extractor class that uses the Strategy pattern
to allow swapping extraction algorithms at runtime.
"""

from .strategies import ExtractionStrategy


class Extractor:
    """Extracts keywords or topics using configurable strategies.

    This class implements the Strategy pattern, allowing different extraction
    algorithms to be used interchangeably. A default strategy can be set at
    initialization, but can be overridden per extraction call.

    Example:
        >>> from clotho.extract import Extractor, YakeStrategy
        >>> extractor = Extractor(default_strategy=YakeStrategy(n=15, max_ngram=2))
        >>> keywords = extractor.extract(text)
        >>> # Override at call time
        >>> keywords = extractor.extract(text, strategy=YakeStrategy(n=10))

    Attributes:
        default_strategy: The default extraction strategy to use.
    """

    def __init__(self, default_strategy: ExtractionStrategy | None = None) -> None:
        """Initialize the extractor.

        Args:
            default_strategy: The default strategy to use for extraction.
                If None, a strategy must be provided to each extract() call.
        """
        self.default_strategy = default_strategy

    def extract(
        self,
        text: str,
        strategy: ExtractionStrategy | None = None,
    ) -> list[tuple[str, float]]:
        """Extract using the specified or default strategy.

        Args:
            text: The text to extract from.
            strategy: Override strategy for this extraction. If None, uses
                the default_strategy.

        Returns:
            List of (item, score) tuples sorted by relevance (highest first).
            Scores are normalized to the 0-1 range.

        Raises:
            ValueError: If no strategy is provided and no default is set.
        """
        active_strategy = strategy or self.default_strategy
        if active_strategy is None:
            raise ValueError("No extraction strategy provided")
        return active_strategy.extract(text)
