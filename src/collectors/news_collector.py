"""News data collector for sentiment analysis."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import aiohttp
import structlog

from .base_collector import BaseCollector, CollectedData, DataSource

logger = structlog.get_logger()


class NewsCollector(BaseCollector):
    """
    Collector for financial news from multiple sources.

    Supports:
    - NewsAPI.org
    - Alpha Vantage News Sentiment
    - Direct RSS feeds (future)
    """

    def __init__(self):
        super().__init__(DataSource.NEWS)
        self._session: Optional[aiohttp.ClientSession] = None
        self._news_api_key: Optional[str] = None
        self._alpha_vantage_key: Optional[str] = None

    async def initialize(self) -> bool:
        """Initialize news API clients."""
        try:
            from config.settings import settings

            if not settings.news_enabled and not settings.alpha_vantage_api_key:
                logger.info("News collector disabled - no API keys configured")
                return False

            self._news_api_key = settings.news_api_key if settings.news_enabled else None
            self._alpha_vantage_key = settings.alpha_vantage_api_key or None

            # Create aiohttp session
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )

            self._enabled = True
            logger.info(
                "News collector initialized",
                newsapi=bool(self._news_api_key),
                alphavantage=bool(self._alpha_vantage_key),
            )
            return True

        except Exception as e:
            logger.error("Failed to initialize News collector", error=str(e))
            return False

    async def close(self):
        """Close the HTTP session."""
        if self._session:
            await self._session.close()
            self._session = None

    async def collect(self, symbol: str, limit: int = 50) -> List[CollectedData]:
        """
        Collect recent news about a symbol from all available sources.

        Args:
            symbol: Trading symbol (e.g., MNQ, ES)
            limit: Maximum number of articles to collect

        Returns:
            List of collected news data
        """
        if not self._enabled:
            return []

        results: List[CollectedData] = []

        # Collect from all available sources in parallel
        tasks = []
        if self._news_api_key:
            tasks.append(self._collect_from_newsapi(symbol, limit // 2))
        if self._alpha_vantage_key:
            tasks.append(self._collect_from_alphavantage(symbol, limit // 2))

        if tasks:
            collected_lists = await asyncio.gather(*tasks, return_exceptions=True)
            for collected in collected_lists:
                if isinstance(collected, list):
                    results.extend(collected)
                elif isinstance(collected, Exception):
                    logger.error("News collection error", error=str(collected))

        # Sort by timestamp (newest first) and limit
        results.sort(key=lambda x: x.timestamp, reverse=True)
        results = results[:limit]

        self._last_collect_time = datetime.utcnow()
        logger.info("News collection complete", symbol=symbol, count=len(results))

        return results

    async def _collect_from_newsapi(
        self, symbol: str, limit: int
    ) -> List[CollectedData]:
        """Collect from NewsAPI.org."""
        if not self._session or not self._news_api_key:
            return []

        from config.settings import get_symbol_terms

        results: List[CollectedData] = []
        search_terms = get_symbol_terms(symbol, "news")

        try:
            # Build query
            query = " OR ".join(f'"{term}"' for term in search_terms)

            # Calculate date range (last 24 hours)
            from_date = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

            url = "https://newsapi.org/v2/everything"
            params = {
                "q": query,
                "from": from_date,
                "sortBy": "publishedAt",
                "language": "en",
                "pageSize": min(limit, 100),
                "apiKey": self._news_api_key,
            }

            async with self._session.get(url, params=params) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.warning(
                        "NewsAPI request failed",
                        status=response.status,
                        error=error_text,
                    )
                    return results

                data = await response.json()

                for article in data.get("articles", []):
                    # Parse timestamp
                    published_at = article.get("publishedAt", "")
                    try:
                        timestamp = datetime.fromisoformat(
                            published_at.replace("Z", "+00:00")
                        )
                    except:
                        timestamp = datetime.now(timezone.utc)

                    # Combine title and description
                    text = article.get("title", "")
                    if article.get("description"):
                        text += "\n\n" + article["description"]
                    if article.get("content"):
                        # NewsAPI truncates content, but include what we have
                        text += "\n\n" + article["content"][:500]

                    # Calculate engagement score based on source reputation
                    source_name = article.get("source", {}).get("name", "")
                    engagement_score = self._get_source_reputation(source_name)

                    collected = CollectedData(
                        source=DataSource.NEWS,
                        symbol=symbol,
                        text=text,
                        timestamp=timestamp,
                        author=article.get("author"),
                        url=article.get("url"),
                        engagement_score=engagement_score,
                        metadata={
                            "source_name": source_name,
                            "api": "newsapi",
                        },
                    )
                    results.append(collected)

        except Exception as e:
            logger.error("NewsAPI collection failed", error=str(e))

        return results

    async def _collect_from_alphavantage(
        self, symbol: str, limit: int
    ) -> List[CollectedData]:
        """Collect from Alpha Vantage News Sentiment API."""
        if not self._session or not self._alpha_vantage_key:
            return []

        from config.settings import get_symbol_terms

        results: List[CollectedData] = []
        search_terms = get_symbol_terms(symbol, "news")

        try:
            # Alpha Vantage uses different topic categories
            topics = "financial_markets,economy_fiscal,economy_monetary"

            url = "https://www.alphavantage.co/query"
            params = {
                "function": "NEWS_SENTIMENT",
                "topics": topics,
                "limit": min(limit, 50),
                "apikey": self._alpha_vantage_key,
            }

            async with self._session.get(url, params=params) as response:
                if response.status != 200:
                    return results

                data = await response.json()

                for article in data.get("feed", []):
                    # Parse timestamp (format: 20231215T120000)
                    time_str = article.get("time_published", "")
                    try:
                        timestamp = datetime.strptime(time_str, "%Y%m%dT%H%M%S")
                        timestamp = timestamp.replace(tzinfo=timezone.utc)
                    except:
                        timestamp = datetime.now(timezone.utc)

                    # Check if article is relevant to our symbol
                    title = article.get("title", "").lower()
                    summary = article.get("summary", "").lower()
                    full_text = title + " " + summary

                    if not any(term.lower() in full_text for term in search_terms):
                        continue

                    # Combine title and summary
                    text = article.get("title", "")
                    if article.get("summary"):
                        text += "\n\n" + article["summary"]

                    # Use Alpha Vantage's sentiment score if available
                    overall_sentiment = article.get("overall_sentiment_score", 0)
                    # Convert -1 to 1 sentiment to 0-1 engagement score
                    engagement_score = (overall_sentiment + 1) / 2

                    collected = CollectedData(
                        source=DataSource.NEWS,
                        symbol=symbol,
                        text=text,
                        timestamp=timestamp,
                        author=None,
                        url=article.get("url"),
                        engagement_score=engagement_score,
                        metadata={
                            "source_name": article.get("source", ""),
                            "api": "alphavantage",
                            "sentiment_score": overall_sentiment,
                            "sentiment_label": article.get("overall_sentiment_label"),
                        },
                    )
                    results.append(collected)

        except Exception as e:
            logger.error("Alpha Vantage collection failed", error=str(e))

        return results

    def _get_source_reputation(self, source_name: str) -> float:
        """
        Get reputation score for a news source.

        Higher scores for more reputable financial news sources.
        """
        # Tier 1 - Major financial news (0.9-1.0)
        tier1 = [
            "bloomberg", "reuters", "cnbc", "wall street journal", "wsj",
            "financial times", "ft", "marketwatch", "barron's"
        ]

        # Tier 2 - Business news (0.7-0.8)
        tier2 = [
            "yahoo finance", "investing.com", "seekingalpha", "benzinga",
            "thestreet", "business insider", "forbes", "fortune"
        ]

        # Tier 3 - General news with finance coverage (0.5-0.6)
        tier3 = [
            "cnn", "bbc", "new york times", "washington post", "associated press"
        ]

        source_lower = source_name.lower()

        for source in tier1:
            if source in source_lower:
                return 0.95

        for source in tier2:
            if source in source_lower:
                return 0.75

        for source in tier3:
            if source in source_lower:
                return 0.55

        # Unknown source
        return 0.4
