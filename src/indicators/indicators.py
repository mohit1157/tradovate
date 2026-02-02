"""
Technical Indicators.

Calculates EMA, ATR, and other technical indicators from market data.
"""

from dataclasses import dataclass
from typing import List, Optional, Dict
import math


@dataclass
class IndicatorValues:
    """Current indicator values for a symbol."""
    symbol: str
    ema_fast: Optional[float] = None
    ema_slow: Optional[float] = None
    atr: Optional[float] = None
    rsi: Optional[float] = None
    signal: int = 0  # -1=sell, 0=hold, +1=buy
    cross_up: bool = False
    cross_down: bool = False


class TechnicalIndicators:
    """
    Calculate technical indicators from price data.

    Supports:
    - EMA (Exponential Moving Average)
    - ATR (Average True Range)
    - RSI (Relative Strength Index)
    - Signal generation (crossover detection)
    """

    def __init__(
        self,
        fast_ema_period: int = 9,
        slow_ema_period: int = 21,
        atr_period: int = 14,
        rsi_period: int = 14,
    ):
        """
        Initialize indicators.

        Args:
            fast_ema_period: Period for fast EMA
            slow_ema_period: Period for slow EMA
            atr_period: Period for ATR
            rsi_period: Period for RSI
        """
        self.fast_ema_period = fast_ema_period
        self.slow_ema_period = slow_ema_period
        self.atr_period = atr_period
        self.rsi_period = rsi_period

        # State storage by symbol
        self._ema_fast: Dict[str, float] = {}
        self._ema_slow: Dict[str, float] = {}
        self._atr: Dict[str, float] = {}
        self._rsi: Dict[str, float] = {}
        self._prev_ema_fast: Dict[str, float] = {}
        self._prev_ema_slow: Dict[str, float] = {}

        # EMA multipliers
        self._fast_mult = 2.0 / (fast_ema_period + 1)
        self._slow_mult = 2.0 / (slow_ema_period + 1)
        self._atr_mult = 2.0 / (atr_period + 1)

    def update(
        self,
        symbol: str,
        close: float,
        high: Optional[float] = None,
        low: Optional[float] = None,
        prev_close: Optional[float] = None,
    ) -> IndicatorValues:
        """
        Update indicators with new bar data.

        Args:
            symbol: Symbol identifier
            close: Close price
            high: High price (for ATR)
            low: Low price (for ATR)
            prev_close: Previous close (for ATR)

        Returns:
            IndicatorValues with current readings
        """
        # Store previous EMAs for crossover detection
        self._prev_ema_fast[symbol] = self._ema_fast.get(symbol)
        self._prev_ema_slow[symbol] = self._ema_slow.get(symbol)

        # Update Fast EMA
        if symbol in self._ema_fast:
            self._ema_fast[symbol] = (close - self._ema_fast[symbol]) * self._fast_mult + self._ema_fast[symbol]
        else:
            self._ema_fast[symbol] = close

        # Update Slow EMA
        if symbol in self._ema_slow:
            self._ema_slow[symbol] = (close - self._ema_slow[symbol]) * self._slow_mult + self._ema_slow[symbol]
        else:
            self._ema_slow[symbol] = close

        # Update ATR if we have high/low/prev_close
        if high is not None and low is not None:
            true_range = self._calculate_true_range(high, low, prev_close or close)
            if symbol in self._atr:
                self._atr[symbol] = (true_range - self._atr[symbol]) * self._atr_mult + self._atr[symbol]
            else:
                self._atr[symbol] = true_range

        # Detect crossover signals
        cross_up, cross_down = self._detect_crossover(symbol)

        signal = 0
        if cross_up:
            signal = 1
        elif cross_down:
            signal = -1

        return IndicatorValues(
            symbol=symbol,
            ema_fast=self._ema_fast.get(symbol),
            ema_slow=self._ema_slow.get(symbol),
            atr=self._atr.get(symbol),
            signal=signal,
            cross_up=cross_up,
            cross_down=cross_down,
        )

    def calculate_from_bars(
        self,
        symbol: str,
        closes: List[float],
        highs: Optional[List[float]] = None,
        lows: Optional[List[float]] = None,
    ) -> IndicatorValues:
        """
        Calculate indicators from historical bar data.

        Args:
            symbol: Symbol identifier
            closes: List of close prices (oldest first)
            highs: List of high prices
            lows: List of low prices

        Returns:
            IndicatorValues with current readings
        """
        if not closes:
            return IndicatorValues(symbol=symbol)

        # Calculate EMAs
        ema_fast = self._calculate_ema(closes, self.fast_ema_period)
        ema_slow = self._calculate_ema(closes, self.slow_ema_period)

        # Store current values
        self._ema_fast[symbol] = ema_fast[-1] if ema_fast else None
        self._ema_slow[symbol] = ema_slow[-1] if ema_slow else None

        # Store previous for crossover detection
        if len(ema_fast) >= 2:
            self._prev_ema_fast[symbol] = ema_fast[-2]
        if len(ema_slow) >= 2:
            self._prev_ema_slow[symbol] = ema_slow[-2]

        # Calculate ATR if we have OHLC data
        atr_value = None
        if highs and lows and len(highs) == len(closes):
            atr_values = self._calculate_atr(highs, lows, closes, self.atr_period)
            if atr_values:
                atr_value = atr_values[-1]
                self._atr[symbol] = atr_value

        # Calculate RSI
        rsi_value = None
        if len(closes) >= self.rsi_period:
            rsi_value = self._calculate_rsi(closes, self.rsi_period)
            self._rsi[symbol] = rsi_value

        # Detect crossover
        cross_up, cross_down = self._detect_crossover(symbol)

        signal = 0
        if cross_up:
            signal = 1
        elif cross_down:
            signal = -1

        return IndicatorValues(
            symbol=symbol,
            ema_fast=self._ema_fast.get(symbol),
            ema_slow=self._ema_slow.get(symbol),
            atr=atr_value,
            rsi=rsi_value,
            signal=signal,
            cross_up=cross_up,
            cross_down=cross_down,
        )

    def _calculate_ema(self, prices: List[float], period: int) -> List[float]:
        """Calculate EMA series."""
        if len(prices) < period:
            return []

        ema = []
        multiplier = 2.0 / (period + 1)

        # Start with SMA for first value
        sma = sum(prices[:period]) / period
        ema.append(sma)

        # Calculate EMA for rest
        for i in range(period, len(prices)):
            ema_val = (prices[i] - ema[-1]) * multiplier + ema[-1]
            ema.append(ema_val)

        return ema

    def _calculate_true_range(self, high: float, low: float, prev_close: float) -> float:
        """Calculate True Range."""
        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low - prev_close)
        return max(tr1, tr2, tr3)

    def _calculate_atr(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int,
    ) -> List[float]:
        """Calculate ATR series."""
        if len(highs) < period + 1:
            return []

        # Calculate true ranges
        true_ranges = []
        for i in range(1, len(highs)):
            tr = self._calculate_true_range(highs[i], lows[i], closes[i - 1])
            true_ranges.append(tr)

        # Calculate ATR using EMA of true ranges
        if len(true_ranges) < period:
            return []

        atr = []
        multiplier = 2.0 / (period + 1)

        # Start with SMA
        sma = sum(true_ranges[:period]) / period
        atr.append(sma)

        # Calculate rest using EMA
        for i in range(period, len(true_ranges)):
            atr_val = (true_ranges[i] - atr[-1]) * multiplier + atr[-1]
            atr.append(atr_val)

        return atr

    def _calculate_rsi(self, prices: List[float], period: int) -> float:
        """Calculate RSI."""
        if len(prices) < period + 1:
            return 50.0  # Neutral

        # Calculate price changes
        changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

        # Separate gains and losses
        gains = [max(0, c) for c in changes]
        losses = [max(0, -c) for c in changes]

        # Calculate average gain/loss
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    def _detect_crossover(self, symbol: str) -> tuple[bool, bool]:
        """
        Detect EMA crossover.

        Returns:
            Tuple of (cross_up, cross_down)
        """
        ema_fast = self._ema_fast.get(symbol)
        ema_slow = self._ema_slow.get(symbol)
        prev_fast = self._prev_ema_fast.get(symbol)
        prev_slow = self._prev_ema_slow.get(symbol)

        if None in (ema_fast, ema_slow, prev_fast, prev_slow):
            return False, False

        # Cross up: fast crosses above slow
        cross_up = prev_fast <= prev_slow and ema_fast > ema_slow

        # Cross down: fast crosses below slow
        cross_down = prev_fast >= prev_slow and ema_fast < ema_slow

        return cross_up, cross_down

    def get_values(self, symbol: str) -> IndicatorValues:
        """Get current indicator values for a symbol."""
        cross_up, cross_down = self._detect_crossover(symbol)

        signal = 0
        if cross_up:
            signal = 1
        elif cross_down:
            signal = -1

        return IndicatorValues(
            symbol=symbol,
            ema_fast=self._ema_fast.get(symbol),
            ema_slow=self._ema_slow.get(symbol),
            atr=self._atr.get(symbol),
            rsi=self._rsi.get(symbol),
            signal=signal,
            cross_up=cross_up,
            cross_down=cross_down,
        )

    def calculate_stop_target(
        self,
        symbol: str,
        entry_price: float,
        is_long: bool,
        stop_atr_mult: float = 1.5,
        target_atr_mult: float = 2.0,
    ) -> tuple[Optional[float], Optional[float]]:
        """
        Calculate stop loss and take profit prices.

        Args:
            symbol: Symbol
            entry_price: Entry price
            is_long: True for long, False for short
            stop_atr_mult: ATR multiplier for stop
            target_atr_mult: ATR multiplier for target

        Returns:
            Tuple of (stop_price, target_price)
        """
        atr = self._atr.get(symbol)
        if not atr:
            return None, None

        if is_long:
            stop = entry_price - (stop_atr_mult * atr)
            target = entry_price + (target_atr_mult * atr)
        else:
            stop = entry_price + (stop_atr_mult * atr)
            target = entry_price - (target_atr_mult * atr)

        return stop, target

    def reset(self, symbol: Optional[str] = None):
        """Reset indicator state."""
        if symbol:
            self._ema_fast.pop(symbol, None)
            self._ema_slow.pop(symbol, None)
            self._atr.pop(symbol, None)
            self._rsi.pop(symbol, None)
            self._prev_ema_fast.pop(symbol, None)
            self._prev_ema_slow.pop(symbol, None)
        else:
            self._ema_fast.clear()
            self._ema_slow.clear()
            self._atr.clear()
            self._rsi.clear()
            self._prev_ema_fast.clear()
            self._prev_ema_slow.clear()
