"""
Enhanced Signal Server for NinjaTrader Integration.

Production-ready HTTP server providing trading signals based on
sentiment analysis from Twitter, Reddit, and news sources,
processed through Google Gemini AI.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from contextlib import asynccontextmanager
import structlog
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from cachetools import TTLCache

from config.settings import settings
from ..collectors import TwitterCollector, RedditCollector, NewsCollector, CollectedData
from ..sentiment import GeminiAnalyzer, SentimentAggregator, TextProcessor
from ..decision import SignalGenerator, RiskCalculator, TradingSignal

logger = structlog.get_logger()


# Response models
class SignalResponse(BaseModel):
    """Response model for /signal endpoint."""
    action: str
    qty: int
    confidence: float


class HealthResponse(BaseModel):
    """Response model for /health endpoint."""
    status: str
    timestamp: str
    components: Dict[str, bool]


class MetricsResponse(BaseModel):
    """Response model for /metrics endpoint."""
    total_requests: int
    signals_generated: Dict[str, int]
    last_signal_time: Optional[str]
    uptime_seconds: float
    risk_stats: Dict


class SignalService:
    """
    Core service that orchestrates data collection, sentiment analysis,
    and signal generation.
    """

    def __init__(self):
        # Components
        self.twitter_collector = TwitterCollector()
        self.reddit_collector = RedditCollector()
        self.news_collector = NewsCollector()
        self.gemini_analyzer = GeminiAnalyzer()
        self.text_processor = TextProcessor()
        self.sentiment_aggregator = SentimentAggregator(
            twitter_weight=settings.twitter_weight,
            reddit_weight=settings.reddit_weight,
            news_weight=settings.news_weight,
        )
        self.risk_calculator = RiskCalculator(
            max_daily_loss=settings.max_daily_loss,
            max_trades_per_day=settings.max_trades_per_day,
        )
        self.signal_generator: Optional[SignalGenerator] = None

        # Caching
        self._signal_cache: TTLCache = TTLCache(maxsize=100, ttl=30)  # 30 second cache
        self._data_cache: Dict[str, List[CollectedData]] = {}
        self._last_collection: Dict[str, datetime] = {}

        # Metrics
        self._start_time = datetime.utcnow()
        self._total_requests = 0
        self._signals_by_action: Dict[str, int] = {"BUY": 0, "SELL": 0, "HOLD": 0}
        self._last_signal_time: Optional[datetime] = None

        # Background collection
        self._collection_task: Optional[asyncio.Task] = None
        self._is_running = False

    async def initialize(self) -> bool:
        """Initialize all components."""
        logger.info("Initializing signal service...")

        # Initialize collectors (non-blocking, some may fail)
        results = await asyncio.gather(
            self.twitter_collector.initialize(),
            self.reddit_collector.initialize(),
            self.news_collector.initialize(),
            self.gemini_analyzer.initialize(),
            return_exceptions=True,
        )

        twitter_ok, reddit_ok, news_ok, gemini_ok = results

        logger.info(
            "Collectors initialized",
            twitter=twitter_ok,
            reddit=reddit_ok,
            news=news_ok,
            gemini=gemini_ok,
        )

        # Initialize signal generator
        self.signal_generator = SignalGenerator(
            risk_calculator=self.risk_calculator,
            gemini_analyzer=self.gemini_analyzer if gemini_ok else None,
            use_gemini_decision=bool(gemini_ok),
        )

        # Start background collection
        self._is_running = True
        self._collection_task = asyncio.create_task(self._background_collection())

        return True

    async def shutdown(self):
        """Shutdown service and cleanup."""
        logger.info("Shutting down signal service...")
        self._is_running = False

        if self._collection_task:
            self._collection_task.cancel()
            try:
                await self._collection_task
            except asyncio.CancelledError:
                pass

        if self.news_collector._session:
            await self.news_collector.close()

    async def _background_collection(self):
        """Background task to periodically collect data."""
        while self._is_running:
            try:
                for symbol in settings.symbols:
                    await self._collect_data_for_symbol(symbol)

                # Wait before next collection cycle
                await asyncio.sleep(60)  # Collect every 60 seconds

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Background collection error", error=str(e))
                await asyncio.sleep(30)

    async def _collect_data_for_symbol(self, symbol: str):
        """Collect data from all sources for a symbol."""
        # Check if we collected recently
        last_time = self._last_collection.get(symbol)
        if last_time and (datetime.utcnow() - last_time) < timedelta(seconds=30):
            return

        all_data: List[CollectedData] = []

        # Collect from all enabled sources in parallel
        tasks = []
        if self.twitter_collector.enabled:
            tasks.append(self.twitter_collector.collect(symbol, limit=30))
        if self.reddit_collector.enabled:
            tasks.append(self.reddit_collector.collect(symbol, limit=30))
        if self.news_collector.enabled:
            tasks.append(self.news_collector.collect(symbol, limit=20))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, list):
                    all_data.extend(result)

        self._data_cache[symbol] = all_data
        self._last_collection[symbol] = datetime.utcnow()

        logger.debug(
            "Data collected",
            symbol=symbol,
            count=len(all_data),
        )

    async def get_signal(self, symbol: str) -> TradingSignal:
        """
        Get trading signal for a symbol.

        Args:
            symbol: Trading symbol (e.g., MNQ, ES)

        Returns:
            TradingSignal with action, quantity, and confidence
        """
        self._total_requests += 1

        # Check cache first
        cached = self._signal_cache.get(symbol)
        if cached:
            return cached

        # Ensure we have recent data
        if symbol not in self._data_cache:
            await self._collect_data_for_symbol(symbol)

        data = self._data_cache.get(symbol, [])

        if not data:
            signal = self.signal_generator.generate_hold_signal(
                symbol, "No data available"
            )
            self._record_signal(signal)
            return signal

        # Analyze sentiment with Gemini
        sentiment_results = {}
        if self.gemini_analyzer._enabled:
            # Batch analyze (limit to most recent/relevant items)
            texts = [d.text for d in data[:15]]
            sources = [d.source.value for d in data[:15]]

            try:
                result = await self.gemini_analyzer.analyze(texts, symbol, sources)
                for i, d in enumerate(data[:15]):
                    sentiment_results[d.text[:100]] = result
            except Exception as e:
                logger.error("Sentiment analysis failed", error=str(e))

        # Aggregate sentiment
        aggregated = self.sentiment_aggregator.aggregate(
            data=data,
            sentiment_results=sentiment_results,
            symbol=symbol,
            time_window_minutes=60,
        )

        # Generate signal
        signal = await self.signal_generator.generate(
            symbol=symbol,
            aggregated_sentiment=aggregated,
            technical_signal=None,  # Could be added via API
        )

        # Cache and record
        self._signal_cache[symbol] = signal
        self._record_signal(signal)

        return signal

    def _record_signal(self, signal: TradingSignal):
        """Record signal for metrics."""
        self._last_signal_time = datetime.utcnow()
        self._signals_by_action[signal.action] = (
            self._signals_by_action.get(signal.action, 0) + 1
        )

    def get_metrics(self) -> dict:
        """Get service metrics."""
        uptime = (datetime.utcnow() - self._start_time).total_seconds()
        return {
            "total_requests": self._total_requests,
            "signals_generated": self._signals_by_action,
            "last_signal_time": self._last_signal_time.isoformat() if self._last_signal_time else None,
            "uptime_seconds": uptime,
            "risk_stats": self.risk_calculator.get_stats(),
        }

    def get_health(self) -> dict:
        """Get service health status."""
        return {
            "status": "healthy" if self._is_running else "degraded",
            "timestamp": datetime.utcnow().isoformat(),
            "components": {
                "twitter": self.twitter_collector.enabled,
                "reddit": self.reddit_collector.enabled,
                "news": self.news_collector.enabled,
                "gemini": self.gemini_analyzer._enabled,
                "background_collector": self._collection_task is not None and not self._collection_task.done(),
            },
        }


# Global service instance
signal_service: Optional[SignalService] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global signal_service
    signal_service = SignalService()
    await signal_service.initialize()
    yield
    await signal_service.shutdown()


def create_app() -> FastAPI:
    """Create FastAPI application."""
    app = FastAPI(
        title="Autonomous Trading Bot Signal Server",
        description="Provides AI-powered trading signals based on sentiment analysis",
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.get("/signal", response_model=SignalResponse)
    async def get_signal(symbol: str = Query(..., description="Trading symbol (e.g., MNQ, ES)")):
        """
        Get trading signal for a symbol.

        Returns action (BUY/SELL/HOLD), quantity, and confidence.
        """
        if not signal_service:
            raise HTTPException(status_code=503, detail="Service not initialized")

        try:
            signal = await signal_service.get_signal(symbol.upper())
            return signal.to_ninja_response()
        except Exception as e:
            logger.error("Signal generation failed", symbol=symbol, error=str(e))
            return {"action": "HOLD", "qty": 0, "confidence": 0.0}

    @app.get("/health", response_model=HealthResponse)
    async def health_check():
        """Check service health."""
        if not signal_service:
            return {"status": "starting", "timestamp": datetime.utcnow().isoformat(), "components": {}}
        return signal_service.get_health()

    @app.get("/metrics", response_model=MetricsResponse)
    async def get_metrics():
        """Get service metrics."""
        if not signal_service:
            raise HTTPException(status_code=503, detail="Service not initialized")
        return signal_service.get_metrics()

    @app.post("/kill")
    async def kill_trading(reason: str = Query("Manual kill switch")):
        """Activate kill switch to stop all trading."""
        if not signal_service:
            raise HTTPException(status_code=503, detail="Service not initialized")
        signal_service.risk_calculator.kill_trading(reason)
        return {"status": "killed", "reason": reason}

    @app.post("/resume")
    async def resume_trading():
        """Deactivate kill switch."""
        if not signal_service:
            raise HTTPException(status_code=503, detail="Service not initialized")
        signal_service.risk_calculator.resume_trading()
        return {"status": "resumed"}

    @app.post("/record-trade")
    async def record_trade(pnl: float = Query(..., description="Trade P&L")):
        """Record a completed trade for risk tracking."""
        if not signal_service:
            raise HTTPException(status_code=503, detail="Service not initialized")
        signal_service.risk_calculator.record_trade(pnl)
        return {"status": "recorded", "daily_pnl": signal_service.risk_calculator._daily_pnl}

    return app


# Entry point for running with uvicorn
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.server.signal_server:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=False,
        log_level="info",
    )
