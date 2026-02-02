"""Repository for database operations."""

from datetime import datetime, date, timedelta
from typing import List, Optional
import json
from sqlalchemy.orm import Session

from .models import Trade, SentimentHistory, DailyPerformance, init_db, get_session


class TradingRepository:
    """Repository for trade and sentiment data operations."""

    def __init__(self, database_url: str = "sqlite:///./data/trading_bot.db"):
        self.engine = init_db(database_url)

    def _get_session(self) -> Session:
        return get_session(self.engine)

    # Trade operations
    def record_trade(
        self,
        symbol: str,
        action: str,
        quantity: int,
        entry_price: Optional[float] = None,
        sentiment_score: Optional[float] = None,
        confidence: Optional[float] = None,
        reasoning: Optional[str] = None,
    ) -> Trade:
        """Record a new trade."""
        session = self._get_session()
        try:
            trade = Trade(
                symbol=symbol,
                action=action,
                quantity=quantity,
                entry_price=entry_price,
                sentiment_score=sentiment_score,
                confidence=confidence,
                reasoning=reasoning,
            )
            session.add(trade)
            session.commit()
            return trade
        finally:
            session.close()

    def update_trade_exit(
        self,
        trade_id: int,
        exit_price: float,
        pnl: float,
    ) -> Optional[Trade]:
        """Update trade with exit info."""
        session = self._get_session()
        try:
            trade = session.query(Trade).filter(Trade.id == trade_id).first()
            if trade:
                trade.exit_price = exit_price
                trade.pnl = pnl
                session.commit()

                # Update daily performance
                self._update_daily_performance(session, trade)

            return trade
        finally:
            session.close()

    def get_trades(
        self,
        symbol: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Trade]:
        """Get trades with optional filters."""
        session = self._get_session()
        try:
            query = session.query(Trade)

            if symbol:
                query = query.filter(Trade.symbol == symbol)
            if start_date:
                query = query.filter(Trade.timestamp >= start_date)
            if end_date:
                query = query.filter(Trade.timestamp <= end_date)

            return query.order_by(Trade.timestamp.desc()).limit(limit).all()
        finally:
            session.close()

    def get_open_trades(self) -> List[Trade]:
        """Get trades without exit price (open positions)."""
        session = self._get_session()
        try:
            return session.query(Trade).filter(Trade.exit_price == None).all()
        finally:
            session.close()

    # Sentiment operations
    def record_sentiment(
        self,
        symbol: str,
        source: str,
        sentiment_score: float,
        confidence: Optional[float] = None,
        raw_text: Optional[str] = None,
        themes: Optional[List[str]] = None,
    ) -> SentimentHistory:
        """Record sentiment data."""
        session = self._get_session()
        try:
            sentiment = SentimentHistory(
                symbol=symbol,
                source=source,
                sentiment_score=sentiment_score,
                confidence=confidence,
                raw_text=raw_text[:500] if raw_text else None,
                themes=json.dumps(themes) if themes else None,
            )
            session.add(sentiment)
            session.commit()
            return sentiment
        finally:
            session.close()

    def get_sentiment_history(
        self,
        symbol: str,
        hours: int = 24,
    ) -> List[SentimentHistory]:
        """Get sentiment history for a symbol."""
        session = self._get_session()
        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            return (
                session.query(SentimentHistory)
                .filter(SentimentHistory.symbol == symbol)
                .filter(SentimentHistory.timestamp >= cutoff)
                .order_by(SentimentHistory.timestamp.desc())
                .all()
            )
        finally:
            session.close()

    # Daily performance operations
    def _update_daily_performance(self, session: Session, trade: Trade):
        """Update daily performance with trade result."""
        today = date.today()
        perf = session.query(DailyPerformance).filter(DailyPerformance.date == today).first()

        if not perf:
            perf = DailyPerformance(date=today)
            session.add(perf)

        if trade.pnl is not None:
            perf.total_trades += 1
            perf.total_pnl += trade.pnl

            if trade.pnl > 0:
                perf.winning_trades += 1
                perf.best_trade = max(perf.best_trade, trade.pnl)
            else:
                perf.losing_trades += 1
                perf.worst_trade = min(perf.worst_trade, trade.pnl)

            # Update max drawdown (simplified)
            if perf.total_pnl < perf.max_drawdown:
                perf.max_drawdown = perf.total_pnl

        session.commit()

    def get_daily_performance(self, target_date: Optional[date] = None) -> Optional[DailyPerformance]:
        """Get performance for a specific date."""
        session = self._get_session()
        try:
            target = target_date or date.today()
            return session.query(DailyPerformance).filter(DailyPerformance.date == target).first()
        finally:
            session.close()

    def get_performance_history(self, days: int = 30) -> List[DailyPerformance]:
        """Get performance history."""
        session = self._get_session()
        try:
            cutoff = date.today() - timedelta(days=days)
            return (
                session.query(DailyPerformance)
                .filter(DailyPerformance.date >= cutoff)
                .order_by(DailyPerformance.date.desc())
                .all()
            )
        finally:
            session.close()

    def get_statistics(self) -> dict:
        """Get overall trading statistics."""
        session = self._get_session()
        try:
            total_trades = session.query(Trade).count()
            completed_trades = session.query(Trade).filter(Trade.pnl != None).all()

            if not completed_trades:
                return {
                    "total_trades": total_trades,
                    "completed_trades": 0,
                    "total_pnl": 0,
                    "win_rate": 0,
                    "avg_win": 0,
                    "avg_loss": 0,
                    "profit_factor": 0,
                }

            wins = [t for t in completed_trades if t.pnl and t.pnl > 0]
            losses = [t for t in completed_trades if t.pnl and t.pnl < 0]

            total_pnl = sum(t.pnl for t in completed_trades if t.pnl)
            total_wins = sum(t.pnl for t in wins) if wins else 0
            total_losses = abs(sum(t.pnl for t in losses)) if losses else 0

            return {
                "total_trades": total_trades,
                "completed_trades": len(completed_trades),
                "total_pnl": total_pnl,
                "win_rate": len(wins) / len(completed_trades) if completed_trades else 0,
                "avg_win": total_wins / len(wins) if wins else 0,
                "avg_loss": total_losses / len(losses) if losses else 0,
                "profit_factor": total_wins / total_losses if total_losses > 0 else float('inf'),
            }
        finally:
            session.close()
