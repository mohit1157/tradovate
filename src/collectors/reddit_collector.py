"""Reddit data collector for sentiment analysis."""

import asyncio
from datetime import datetime, timezone
from typing import List, Optional
import structlog

from .base_collector import BaseCollector, CollectedData, DataSource

logger = structlog.get_logger()


# Subreddits to monitor for trading sentiment
TRADING_SUBREDDITS = [
    "wallstreetbets",
    "stocks",
    "investing",
    "futures",
    "options",
    "StockMarket",
    "daytrading",
]


class RedditCollector(BaseCollector):
    """
    Collector for Reddit data using PRAW (Python Reddit API Wrapper).

    Monitors trading-related subreddits for sentiment.
    """

    def __init__(self):
        super().__init__(DataSource.REDDIT)
        self._reddit = None

    async def initialize(self) -> bool:
        """Initialize Reddit API client."""
        try:
            import praw

            from config.settings import settings

            if not settings.reddit_enabled:
                logger.info("Reddit collector disabled - no credentials configured")
                return False

            # Initialize PRAW client
            self._reddit = praw.Reddit(
                client_id=settings.reddit_client_id,
                client_secret=settings.reddit_client_secret,
                user_agent=settings.reddit_user_agent,
            )

            # Test connection by accessing a subreddit
            await asyncio.to_thread(
                lambda: self._reddit.subreddit("stocks").display_name
            )

            self._enabled = True
            logger.info("Reddit collector initialized successfully")
            return True

        except ImportError:
            logger.warning("praw not installed - Reddit collector disabled")
            return False
        except Exception as e:
            logger.error("Failed to initialize Reddit collector", error=str(e))
            return False

    async def collect(self, symbol: str, limit: int = 50) -> List[CollectedData]:
        """
        Collect recent Reddit posts and comments about a symbol.

        Args:
            symbol: Trading symbol (e.g., MNQ, ES)
            limit: Maximum number of items to collect

        Returns:
            List of collected Reddit data
        """
        if not self._enabled or not self._reddit:
            return []

        from config.settings import get_symbol_terms

        results: List[CollectedData] = []
        search_terms = get_symbol_terms(symbol, "reddit")

        try:
            # Search across multiple subreddits
            for subreddit_name in TRADING_SUBREDDITS:
                if len(results) >= limit:
                    break

                subreddit = await asyncio.to_thread(
                    lambda: self._reddit.subreddit(subreddit_name)
                )

                # Search for posts
                query = " OR ".join(search_terms)
                posts = await asyncio.to_thread(
                    lambda: list(subreddit.search(
                        query,
                        sort="hot",
                        time_filter="day",
                        limit=min(20, limit - len(results)),
                    ))
                )

                for post in posts:
                    # Calculate engagement score
                    engagement = self._calculate_engagement(
                        upvotes=post.score,
                        comments=post.num_comments,
                        awards=len(post.all_awardings) if hasattr(post, 'all_awardings') else 0,
                        upvote_ratio=post.upvote_ratio,
                    )

                    # Combine title and selftext for analysis
                    text = post.title
                    if post.selftext:
                        text += "\n\n" + post.selftext[:1000]  # Limit text length

                    collected = CollectedData(
                        source=DataSource.REDDIT,
                        symbol=symbol,
                        text=text,
                        timestamp=datetime.fromtimestamp(post.created_utc, tz=timezone.utc),
                        author=str(post.author) if post.author else "[deleted]",
                        url=f"https://reddit.com{post.permalink}",
                        engagement_score=engagement,
                        metadata={
                            "post_id": post.id,
                            "subreddit": subreddit_name,
                            "score": post.score,
                            "num_comments": post.num_comments,
                            "upvote_ratio": post.upvote_ratio,
                            "is_post": True,
                        },
                    )
                    results.append(collected)

                # Also get hot posts and check if they mention our terms
                hot_posts = await asyncio.to_thread(
                    lambda: list(subreddit.hot(limit=25))
                )

                for post in hot_posts:
                    # Check if post mentions any of our search terms
                    post_text = (post.title + " " + (post.selftext or "")).lower()
                    if not any(term.lower() in post_text for term in search_terms):
                        continue

                    if len(results) >= limit:
                        break

                    # Skip if already collected
                    if any(r.metadata.get("post_id") == post.id for r in results):
                        continue

                    engagement = self._calculate_engagement(
                        upvotes=post.score,
                        comments=post.num_comments,
                        awards=len(post.all_awardings) if hasattr(post, 'all_awardings') else 0,
                        upvote_ratio=post.upvote_ratio,
                    )

                    text = post.title
                    if post.selftext:
                        text += "\n\n" + post.selftext[:1000]

                    collected = CollectedData(
                        source=DataSource.REDDIT,
                        symbol=symbol,
                        text=text,
                        timestamp=datetime.fromtimestamp(post.created_utc, tz=timezone.utc),
                        author=str(post.author) if post.author else "[deleted]",
                        url=f"https://reddit.com{post.permalink}",
                        engagement_score=engagement,
                        metadata={
                            "post_id": post.id,
                            "subreddit": subreddit_name,
                            "score": post.score,
                            "num_comments": post.num_comments,
                            "upvote_ratio": post.upvote_ratio,
                            "is_post": True,
                        },
                    )
                    results.append(collected)

            self._last_collect_time = datetime.utcnow()
            logger.info(
                "Reddit collection complete",
                symbol=symbol,
                count=len(results),
            )

        except Exception as e:
            logger.error("Reddit collection failed", symbol=symbol, error=str(e))

        return results

    async def collect_comments(
        self, post_id: str, symbol: str, limit: int = 20
    ) -> List[CollectedData]:
        """
        Collect comments from a specific post.

        Args:
            post_id: Reddit post ID
            symbol: Trading symbol for context
            limit: Maximum comments to collect

        Returns:
            List of collected comment data
        """
        if not self._enabled or not self._reddit:
            return []

        results: List[CollectedData] = []

        try:
            submission = await asyncio.to_thread(
                lambda: self._reddit.submission(id=post_id)
            )

            # Expand all comments (may be slow for large threads)
            await asyncio.to_thread(
                lambda: submission.comments.replace_more(limit=0)
            )

            comments = await asyncio.to_thread(
                lambda: list(submission.comments.list())[:limit]
            )

            for comment in comments:
                if not comment.body or comment.body == "[deleted]":
                    continue

                engagement = self._calculate_engagement(
                    upvotes=comment.score,
                    comments=len(comment.replies) if hasattr(comment, 'replies') else 0,
                )

                collected = CollectedData(
                    source=DataSource.REDDIT,
                    symbol=symbol,
                    text=comment.body[:1000],
                    timestamp=datetime.fromtimestamp(comment.created_utc, tz=timezone.utc),
                    author=str(comment.author) if comment.author else "[deleted]",
                    url=f"https://reddit.com{comment.permalink}",
                    engagement_score=engagement,
                    metadata={
                        "comment_id": comment.id,
                        "post_id": post_id,
                        "score": comment.score,
                        "is_post": False,
                    },
                )
                results.append(collected)

        except Exception as e:
            logger.error(
                "Reddit comment collection failed",
                post_id=post_id,
                error=str(e),
            )

        return results

    def _calculate_engagement(
        self,
        upvotes: int = 0,
        comments: int = 0,
        awards: int = 0,
        upvote_ratio: float = 0.5,
    ) -> float:
        """
        Calculate normalized engagement score.

        Args:
            upvotes: Post/comment score
            comments: Number of comments
            awards: Number of awards
            upvote_ratio: Upvote ratio (0-1)

        Returns:
            Normalized engagement score (0-1)
        """
        import math

        # Weight different engagement types
        raw_score = (
            upvotes * 1.0
            + comments * 2.0
            + awards * 5.0
        )

        # Apply upvote ratio as quality multiplier
        quality_multiplier = 0.5 + (upvote_ratio * 0.5)

        # Normalize using log scale
        normalized = math.log1p(raw_score * quality_multiplier) / 12.0

        return min(1.0, max(0.0, normalized))
