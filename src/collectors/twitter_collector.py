"""Twitter/X data collector for sentiment analysis."""

import asyncio
from datetime import datetime, timedelta
from typing import List, Optional
import structlog

from .base_collector import BaseCollector, CollectedData, DataSource

logger = structlog.get_logger()


class TwitterCollector(BaseCollector):
    """
    Collector for Twitter/X data using Twitter API v2.

    Requires Twitter API credentials with at least Basic access.
    """

    def __init__(self):
        super().__init__(DataSource.TWITTER)
        self._client = None
        self._rate_limit_remaining = 100
        self._rate_limit_reset: Optional[datetime] = None

    async def initialize(self) -> bool:
        """Initialize Twitter API client."""
        try:
            # Import here to handle missing dependency gracefully
            import tweepy

            from config.settings import settings

            if not settings.twitter_enabled:
                logger.info("Twitter collector disabled - no credentials configured")
                return False

            # Use bearer token for app-only authentication (higher rate limits)
            self._client = tweepy.Client(
                bearer_token=settings.twitter_bearer_token,
                wait_on_rate_limit=True,
            )

            # Test connection
            # Note: In production, you might want to make a simple API call to verify
            self._enabled = True
            logger.info("Twitter collector initialized successfully")
            return True

        except ImportError:
            logger.warning("tweepy not installed - Twitter collector disabled")
            return False
        except Exception as e:
            logger.error("Failed to initialize Twitter collector", error=str(e))
            return False

    async def collect(self, symbol: str, limit: int = 50) -> List[CollectedData]:
        """
        Collect recent tweets about a symbol.

        Args:
            symbol: Trading symbol (e.g., MNQ, ES)
            limit: Maximum number of tweets to collect

        Returns:
            List of collected tweet data
        """
        if not self._enabled or not self._client:
            return []

        from config.settings import get_symbol_terms

        results: List[CollectedData] = []
        search_terms = get_symbol_terms(symbol, "twitter")

        try:
            # Build search query
            query = " OR ".join(search_terms)
            query += " -is:retweet lang:en"  # Exclude retweets, English only

            # Search recent tweets (last 7 days with Basic access)
            response = await asyncio.to_thread(
                self._client.search_recent_tweets,
                query=query,
                max_results=min(limit, 100),  # API max is 100
                tweet_fields=["created_at", "public_metrics", "author_id"],
                expansions=["author_id"],
                user_fields=["username", "verified"],
            )

            if not response.data:
                logger.debug("No tweets found", symbol=symbol)
                return results

            # Build user lookup
            users = {}
            if response.includes and "users" in response.includes:
                users = {u.id: u for u in response.includes["users"]}

            for tweet in response.data:
                # Calculate engagement score
                metrics = tweet.public_metrics or {}
                engagement = (
                    metrics.get("like_count", 0) * 1.0
                    + metrics.get("retweet_count", 0) * 2.0
                    + metrics.get("reply_count", 0) * 1.5
                    + metrics.get("quote_count", 0) * 2.0
                )
                # Normalize to 0-1 scale (log scale for high engagement)
                import math
                engagement_score = min(1.0, math.log1p(engagement) / 10.0)

                # Get author info
                author = users.get(tweet.author_id)
                author_name = author.username if author else None
                is_verified = author.verified if author else False

                # Boost score for verified accounts
                if is_verified:
                    engagement_score = min(1.0, engagement_score * 1.5)

                collected = CollectedData(
                    source=DataSource.TWITTER,
                    symbol=symbol,
                    text=tweet.text,
                    timestamp=tweet.created_at or datetime.utcnow(),
                    author=author_name,
                    url=f"https://twitter.com/{author_name}/status/{tweet.id}" if author_name else None,
                    engagement_score=engagement_score,
                    metadata={
                        "tweet_id": str(tweet.id),
                        "likes": metrics.get("like_count", 0),
                        "retweets": metrics.get("retweet_count", 0),
                        "replies": metrics.get("reply_count", 0),
                        "verified": is_verified,
                    },
                )
                results.append(collected)

            self._last_collect_time = datetime.utcnow()
            logger.info(
                "Twitter collection complete",
                symbol=symbol,
                count=len(results),
            )

        except Exception as e:
            logger.error("Twitter collection failed", symbol=symbol, error=str(e))

        return results

    async def collect_from_accounts(
        self, accounts: List[str], symbol: str, limit: int = 20
    ) -> List[CollectedData]:
        """
        Collect tweets from specific influential accounts.

        Args:
            accounts: List of Twitter usernames to monitor
            symbol: Trading symbol for context
            limit: Max tweets per account

        Returns:
            List of collected tweet data
        """
        if not self._enabled or not self._client:
            return []

        results: List[CollectedData] = []

        for username in accounts:
            try:
                # Get user ID
                user_response = await asyncio.to_thread(
                    self._client.get_user, username=username
                )

                if not user_response.data:
                    continue

                user_id = user_response.data.id

                # Get user's recent tweets
                tweets_response = await asyncio.to_thread(
                    self._client.get_users_tweets,
                    id=user_id,
                    max_results=min(limit, 100),
                    tweet_fields=["created_at", "public_metrics"],
                )

                if not tweets_response.data:
                    continue

                for tweet in tweets_response.data:
                    metrics = tweet.public_metrics or {}
                    import math
                    engagement = (
                        metrics.get("like_count", 0)
                        + metrics.get("retweet_count", 0) * 2
                    )
                    engagement_score = min(1.0, math.log1p(engagement) / 10.0)

                    collected = CollectedData(
                        source=DataSource.TWITTER,
                        symbol=symbol,
                        text=tweet.text,
                        timestamp=tweet.created_at or datetime.utcnow(),
                        author=username,
                        url=f"https://twitter.com/{username}/status/{tweet.id}",
                        engagement_score=engagement_score,
                        metadata={
                            "tweet_id": str(tweet.id),
                            "monitored_account": True,
                        },
                    )
                    results.append(collected)

            except Exception as e:
                logger.warning(
                    "Failed to collect from account",
                    username=username,
                    error=str(e),
                )

        return results


# List of influential financial Twitter accounts to monitor
INFLUENTIAL_ACCOUNTS = [
    "unusual_whales",
    "DeItaone",  # Walter Bloomberg
    "Fxhedgers",
    "zaborhedge",
    "LiveSquawk",
    "financialjuice",
]
