"""
Market Data Handler.

Processes and stores real-time market data for use by the trading bot.
"""

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, List, Deque, Callable
import structlog

logger = structlog.get_logger()


@dataclass
class Tick:
    """Single tick/trade."""
    timestamp: datetime
    price: float
    size: int
    bid: Optional[float] = None
    ask: Optional[float] = None


@dataclass
class Bar:
    """OHLCV bar/candle."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    is_complete: bool = False

    def update(self, price: float, size: int = 0):
        """Update bar with new tick."""
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += size


@dataclass
class Quote:
    """Current quote data."""
    symbol: str
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    bid_size: int = 0
    ask_size: int = 0
    volume: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def mid(self) -> float:
        """Get mid price."""
        if self.bid and self.ask:
            return (self.bid + self.ask) / 2
        return self.last

    @property
    def spread(self) -> float:
        """Get bid-ask spread."""
        if self.bid and self.ask:
            return self.ask - self.bid
        return 0.0


class MarketDataHandler:
    """
    Handles and stores real-time market data.

    Maintains:
    - Current quotes
    - Tick history
    - Bar/candle data
    - Calculated indicators
    """

    def __init__(
        self,
        max_ticks: int = 10000,
        max_bars: int = 500,
    ):
        """
        Initialize market data handler.

        Args:
            max_ticks: Maximum ticks to keep in memory
            max_bars: Maximum bars to keep in memory
        """
        self.max_ticks = max_ticks
        self.max_bars = max_bars

        # Data storage by symbol
        self._quotes: Dict[str, Quote] = {}
        self._ticks: Dict[str, Deque[Tick]] = {}
        self._bars: Dict[str, Deque[Bar]] = {}
        self._current_bar: Dict[str, Bar] = {}

        # Callbacks for data updates
        self._on_bar_complete: Optional[Callable] = None
        self._on_quote_update: Optional[Callable] = None

    def set_callbacks(
        self,
        on_bar_complete: Optional[Callable] = None,
        on_quote_update: Optional[Callable] = None,
    ):
        """Set callback functions."""
        self._on_bar_complete = on_bar_complete
        self._on_quote_update = on_quote_update

    def process_quote(self, data: Dict):
        """Process incoming quote data."""
        try:
            symbol = data.get("contractId") or data.get("symbol", "")

            if not symbol:
                return

            # Get or create quote
            if symbol not in self._quotes:
                self._quotes[symbol] = Quote(symbol=str(symbol))

            quote = self._quotes[symbol]

            # Update quote fields
            if "bid" in data:
                quote.bid = float(data["bid"])
            if "offer" in data or "ask" in data:
                quote.ask = float(data.get("offer") or data.get("ask"))
            if "last" in data:
                quote.last = float(data["last"])
            if "bidSize" in data:
                quote.bid_size = int(data["bidSize"])
            if "offerSize" in data or "askSize" in data:
                quote.ask_size = int(data.get("offerSize") or data.get("askSize", 0))
            if "totalVolume" in data:
                quote.volume = int(data["totalVolume"])

            quote.timestamp = datetime.utcnow()

            # Notify callback
            if self._on_quote_update:
                self._on_quote_update(symbol, quote)

        except Exception as e:
            logger.error("Quote processing error", error=str(e), data=data)

    def process_tick(self, symbol: str, price: float, size: int = 0):
        """Process incoming tick data."""
        try:
            # Store tick
            if symbol not in self._ticks:
                self._ticks[symbol] = deque(maxlen=self.max_ticks)

            tick = Tick(
                timestamp=datetime.utcnow(),
                price=price,
                size=size,
                bid=self._quotes.get(symbol, Quote(symbol)).bid,
                ask=self._quotes.get(symbol, Quote(symbol)).ask,
            )
            self._ticks[symbol].append(tick)

            # Update current bar
            self._update_current_bar(symbol, price, size)

        except Exception as e:
            logger.error("Tick processing error", error=str(e))

    def process_bar(self, symbol: str, bar_data: Dict):
        """Process incoming bar/candle data."""
        try:
            if symbol not in self._bars:
                self._bars[symbol] = deque(maxlen=self.max_bars)

            # Parse bar data
            bar = Bar(
                timestamp=datetime.fromisoformat(bar_data.get("timestamp", "").replace("Z", "+00:00")),
                open=float(bar_data.get("open", 0)),
                high=float(bar_data.get("high", 0)),
                low=float(bar_data.get("low", 0)),
                close=float(bar_data.get("close", 0)),
                volume=int(bar_data.get("volume", 0)),
                is_complete=bar_data.get("complete", True),
            )

            if bar.is_complete:
                self._bars[symbol].append(bar)
                if self._on_bar_complete:
                    self._on_bar_complete(symbol, bar)
            else:
                self._current_bar[symbol] = bar

        except Exception as e:
            logger.error("Bar processing error", error=str(e), data=bar_data)

    def process_chart_data(self, symbol: str, data: Dict):
        """Process historical chart data response."""
        try:
            if "bars" not in data:
                return

            if symbol not in self._bars:
                self._bars[symbol] = deque(maxlen=self.max_bars)

            for bar_data in data["bars"]:
                bar = Bar(
                    timestamp=datetime.fromisoformat(bar_data.get("timestamp", "").replace("Z", "+00:00")),
                    open=float(bar_data.get("open", 0)),
                    high=float(bar_data.get("high", 0)),
                    low=float(bar_data.get("low", 0)),
                    close=float(bar_data.get("close", 0)),
                    volume=int(bar_data.get("upVolume", 0) + bar_data.get("downVolume", 0)),
                    is_complete=True,
                )
                self._bars[symbol].append(bar)

            logger.info("Chart data loaded", symbol=symbol, bars=len(data["bars"]))

        except Exception as e:
            logger.error("Chart data processing error", error=str(e))

    def _update_current_bar(self, symbol: str, price: float, size: int):
        """Update current forming bar with tick."""
        if symbol not in self._current_bar:
            self._current_bar[symbol] = Bar(
                timestamp=datetime.utcnow(),
                open=price,
                high=price,
                low=price,
                close=price,
                volume=size,
            )
        else:
            self._current_bar[symbol].update(price, size)

    # ==================== Data Access Methods ====================

    def get_quote(self, symbol: str) -> Optional[Quote]:
        """Get current quote for symbol."""
        return self._quotes.get(symbol)

    def get_last_price(self, symbol: str) -> Optional[float]:
        """Get last traded price."""
        quote = self._quotes.get(symbol)
        if quote:
            return quote.last or quote.mid
        return None

    def get_ticks(self, symbol: str, count: int = 100) -> List[Tick]:
        """Get recent ticks."""
        if symbol not in self._ticks:
            return []
        ticks = list(self._ticks[symbol])
        return ticks[-count:] if len(ticks) > count else ticks

    def get_bars(self, symbol: str, count: int = 100) -> List[Bar]:
        """Get recent completed bars."""
        if symbol not in self._bars:
            return []
        bars = list(self._bars[symbol])
        return bars[-count:] if len(bars) > count else bars

    def get_current_bar(self, symbol: str) -> Optional[Bar]:
        """Get current forming bar."""
        return self._current_bar.get(symbol)

    def get_closes(self, symbol: str, count: int = 100) -> List[float]:
        """Get recent close prices."""
        bars = self.get_bars(symbol, count)
        return [bar.close for bar in bars]

    def get_highs(self, symbol: str, count: int = 100) -> List[float]:
        """Get recent high prices."""
        bars = self.get_bars(symbol, count)
        return [bar.high for bar in bars]

    def get_lows(self, symbol: str, count: int = 100) -> List[float]:
        """Get recent low prices."""
        bars = self.get_bars(symbol, count)
        return [bar.low for bar in bars]

    def get_volumes(self, symbol: str, count: int = 100) -> List[int]:
        """Get recent volumes."""
        bars = self.get_bars(symbol, count)
        return [bar.volume for bar in bars]

    # ==================== Statistics ====================

    def get_stats(self, symbol: str) -> Dict:
        """Get data statistics for a symbol."""
        quote = self._quotes.get(symbol)
        ticks = self._ticks.get(symbol, deque())
        bars = self._bars.get(symbol, deque())

        return {
            "symbol": symbol,
            "has_quote": quote is not None,
            "last_price": quote.last if quote else None,
            "bid": quote.bid if quote else None,
            "ask": quote.ask if quote else None,
            "spread": quote.spread if quote else None,
            "tick_count": len(ticks),
            "bar_count": len(bars),
            "has_current_bar": symbol in self._current_bar,
        }
