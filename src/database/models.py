"""Database models for trade journaling."""

from datetime import datetime, date
from typing import Optional
from sqlalchemy import Column, Integer, Float, String, DateTime, Date, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class Trade(Base):
    """Trade record."""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    symbol = Column(String(20), nullable=False, index=True)
    action = Column(String(10), nullable=False)  # BUY, SELL
    quantity = Column(Integer, nullable=False)
    entry_price = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True)
    sentiment_score = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    regime = Column(String(20), nullable=True)
    reasoning = Column(Text, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "symbol": self.symbol,
            "action": self.action,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "pnl": self.pnl,
            "sentiment_score": self.sentiment_score,
            "confidence": self.confidence,
            "regime": self.regime,
            "reasoning": self.reasoning,
        }


class SentimentHistory(Base):
    """Sentiment data history."""
    __tablename__ = "sentiment_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    source = Column(String(20), nullable=False)  # twitter, reddit, news
    raw_text = Column(Text, nullable=True)
    sentiment_score = Column(Float, nullable=False)
    confidence = Column(Float, nullable=True)
    themes = Column(Text, nullable=True)  # JSON array as string

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "symbol": self.symbol,
            "source": self.source,
            "sentiment_score": self.sentiment_score,
            "confidence": self.confidence,
            "themes": self.themes,
        }


class DailyPerformance(Base):
    """Daily performance summary."""
    __tablename__ = "daily_performance"

    date = Column(Date, primary_key=True)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    total_pnl = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    best_trade = Column(Float, default=0.0)
    worst_trade = Column(Float, default=0.0)

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat() if self.date else None,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "total_pnl": self.total_pnl,
            "max_drawdown": self.max_drawdown,
            "best_trade": self.best_trade,
            "worst_trade": self.worst_trade,
            "win_rate": self.winning_trades / self.total_trades if self.total_trades > 0 else 0,
        }


def init_db(database_url: str = "sqlite:///./data/trading_bot.db"):
    """Initialize database and create tables."""
    engine = create_engine(database_url, echo=False)
    Base.metadata.create_all(engine)
    return engine


def get_session(engine):
    """Get database session."""
    Session = sessionmaker(bind=engine)
    return Session()
