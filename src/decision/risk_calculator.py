"""Risk calculation and position sizing."""

from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional
import structlog

logger = structlog.get_logger()


@dataclass
class RiskParameters:
    """Risk parameters for a trade."""
    position_size: int
    max_loss_per_trade: float
    stop_distance: float
    target_distance: float
    risk_reward_ratio: float
    can_trade: bool
    reason: str = ""


class RiskCalculator:
    """
    Calculate position sizing and risk parameters.

    Tracks daily P&L and enforces risk limits.
    """

    def __init__(
        self,
        max_daily_loss: float = 500.0,
        max_trades_per_day: int = 10,
        max_position_size: int = 5,
        risk_per_trade_pct: float = 1.0,  # Percentage of account
        account_size: float = 10000.0,
    ):
        self.max_daily_loss = max_daily_loss
        self.max_trades_per_day = max_trades_per_day
        self.max_position_size = max_position_size
        self.risk_per_trade_pct = risk_per_trade_pct
        self.account_size = account_size

        # Daily tracking
        self._current_date: Optional[date] = None
        self._daily_pnl: float = 0.0
        self._daily_trades: int = 0
        self._is_killed: bool = False

    def calculate(
        self,
        symbol: str,
        confidence: float,
        volatility: Optional[float] = None,
        current_price: Optional[float] = None,
    ) -> RiskParameters:
        """
        Calculate risk parameters for a potential trade.

        Args:
            symbol: Trading symbol
            confidence: Signal confidence (0-1)
            volatility: Optional current volatility (ATR)
            current_price: Optional current price

        Returns:
            RiskParameters with sizing and limits
        """
        # Check if trading is allowed
        can_trade, reason = self._check_trading_allowed()
        if not can_trade:
            return RiskParameters(
                position_size=0,
                max_loss_per_trade=0,
                stop_distance=0,
                target_distance=0,
                risk_reward_ratio=0,
                can_trade=False,
                reason=reason,
            )

        # Calculate position size based on confidence
        base_size = self._calculate_base_size(confidence)

        # Adjust for volatility if available
        if volatility and current_price:
            vol_adjusted_size = self._adjust_for_volatility(
                base_size, volatility, current_price
            )
        else:
            vol_adjusted_size = base_size

        # Calculate max loss per trade
        max_loss = (self.account_size * self.risk_per_trade_pct / 100) * confidence

        # Default stop/target distances (ATR multiples typically)
        # These will be overridden by the strategy if it has better data
        default_stop_mult = 1.5
        default_target_mult = 2.0

        if volatility:
            stop_distance = volatility * default_stop_mult
            target_distance = volatility * default_target_mult
        else:
            # Fallback percentages
            stop_distance = (current_price or 100) * 0.005  # 0.5%
            target_distance = (current_price or 100) * 0.01  # 1%

        risk_reward = target_distance / stop_distance if stop_distance > 0 else 0

        return RiskParameters(
            position_size=vol_adjusted_size,
            max_loss_per_trade=max_loss,
            stop_distance=stop_distance,
            target_distance=target_distance,
            risk_reward_ratio=risk_reward,
            can_trade=True,
        )

    def _check_trading_allowed(self) -> tuple[bool, str]:
        """Check if trading is currently allowed."""
        # Reset daily counters if new day
        today = date.today()
        if self._current_date != today:
            self._current_date = today
            self._daily_pnl = 0.0
            self._daily_trades = 0
            logger.info("Daily counters reset", date=today.isoformat())

        # Check kill switch
        if self._is_killed:
            return False, "Kill switch activated - trading disabled"

        # Check daily loss limit
        if self._daily_pnl <= -self.max_daily_loss:
            return False, f"Daily loss limit reached: ${abs(self._daily_pnl):.2f}"

        # Check trade count
        if self._daily_trades >= self.max_trades_per_day:
            return False, f"Max daily trades reached: {self._daily_trades}"

        return True, ""

    def _calculate_base_size(self, confidence: float) -> int:
        """Calculate base position size from confidence."""
        # Scale position size with confidence
        # Low confidence (0.55-0.65) = 1 contract
        # Medium confidence (0.65-0.80) = 2-3 contracts
        # High confidence (0.80-1.0) = 3-5 contracts

        if confidence < 0.55:
            return 0
        elif confidence < 0.65:
            return 1
        elif confidence < 0.75:
            return 2
        elif confidence < 0.85:
            return 3
        elif confidence < 0.95:
            return 4
        else:
            return min(5, self.max_position_size)

    def _adjust_for_volatility(
        self, base_size: int, volatility: float, price: float
    ) -> int:
        """Adjust position size for current volatility."""
        # Higher volatility = smaller position
        vol_pct = volatility / price

        if vol_pct > 0.02:  # Very high volatility (>2%)
            return max(1, base_size // 2)
        elif vol_pct > 0.01:  # High volatility (>1%)
            return max(1, int(base_size * 0.75))
        else:
            return base_size

    def record_trade(self, pnl: float):
        """Record a completed trade."""
        self._daily_trades += 1
        self._daily_pnl += pnl

        logger.info(
            "Trade recorded",
            pnl=pnl,
            daily_pnl=self._daily_pnl,
            daily_trades=self._daily_trades,
        )

        # Check if we need to kill trading
        if self._daily_pnl <= -self.max_daily_loss:
            logger.warning(
                "Daily loss limit breached - activating kill switch",
                daily_pnl=self._daily_pnl,
            )
            self._is_killed = True

    def kill_trading(self, reason: str = "Manual kill switch"):
        """Activate kill switch to stop all trading."""
        self._is_killed = True
        logger.warning("Kill switch activated", reason=reason)

    def resume_trading(self):
        """Deactivate kill switch."""
        self._is_killed = False
        logger.info("Trading resumed - kill switch deactivated")

    def get_stats(self) -> dict:
        """Get current risk statistics."""
        return {
            "date": self._current_date.isoformat() if self._current_date else None,
            "daily_pnl": self._daily_pnl,
            "daily_trades": self._daily_trades,
            "max_daily_loss": self.max_daily_loss,
            "max_trades_per_day": self.max_trades_per_day,
            "is_killed": self._is_killed,
            "remaining_loss_budget": self.max_daily_loss + self._daily_pnl,
            "remaining_trades": self.max_trades_per_day - self._daily_trades,
        }
