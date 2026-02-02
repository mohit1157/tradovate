"""Text preprocessing for sentiment analysis."""

import re
from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class ProcessedText:
    """Processed text with extracted entities."""
    cleaned_text: str
    tickers: List[str]
    prices: List[float]
    percentages: List[float]
    sentiment_keywords: Dict[str, int]  # keyword -> count
    word_count: int


class TextProcessor:
    """
    Preprocessor for financial text data.

    Cleans, normalizes, and extracts financial entities from text.
    """

    # Financial slang and abbreviations
    SLANG_MAPPINGS = {
        "hodl": "hold",
        "fomo": "fear of missing out",
        "fud": "fear uncertainty doubt",
        "btfd": "buy the dip",
        "ath": "all time high",
        "atl": "all time low",
        "dd": "due diligence",
        "yolo": "high risk trade",
        "tendies": "profits",
        "bagholder": "holding losing position",
        "diamond hands": "holding through volatility",
        "paper hands": "selling at first sign of loss",
        "moon": "price increase significantly",
        "mooning": "price increasing significantly",
        "to the moon": "expecting large price increase",
        "rekt": "significant loss",
        "pump": "price manipulation upward",
        "dump": "price manipulation downward",
        "short squeeze": "forced buying by short sellers",
        "gamma squeeze": "options driven price spike",
        "calls": "bullish options",
        "puts": "bearish options",
    }

    # Sentiment keywords
    BULLISH_KEYWORDS = [
        "bullish", "buy", "long", "calls", "moon", "rocket", "green",
        "rally", "breakout", "support", "upgrade", "beat", "growth",
        "strong", "surge", "soar", "gain", "profit", "winner", "outperform",
        "accumulate", "undervalued", "opportunity", "upside", "momentum",
    ]

    BEARISH_KEYWORDS = [
        "bearish", "sell", "short", "puts", "crash", "dump", "red",
        "collapse", "breakdown", "resistance", "downgrade", "miss", "weak",
        "plunge", "drop", "fall", "loss", "loser", "underperform", "overvalued",
        "risk", "warning", "downside", "correction", "recession", "fear",
    ]

    # Regex patterns
    TICKER_PATTERN = re.compile(r'\$([A-Z]{1,5})\b')
    PRICE_PATTERN = re.compile(r'\$[\d,]+\.?\d*')
    PERCENTAGE_PATTERN = re.compile(r'[-+]?\d+\.?\d*%')
    URL_PATTERN = re.compile(r'https?://\S+')
    MENTION_PATTERN = re.compile(r'@\w+')
    HASHTAG_PATTERN = re.compile(r'#\w+')

    def __init__(self):
        # Build sentiment keyword sets for fast lookup
        self._bullish_set = set(self.BULLISH_KEYWORDS)
        self._bearish_set = set(self.BEARISH_KEYWORDS)

    def process(self, text: str) -> ProcessedText:
        """
        Process text for sentiment analysis.

        Args:
            text: Raw text input

        Returns:
            ProcessedText with cleaned text and extracted entities
        """
        if not text:
            return ProcessedText(
                cleaned_text="",
                tickers=[],
                prices=[],
                percentages=[],
                sentiment_keywords={},
                word_count=0,
            )

        # Extract entities before cleaning
        tickers = self._extract_tickers(text)
        prices = self._extract_prices(text)
        percentages = self._extract_percentages(text)

        # Clean text
        cleaned = self._clean_text(text)

        # Expand slang
        cleaned = self._expand_slang(cleaned)

        # Extract sentiment keywords
        sentiment_keywords = self._extract_sentiment_keywords(cleaned)

        # Count words
        word_count = len(cleaned.split())

        return ProcessedText(
            cleaned_text=cleaned,
            tickers=tickers,
            prices=prices,
            percentages=percentages,
            sentiment_keywords=sentiment_keywords,
            word_count=word_count,
        )

    def _clean_text(self, text: str) -> str:
        """Remove noise and normalize text."""
        # Convert to lowercase
        text = text.lower()

        # Remove URLs
        text = self.URL_PATTERN.sub(' ', text)

        # Remove mentions but keep hashtags (often meaningful)
        text = self.MENTION_PATTERN.sub(' ', text)

        # Convert hashtags to words
        text = re.sub(r'#(\w+)', r'\1', text)

        # Remove emojis (keep for now, might be useful)
        # text = self._remove_emojis(text)

        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)

        # Remove special characters but keep basic punctuation
        text = re.sub(r'[^\w\s\.\,\!\?\-\%\$]', ' ', text)

        return text.strip()

    def _expand_slang(self, text: str) -> str:
        """Expand financial slang and abbreviations."""
        words = text.split()
        expanded = []

        for word in words:
            # Check if word is slang
            clean_word = word.strip('.,!?')
            if clean_word in self.SLANG_MAPPINGS:
                expanded.append(self.SLANG_MAPPINGS[clean_word])
            else:
                expanded.append(word)

        return ' '.join(expanded)

    def _extract_tickers(self, text: str) -> List[str]:
        """Extract stock/futures tickers from text."""
        matches = self.TICKER_PATTERN.findall(text.upper())
        # Remove duplicates while preserving order
        seen = set()
        tickers = []
        for ticker in matches:
            if ticker not in seen:
                seen.add(ticker)
                tickers.append(ticker)
        return tickers

    def _extract_prices(self, text: str) -> List[float]:
        """Extract price mentions from text."""
        matches = self.PRICE_PATTERN.findall(text)
        prices = []
        for match in matches:
            try:
                # Remove $ and commas
                price_str = match.replace('$', '').replace(',', '')
                price = float(price_str)
                prices.append(price)
            except ValueError:
                continue
        return prices

    def _extract_percentages(self, text: str) -> List[float]:
        """Extract percentage mentions from text."""
        matches = self.PERCENTAGE_PATTERN.findall(text)
        percentages = []
        for match in matches:
            try:
                pct = float(match.replace('%', ''))
                percentages.append(pct)
            except ValueError:
                continue
        return percentages

    def _extract_sentiment_keywords(self, text: str) -> Dict[str, int]:
        """Extract and count sentiment keywords."""
        words = text.lower().split()
        keywords = {}

        for word in words:
            clean_word = word.strip('.,!?')
            if clean_word in self._bullish_set:
                keywords[clean_word] = keywords.get(clean_word, 0) + 1
            elif clean_word in self._bearish_set:
                keywords[clean_word] = keywords.get(clean_word, 0) + 1

        return keywords

    def get_keyword_sentiment(self, keywords: Dict[str, int]) -> float:
        """
        Calculate sentiment score from keywords.

        Returns:
            Sentiment score from -1 (bearish) to +1 (bullish)
        """
        bullish_count = sum(
            count for word, count in keywords.items()
            if word in self._bullish_set
        )
        bearish_count = sum(
            count for word, count in keywords.items()
            if word in self._bearish_set
        )

        total = bullish_count + bearish_count
        if total == 0:
            return 0.0

        return (bullish_count - bearish_count) / total

    def batch_process(self, texts: List[str]) -> List[ProcessedText]:
        """Process multiple texts."""
        return [self.process(text) for text in texts]
