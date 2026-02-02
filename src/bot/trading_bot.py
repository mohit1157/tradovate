"""
Autonomous Trading Bot.

Main bot that combines:
- Tradovate market data and execution
- Technical indicators (EMA, ATR)
- Sentiment analysis (Twitter, Reddit, News, Gemini)
- Risk management
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
import structlog

from config.settings import settings
from ..tradovate.client import TradovateClient
from ..tradovate.websocket_client import TradovateWebSocket
from ..tradovate.market_data import MarketDataHandler
from ..tradovate.order_manager import OrderManager, PositionSide
from ..indicators.indicators import TechnicalIndicators, IndicatorValues
from ..collectors import TwitterCollector, RedditCollector, NewsCollector
from ..sentiment import GeminiAnalyzer, SentimentAggregator, TextProcessor
from ..decision import SignalGenerator, RiskCalculator

logger = structlog.get_logger()


@dataclass
class BotConfig:
    """Bot configuration."""
    # Tradovate credentials
    username: str
    password: str
    app_id: Optional[str] = None
    cid: Optional[int] = None
    secret: Optional[str] = None
    demo: bool = True

    # Trading parameters
    symbols: List[str] = None
    bar_interval: int = 1  # Minutes

    # Technical parameters
    fast_ema: int = 9
    slow_ema: int = 21
    atr_period: int = 14
    stop_atr_mult: float = 1.5
    target_atr_mult: float = 2.0

    # Risk parameters
    max_contracts: int = 1
    max_daily_loss: float = 500.0
    max_trades_per_day: int = 10
    cooldown_seconds: int = 30
    confidence_threshold: float = 0.55

    # Mode
    use_sentiment: bool = True
    use_technicals: bool = True

    def __post_init__(self):
        if self.symbols is None:
            self.symbols = ["MNQH5"]  # Default to micro nasdaq


class TradingBot:
    """
    Main autonomous trading bot.

    Combines real-time market data, technical analysis,
    sentiment analysis, and automated execution.
    """

    def __init__(self, config: BotConfig):
        """
        Initialize trading bot.

        Args:
            config: Bot configuration
        """
        self.config = config

        # Tradovate components
        self.client: Optional[TradovateClient] = None
        self.websocket: Optional[TradovateWebSocket] = None
        self.market_data = MarketDataHandler()
        self.order_manager: Optional[OrderManager] = None

        # Technical analysis
        self.indicators = TechnicalIndicators(
            fast_ema_period=config.fast_ema,
            slow_ema_period=config.slow_ema,
            atr_period=config.atr_period,
        )

        # Sentiment analysis
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
            max_daily_loss=config.max_daily_loss,
            max_trades_per_day=config.max_trades_per_day,
        )
        self.signal_generator: Optional[SignalGenerator] = None

        # State
        self._running = False
        self._last_trade_time: Dict[str, datetime] = {}
        self._last_sentiment_update: Optional[datetime] = None
        self._sentiment_cache: Dict[str, Any] = {}

    async def start(self) -> bool:
        """
        Start the trading bot.

        Returns:
            True if started successfully
        """
        logger.info("Starting trading bot...")

        # Connect to Tradovate
        self.client = TradovateClient(
            username=self.config.username,
            password=self.config.password,
            app_id=self.config.app_id,
            cid=self.config.cid,
            secret=self.config.secret,
            demo=self.config.demo,
        )

        if not await self.client.connect():
            logger.error("Failed to connect to Tradovate")
            return False

        # Initialize order manager
        self.order_manager = OrderManager(
            client=self.client,
            max_daily_loss=self.config.max_daily_loss,
            max_trades_per_day=self.config.max_trades_per_day,
            max_position_size=self.config.max_contracts,
        )

        # Connect WebSocket for real-time data
        self.websocket = TradovateWebSocket(
            access_token=self.client.access_token,
            ws_url=self.client.ws_url,
            md_ws_url=self.client.md_ws_url,
        )

        self.websocket.set_callbacks(
            on_quote=self._on_quote,
            on_chart=self._on_chart,
            on_order=self.order_manager.on_fill_event,
            on_position=self.order_manager.on_position_event,
        )

        if not await self.websocket.connect():
            logger.error("Failed to connect WebSocket")
            return False

        # Initialize sentiment components if enabled
        if self.config.use_sentiment:
            await self._init_sentiment()

        # Initialize signal generator
        self.signal_generator = SignalGenerator(
            risk_calculator=self.risk_calculator,
            gemini_analyzer=self.gemini_analyzer if self.config.use_sentiment else None,
            use_gemini_decision=self.config.use_sentiment,
        )

        # Subscribe to market data
        for symbol in self.config.symbols:
            await self.websocket.subscribe_quote(symbol)
            await self.websocket.subscribe_chart(symbol, interval=self.config.bar_interval)
            logger.info("Subscribed to market data", symbol=symbol)

        # Subscribe to user updates (orders, positions)
        await self.websocket.subscribe_user_updates()

        # Sync existing positions
        await self.order_manager.sync_positions()

        # Load historical data for indicators
        await self._load_historical_data()

        # Start main loop
        self._running = True
        asyncio.create_task(self._main_loop())
        asyncio.create_task(self.websocket.start_heartbeat())

        if self.config.use_sentiment:
            asyncio.create_task(self._sentiment_loop())

        logger.info(
            "Trading bot started",
            symbols=self.config.symbols,
            demo=self.config.demo,
            use_sentiment=self.config.use_sentiment,
        )

        return True

    async def stop(self):
        """Stop the trading bot."""
        logger.info("Stopping trading bot...")
        self._running = False

        # Cancel all orders
        if self.order_manager:
            await self.order_manager.cancel_all_orders()

        # Disconnect
        if self.websocket:
            await self.websocket.disconnect()

        if self.client:
            await self.client.disconnect()

        logger.info("Trading bot stopped")

    async def _init_sentiment(self):
        """Initialize sentiment analysis components."""
        await asyncio.gather(
            self.twitter_collector.initialize(),
            self.reddit_collector.initialize(),
            self.news_collector.initialize(),
            self.gemini_analyzer.initialize(),
            return_exceptions=True,
        )
        logger.info(
            "Sentiment components initialized",
            twitter=self.twitter_collector.enabled,
            reddit=self.reddit_collector.enabled,
            news=self.news_collector.enabled,
            gemini=self.gemini_analyzer._enabled,
        )

    async def _load_historical_data(self):
        """Load historical bar data for indicator warmup."""
        for symbol in self.config.symbols:
            try:
                # Get last 100 bars
                end_time = datetime.utcnow()
                start_time = end_time - timedelta(hours=24)

                data = await self.client.get_chart_data(
                    symbol=symbol,
                    chart_type="MinuteBar",
                    interval=self.config.bar_interval,
                    start_time=start_time,
                    end_time=end_time,
                )

                if data and "bars" in data:
                    self.market_data.process_chart_data(symbol, data)

                    # Calculate indicators
                    closes = self.market_data.get_closes(symbol)
                    highs = self.market_data.get_highs(symbol)
                    lows = self.market_data.get_lows(symbol)

                    if closes:
                        self.indicators.calculate_from_bars(symbol, closes, highs, lows)
                        logger.info(
                            "Historical data loaded",
                            symbol=symbol,
                            bars=len(closes),
                        )

            except Exception as e:
                logger.error("Failed to load historical data", symbol=symbol, error=str(e))

    async def _main_loop(self):
        """Main trading loop."""
        while self._running:
            try:
                for symbol in self.config.symbols:
                    await self._process_symbol(symbol)

                await asyncio.sleep(1)  # Check every second

            except Exception as e:
                logger.error("Main loop error", error=str(e))
                await asyncio.sleep(5)

    async def _process_symbol(self, symbol: str):
        """Process trading logic for a symbol."""
        # Check if we can trade
        can_trade, reason = self.order_manager.can_trade()
        if not can_trade:
            return

        # Check cooldown
        last_trade = self._last_trade_time.get(symbol)
        if last_trade:
            elapsed = (datetime.utcnow() - last_trade).total_seconds()
            if elapsed < self.config.cooldown_seconds:
                return

        # Get current position
        position = self.order_manager.get_position(symbol)
        is_flat = position is None or position.side == PositionSide.FLAT

        # Get indicator values
        indicator_values = self.indicators.get_values(symbol)

        # Skip if indicators not ready
        if indicator_values.ema_fast is None or indicator_values.atr is None:
            return

        # Determine signal
        signal = await self._get_trading_signal(symbol, indicator_values)

        if signal == 0:
            return

        # Get current price
        quote = self.market_data.get_quote(symbol)
        if not quote:
            return

        current_price = quote.last or quote.mid
        if not current_price:
            return

        # Calculate stops
        is_long = signal > 0
        stop_price, target_price = self.indicators.calculate_stop_target(
            symbol,
            current_price,
            is_long,
            self.config.stop_atr_mult,
            self.config.target_atr_mult,
        )

        if not stop_price or not target_price:
            return

        # Execute trade
        if is_flat:
            action = "Buy" if is_long else "Sell"

            order = await self.order_manager.place_bracket_order(
                symbol=symbol,
                action=action,
                quantity=self.config.max_contracts,
                stop_loss=stop_price,
                take_profit=target_price,
            )

            if order:
                self._last_trade_time[symbol] = datetime.utcnow()
                logger.info(
                    "Trade executed",
                    symbol=symbol,
                    action=action,
                    stop=stop_price,
                    target=target_price,
                )

        elif position and position.side != PositionSide.FLAT:
            # Check for reversal signal
            should_reverse = (
                (position.side == PositionSide.LONG and signal < 0) or
                (position.side == PositionSide.SHORT and signal > 0)
            )

            if should_reverse:
                await self.order_manager.flatten_position(symbol)
                self._last_trade_time[symbol] = datetime.utcnow()
                logger.info("Position reversed", symbol=symbol)

    async def _get_trading_signal(
        self,
        symbol: str,
        indicators: IndicatorValues,
    ) -> int:
        """
        Get trading signal combining technicals and sentiment.

        Returns:
            Signal: -1 (sell), 0 (hold), +1 (buy)
        """
        technical_signal = indicators.signal

        # If not using sentiment, just return technical signal
        if not self.config.use_sentiment:
            return technical_signal

        # Get sentiment signal
        sentiment = self._sentiment_cache.get(symbol)
        if not sentiment:
            # Use technical only if no sentiment data
            return technical_signal if self.config.use_technicals else 0

        # Check confidence threshold
        if sentiment.confidence < self.config.confidence_threshold:
            return technical_signal if self.config.use_technicals else 0

        # Convert sentiment action to signal
        sentiment_signal = 0
        if sentiment.action == "BUY":
            sentiment_signal = 1
        elif sentiment.action == "SELL":
            sentiment_signal = -1

        # Combine signals
        if self.config.use_technicals:
            # Require agreement for higher confidence
            if technical_signal == sentiment_signal:
                return technical_signal
            elif technical_signal != 0 and sentiment_signal == 0:
                return technical_signal
            elif technical_signal == 0 and sentiment_signal != 0:
                return sentiment_signal if sentiment.confidence > 0.7 else 0
            else:
                # Signals disagree - hold
                return 0
        else:
            return sentiment_signal

    async def _sentiment_loop(self):
        """Background loop for sentiment analysis."""
        while self._running:
            try:
                for symbol in self.config.symbols:
                    await self._update_sentiment(symbol)

                # Update every 60 seconds
                await asyncio.sleep(60)

            except Exception as e:
                logger.error("Sentiment loop error", error=str(e))
                await asyncio.sleep(30)

    async def _update_sentiment(self, symbol: str):
        """Update sentiment for a symbol."""
        try:
            # Collect data from all sources
            all_data = []

            if self.twitter_collector.enabled:
                twitter_data = await self.twitter_collector.collect(symbol, limit=30)
                all_data.extend(twitter_data)

            if self.reddit_collector.enabled:
                reddit_data = await self.reddit_collector.collect(symbol, limit=30)
                all_data.extend(reddit_data)

            if self.news_collector.enabled:
                news_data = await self.news_collector.collect(symbol, limit=20)
                all_data.extend(news_data)

            if not all_data:
                return

            # Analyze with Gemini
            sentiment_results = {}
            if self.gemini_analyzer._enabled:
                texts = [d.text for d in all_data[:15]]
                sources = [d.source.value for d in all_data[:15]]

                result = await self.gemini_analyzer.analyze(texts, symbol, sources)
                for d in all_data[:15]:
                    sentiment_results[d.text[:100]] = result

            # Aggregate
            aggregated = self.sentiment_aggregator.aggregate(
                data=all_data,
                sentiment_results=sentiment_results,
                symbol=symbol,
                time_window_minutes=60,
            )

            self._sentiment_cache[symbol] = aggregated
            self._last_sentiment_update = datetime.utcnow()

            logger.debug(
                "Sentiment updated",
                symbol=symbol,
                score=aggregated.composite_score,
                confidence=aggregated.confidence,
                action=aggregated.action,
            )

        except Exception as e:
            logger.error("Sentiment update error", symbol=symbol, error=str(e))

    def _on_quote(self, data: Dict):
        """Handle quote update."""
        self.market_data.process_quote(data)

    def _on_chart(self, data: Dict):
        """Handle chart/bar update."""
        if "bars" in data:
            # Historical data
            symbol = data.get("symbol", "")
            self.market_data.process_chart_data(symbol, data)

            # Update indicators
            closes = self.market_data.get_closes(symbol)
            highs = self.market_data.get_highs(symbol)
            lows = self.market_data.get_lows(symbol)

            if closes:
                self.indicators.calculate_from_bars(symbol, closes, highs, lows)

    def get_status(self) -> Dict:
        """Get bot status."""
        return {
            "running": self._running,
            "symbols": self.config.symbols,
            "demo": self.config.demo,
            "use_sentiment": self.config.use_sentiment,
            "order_manager": self.order_manager.get_stats() if self.order_manager else {},
            "sentiment_cache": {
                symbol: {
                    "score": s.composite_score,
                    "confidence": s.confidence,
                    "action": s.action,
                }
                for symbol, s in self._sentiment_cache.items()
            },
            "last_sentiment_update": self._last_sentiment_update.isoformat() if self._last_sentiment_update else None,
        }
