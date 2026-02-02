"""
Configuration settings for the Autonomous Trading Bot.
Loads from environment variables with sensible defaults.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API Keys
    gemini_api_key: str = Field(default="", env="GEMINI_API_KEY")

    # Twitter
    twitter_api_key: str = Field(default="", env="TWITTER_API_KEY")
    twitter_api_secret: str = Field(default="", env="TWITTER_API_SECRET")
    twitter_access_token: str = Field(default="", env="TWITTER_ACCESS_TOKEN")
    twitter_access_token_secret: str = Field(default="", env="TWITTER_ACCESS_TOKEN_SECRET")
    twitter_bearer_token: str = Field(default="", env="TWITTER_BEARER_TOKEN")

    # Reddit
    reddit_client_id: str = Field(default="", env="REDDIT_CLIENT_ID")
    reddit_client_secret: str = Field(default="", env="REDDIT_CLIENT_SECRET")
    reddit_user_agent: str = Field(default="TradingBot/1.0", env="REDDIT_USER_AGENT")

    # News
    news_api_key: str = Field(default="", env="NEWS_API_KEY")
    alpha_vantage_api_key: str = Field(default="", env="ALPHA_VANTAGE_API_KEY")

    # Server
    server_host: str = Field(default="127.0.0.1", env="SERVER_HOST")
    server_port: int = Field(default=8787, env="SERVER_PORT")

    # Trading
    default_symbols: str = Field(default="MNQ,MES,ES,NQ", env="DEFAULT_SYMBOLS")
    confidence_threshold: float = Field(default=0.55, env="CONFIDENCE_THRESHOLD")
    max_daily_loss: float = Field(default=500.0, env="MAX_DAILY_LOSS")
    max_trades_per_day: int = Field(default=10, env="MAX_TRADES_PER_DAY")
    cooldown_seconds: int = Field(default=30, env="COOLDOWN_SECONDS")

    # Sentiment Weights
    twitter_weight: float = Field(default=0.3, env="TWITTER_WEIGHT")
    reddit_weight: float = Field(default=0.3, env="REDDIT_WEIGHT")
    news_weight: float = Field(default=0.4, env="NEWS_WEIGHT")

    # Logging
    log_level: str = Field(default="INFO", env="LOG_LEVEL")

    # Database
    database_url: str = Field(default="sqlite:///./data/trading_bot.db", env="DATABASE_URL")

    @property
    def symbols(self) -> List[str]:
        """Parse comma-separated symbols into list."""
        return [s.strip() for s in self.default_symbols.split(",")]

    @property
    def twitter_enabled(self) -> bool:
        """Check if Twitter credentials are configured."""
        return bool(self.twitter_bearer_token)

    @property
    def reddit_enabled(self) -> bool:
        """Check if Reddit credentials are configured."""
        return bool(self.reddit_client_id and self.reddit_client_secret)

    @property
    def news_enabled(self) -> bool:
        """Check if News API is configured."""
        return bool(self.news_api_key)

    @property
    def gemini_enabled(self) -> bool:
        """Check if Gemini API is configured."""
        return bool(self.gemini_api_key)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# Global settings instance
settings = Settings()


# Symbol mappings for different data sources
SYMBOL_MAPPINGS = {
    # NinjaTrader symbol -> Search terms
    "MNQ": {
        "name": "Micro E-mini Nasdaq-100",
        "twitter_terms": ["$MNQ", "$NQ", "nasdaq futures", "NQ futures", "tech futures"],
        "reddit_terms": ["MNQ", "NQ", "nasdaq", "tech stocks", "QQQ"],
        "news_terms": ["Nasdaq", "technology stocks", "tech sector"],
    },
    "MES": {
        "name": "Micro E-mini S&P 500",
        "twitter_terms": ["$MES", "$ES", "SP500 futures", "ES futures", "SPY"],
        "reddit_terms": ["MES", "ES", "S&P 500", "SPY", "SPX"],
        "news_terms": ["S&P 500", "stock market", "Wall Street"],
    },
    "ES": {
        "name": "E-mini S&P 500",
        "twitter_terms": ["$ES", "ES futures", "SP500", "SPX futures"],
        "reddit_terms": ["ES", "S&P 500", "SPY", "SPX"],
        "news_terms": ["S&P 500", "stock market", "equities"],
    },
    "NQ": {
        "name": "E-mini Nasdaq-100",
        "twitter_terms": ["$NQ", "NQ futures", "nasdaq futures", "QQQ"],
        "reddit_terms": ["NQ", "nasdaq", "QQQ", "tech"],
        "news_terms": ["Nasdaq", "technology", "big tech"],
    },
    "CL": {
        "name": "Crude Oil",
        "twitter_terms": ["$CL", "crude oil", "oil futures", "WTI"],
        "reddit_terms": ["crude oil", "oil", "WTI", "energy"],
        "news_terms": ["crude oil", "oil prices", "OPEC", "energy"],
    },
    "GC": {
        "name": "Gold",
        "twitter_terms": ["$GC", "gold futures", "gold price", "XAU"],
        "reddit_terms": ["gold", "GLD", "precious metals"],
        "news_terms": ["gold", "precious metals", "safe haven"],
    },
}


def get_symbol_terms(symbol: str, source: str) -> List[str]:
    """Get search terms for a symbol and data source."""
    if symbol not in SYMBOL_MAPPINGS:
        return [symbol]

    mapping = SYMBOL_MAPPINGS[symbol]
    key = f"{source}_terms"
    return mapping.get(key, [symbol])
