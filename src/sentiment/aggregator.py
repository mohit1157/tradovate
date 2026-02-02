"""Sentiment aggregator combining multiple sources."""

from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass, field
import math
import structlog

from ..collectors.base_collector import CollectedData, DataSource
from .gemini_analyzer import SentimentResult

logger = structlog.get_logger()


@dataclass
class AggregatedSentiment:
    """Aggregated sentiment from multiple sources."""
    symbol: str
    composite_score: float  # -1.0 to +1.0
    confidence: float  # 0.0 to 1.0
    action: str  # BUY, SELL, HOLD
    source_breakdown: Dict[str, float]  # source -> score
    data_points: int
    time_window_minutes: int
    timestamp: datetime
    themes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "composite_score": self.composite_score,
            "confidence": self.confidence,
            "action": self.action,
            "source_breakdown": self.source_breakdown,
            "data_points": self.data_points,
            "time_window_minutes": self.time_window_minutes,
            "timestamp": self.timestamp.isoformat(),
            "themes": self.themes,
        }


class SentimentAggregator:
    """
    Aggregates sentiment from multiple data sources.

    Applies:
    - Time decay weighting (recent data weighted higher)
    - Source reliability weighting
    - Engagement-based weighting
    - Conflict detection and confidence adjustment
    """

    def __init__(
        self,
        twitter_weight: float = 0.3,
        reddit_weight: float = 0.3,
        news_weight: float = 0.4,
        time_decay_halflife_minutes: float = 30.0,
    ):
        """
        Initialize aggregator.

        Args:
            twitter_weight: Weight for Twitter sentiment
            reddit_weight: Weight for Reddit sentiment
            news_weight: Weight for news sentiment
            time_decay_halflife_minutes: Half-life for time decay weighting
        """
        self.source_weights = {
            DataSource.TWITTER: twitter_weight,
            DataSource.REDDIT: reddit_weight,
            DataSource.NEWS: news_weight,
        }
        self.time_decay_halflife = time_decay_halflife_minutes

        # Validate weights sum to 1
        total = sum(self.source_weights.values())
        if abs(total - 1.0) > 0.01:
            logger.warning(
                "Source weights don't sum to 1, normalizing",
                total=total,
            )
            for source in self.source_weights:
                self.source_weights[source] /= total

    def aggregate(
        self,
        data: List[CollectedData],
        sentiment_results: Dict[str, SentimentResult],
        symbol: str,
        time_window_minutes: int = 60,
    ) -> AggregatedSentiment:
        """
        Aggregate sentiment from collected data and analysis results.

        Args:
            data: List of collected data items
            sentiment_results: Dict mapping data item ID/text to sentiment result
            symbol: Trading symbol
            time_window_minutes: Time window for aggregation

        Returns:
            AggregatedSentiment result
        """
        if not data:
            return self._empty_result(symbol, time_window_minutes)

        now = datetime.utcnow()
        cutoff = now - timedelta(minutes=time_window_minutes)

        # Filter data within time window
        recent_data = [d for d in data if d.timestamp.replace(tzinfo=None) >= cutoff]

        if not recent_data:
            return self._empty_result(symbol, time_window_minutes)

        # Calculate weighted scores by source
        source_scores: Dict[DataSource, List[tuple]] = {
            source: [] for source in DataSource
        }

        for item in recent_data:
            # Get sentiment result for this item
            key = item.text[:100]  # Use truncated text as key
            sentiment = sentiment_results.get(key)

            if sentiment:
                score = sentiment.sentiment_score
                base_confidence = sentiment.confidence
            else:
                # Use engagement as proxy if no sentiment analysis
                score = 0.0
                base_confidence = 0.3

            # Calculate time decay weight
            age_minutes = (now - item.timestamp.replace(tzinfo=None)).total_seconds() / 60
            time_weight = math.exp(-0.693 * age_minutes / self.time_decay_halflife)

            # Calculate final weight for this data point
            weight = time_weight * item.engagement_score * base_confidence

            source_scores[item.source].append((score, weight))

        # Calculate weighted average for each source
        source_averages: Dict[str, float] = {}
        source_confidences: Dict[str, float] = {}

        for source, scores in source_scores.items():
            if not scores:
                continue

            total_weight = sum(w for _, w in scores)
            if total_weight > 0:
                weighted_avg = sum(s * w for s, w in scores) / total_weight
                source_averages[source.value] = weighted_avg

                # Confidence based on data volume and consistency
                variance = sum((s - weighted_avg) ** 2 * w for s, w in scores) / total_weight
                consistency = 1.0 / (1.0 + variance)
                volume_factor = min(1.0, len(scores) / 10.0)
                source_confidences[source.value] = consistency * volume_factor

        # Calculate composite score
        composite_score = 0.0
        total_weight = 0.0

        for source, score in source_averages.items():
            source_enum = DataSource(source)
            weight = self.source_weights[source_enum]
            confidence = source_confidences.get(source, 0.5)
            composite_score += score * weight * confidence
            total_weight += weight * confidence

        if total_weight > 0:
            composite_score /= total_weight

        # Calculate overall confidence
        # Consider: data volume, source agreement, individual confidences
        if len(source_averages) > 1:
            # Check for agreement between sources
            scores = list(source_averages.values())
            score_variance = sum((s - composite_score) ** 2 for s in scores) / len(scores)
            agreement_factor = 1.0 / (1.0 + score_variance * 4)
        else:
            agreement_factor = 0.7  # Lower confidence with single source

        volume_factor = min(1.0, len(recent_data) / 20.0)
        avg_source_confidence = sum(source_confidences.values()) / max(1, len(source_confidences))

        overall_confidence = agreement_factor * volume_factor * avg_source_confidence

        # Determine action
        action = self._determine_action(composite_score, overall_confidence)

        # Collect themes from sentiment results
        all_themes = []
        for result in sentiment_results.values():
            all_themes.extend(result.key_themes)
        # Get most common themes
        theme_counts = {}
        for theme in all_themes:
            theme_counts[theme] = theme_counts.get(theme, 0) + 1
        top_themes = sorted(theme_counts.keys(), key=lambda x: theme_counts[x], reverse=True)[:5]

        return AggregatedSentiment(
            symbol=symbol,
            composite_score=composite_score,
            confidence=overall_confidence,
            action=action,
            source_breakdown=source_averages,
            data_points=len(recent_data),
            time_window_minutes=time_window_minutes,
            timestamp=now,
            themes=top_themes,
        )

    def _determine_action(self, score: float, confidence: float) -> str:
        """Determine trading action from score and confidence."""
        from config.settings import settings

        threshold = settings.confidence_threshold

        if confidence < threshold:
            return "HOLD"

        if score > 0.3:
            return "BUY"
        elif score < -0.3:
            return "SELL"
        else:
            return "HOLD"

    def _empty_result(self, symbol: str, time_window: int) -> AggregatedSentiment:
        """Return empty/neutral result."""
        return AggregatedSentiment(
            symbol=symbol,
            composite_score=0.0,
            confidence=0.0,
            action="HOLD",
            source_breakdown={},
            data_points=0,
            time_window_minutes=time_window,
            timestamp=datetime.utcnow(),
            themes=[],
        )

    def quick_aggregate(
        self,
        sentiment_results: List[SentimentResult],
        symbol: str,
    ) -> AggregatedSentiment:
        """
        Quick aggregation of sentiment results without raw data.

        Args:
            sentiment_results: List of sentiment analysis results
            symbol: Trading symbol

        Returns:
            AggregatedSentiment
        """
        if not sentiment_results:
            return self._empty_result(symbol, 60)

        # Simple average
        total_score = 0.0
        total_confidence = 0.0

        for result in sentiment_results:
            total_score += result.sentiment_score * result.confidence
            total_confidence += result.confidence

        if total_confidence > 0:
            composite_score = total_score / total_confidence
            avg_confidence = total_confidence / len(sentiment_results)
        else:
            composite_score = 0.0
            avg_confidence = 0.0

        # Collect themes
        all_themes = []
        for result in sentiment_results:
            all_themes.extend(result.key_themes)
        theme_counts = {}
        for theme in all_themes:
            theme_counts[theme] = theme_counts.get(theme, 0) + 1
        top_themes = sorted(theme_counts.keys(), key=lambda x: theme_counts[x], reverse=True)[:5]

        action = self._determine_action(composite_score, avg_confidence)

        return AggregatedSentiment(
            symbol=symbol,
            composite_score=composite_score,
            confidence=avg_confidence,
            action=action,
            source_breakdown={},
            data_points=len(sentiment_results),
            time_window_minutes=60,
            timestamp=datetime.utcnow(),
            themes=top_themes,
        )
