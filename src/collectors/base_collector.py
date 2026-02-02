"""Base collector class and data models."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from enum import Enum


class DataSource(Enum):
    """Enumeration of data sources."""
    TWITTER = "twitter"
    REDDIT = "reddit"
    NEWS = "news"


@dataclass
class CollectedData:
    """Data collected from a source."""
    source: DataSource
    symbol: str
    text: str
    timestamp: datetime
    author: Optional[str] = None
    url: Optional[str] = None
    engagement_score: float = 0.0  # Likes, upvotes, shares normalized
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "source": self.source.value,
            "symbol": self.symbol,
            "text": self.text,
            "timestamp": self.timestamp.isoformat(),
            "author": self.author,
            "url": self.url,
            "engagement_score": self.engagement_score,
            "metadata": self.metadata,
        }


class BaseCollector(ABC):
    """Base class for all data collectors."""

    def __init__(self, source: DataSource):
        self.source = source
        self._enabled = False
        self._last_collect_time: Optional[datetime] = None

    @property
    def enabled(self) -> bool:
        """Check if collector is enabled."""
        return self._enabled

    @abstractmethod
    async def initialize(self) -> bool:
        """
        Initialize the collector with API credentials.
        Returns True if initialization successful.
        """
        pass

    @abstractmethod
    async def collect(self, symbol: str, limit: int = 50) -> List[CollectedData]:
        """
        Collect data for a symbol.

        Args:
            symbol: Trading symbol (e.g., MNQ, ES)
            limit: Maximum number of items to collect

        Returns:
            List of collected data items
        """
        pass

    async def health_check(self) -> bool:
        """Check if the collector is healthy."""
        return self._enabled

    def get_stats(self) -> dict:
        """Get collector statistics."""
        return {
            "source": self.source.value,
            "enabled": self._enabled,
            "last_collect_time": self._last_collect_time.isoformat() if self._last_collect_time else None,
        }
