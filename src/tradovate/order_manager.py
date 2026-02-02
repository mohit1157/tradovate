"""
Order Manager.

Handles order placement, tracking, and position management.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, Dict, List, Callable
from enum import Enum
import structlog

from .client import TradovateClient

logger = structlog.get_logger()


class OrderStatus(Enum):
    """Order status enumeration."""
    PENDING = "pending"
    WORKING = "working"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class PositionSide(Enum):
    """Position side enumeration."""
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@dataclass
class Position:
    """Current position state."""
    symbol: str
    side: PositionSide = PositionSide.FLAT
    quantity: int = 0
    avg_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Order:
    """Order record."""
    order_id: int
    symbol: str
    action: str  # "Buy" or "Sell"
    quantity: int
    order_type: str
    status: OrderStatus
    price: Optional[float] = None
    stop_price: Optional[float] = None
    fill_price: Optional[float] = None
    filled_qty: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)


class OrderManager:
    """
    Manages orders and positions.

    Features:
    - Order placement with bracket orders
    - Position tracking
    - Risk management (daily loss, trade limits)
    - Kill switch
    """

    def __init__(
        self,
        client: TradovateClient,
        max_daily_loss: float = 500.0,
        max_trades_per_day: int = 10,
        max_position_size: int = 5,
    ):
        """
        Initialize order manager.

        Args:
            client: Tradovate REST client
            max_daily_loss: Maximum daily loss before kill switch
            max_trades_per_day: Maximum trades per day
            max_position_size: Maximum position size
        """
        self.client = client
        self.max_daily_loss = max_daily_loss
        self.max_trades_per_day = max_trades_per_day
        self.max_position_size = max_position_size

        # State
        self._positions: Dict[str, Position] = {}
        self._orders: Dict[int, Order] = {}
        self._daily_pnl: float = 0.0
        self._daily_trades: int = 0
        self._current_date: Optional[date] = None
        self._is_killed: bool = False

        # Callbacks
        self._on_fill: Optional[Callable] = None
        self._on_position_change: Optional[Callable] = None

    def set_callbacks(
        self,
        on_fill: Optional[Callable] = None,
        on_position_change: Optional[Callable] = None,
    ):
        """Set callback functions."""
        self._on_fill = on_fill
        self._on_position_change = on_position_change

    async def sync_positions(self):
        """Sync positions with broker."""
        positions = await self.client.get_positions()

        for pos_data in positions:
            symbol = pos_data.get("contractId", "")
            net_pos = pos_data.get("netPos", 0)

            if net_pos > 0:
                side = PositionSide.LONG
            elif net_pos < 0:
                side = PositionSide.SHORT
            else:
                side = PositionSide.FLAT

            self._positions[symbol] = Position(
                symbol=str(symbol),
                side=side,
                quantity=abs(net_pos),
                avg_price=pos_data.get("netPrice", 0),
            )

        logger.info("Positions synced", count=len(positions))

    def _check_new_day(self):
        """Check if new trading day and reset counters."""
        today = date.today()
        if self._current_date != today:
            self._current_date = today
            self._daily_pnl = 0.0
            self._daily_trades = 0
            self._is_killed = False
            logger.info("Daily counters reset", date=today.isoformat())

    def can_trade(self) -> tuple[bool, str]:
        """
        Check if trading is allowed.

        Returns:
            Tuple of (can_trade, reason)
        """
        self._check_new_day()

        if self._is_killed:
            return False, "Kill switch active"

        if self._daily_trades >= self.max_trades_per_day:
            return False, f"Max trades reached: {self._daily_trades}"

        if self._daily_pnl <= -self.max_daily_loss:
            self._is_killed = True
            return False, f"Daily loss limit: ${abs(self._daily_pnl):.2f}"

        return True, ""

    def kill_trading(self, reason: str = "Manual kill"):
        """Activate kill switch."""
        self._is_killed = True
        logger.warning("Kill switch activated", reason=reason)

    def resume_trading(self):
        """Deactivate kill switch."""
        self._is_killed = False
        logger.info("Trading resumed")

    # ==================== Order Methods ====================

    async def place_market_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
    ) -> Optional[Order]:
        """Place a market order."""
        can_trade, reason = self.can_trade()
        if not can_trade:
            logger.warning("Cannot trade", reason=reason)
            return None

        # Check position limits
        quantity = min(quantity, self.max_position_size)

        result = await self.client.place_order(
            symbol=symbol,
            action=action,
            quantity=quantity,
            order_type="Market",
        )

        if result and "orderId" in result:
            order = Order(
                order_id=result["orderId"],
                symbol=symbol,
                action=action,
                quantity=quantity,
                order_type="Market",
                status=OrderStatus.WORKING,
            )
            self._orders[order.order_id] = order
            self._daily_trades += 1

            logger.info(
                "Market order placed",
                order_id=order.order_id,
                symbol=symbol,
                action=action,
                quantity=quantity,
            )
            return order

        return None

    async def place_bracket_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        stop_loss: float,
        take_profit: float,
    ) -> Optional[Order]:
        """
        Place a bracket order (entry + stop + target).

        Args:
            symbol: Contract symbol
            action: "Buy" or "Sell"
            quantity: Number of contracts
            stop_loss: Stop loss price
            take_profit: Take profit price

        Returns:
            Order if successful
        """
        can_trade, reason = self.can_trade()
        if not can_trade:
            logger.warning("Cannot trade", reason=reason)
            return None

        quantity = min(quantity, self.max_position_size)

        result = await self.client.place_oso_order(
            symbol=symbol,
            action=action,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

        if result and "orderId" in result:
            order = Order(
                order_id=result["orderId"],
                symbol=symbol,
                action=action,
                quantity=quantity,
                order_type="Bracket",
                status=OrderStatus.WORKING,
                stop_price=stop_loss,
                price=take_profit,
            )
            self._orders[order.order_id] = order
            self._daily_trades += 1

            logger.info(
                "Bracket order placed",
                order_id=order.order_id,
                symbol=symbol,
                action=action,
                stop=stop_loss,
                target=take_profit,
            )
            return order

        return None

    async def place_limit_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
    ) -> Optional[Order]:
        """Place a limit order."""
        can_trade, reason = self.can_trade()
        if not can_trade:
            return None

        quantity = min(quantity, self.max_position_size)

        result = await self.client.place_order(
            symbol=symbol,
            action=action,
            quantity=quantity,
            order_type="Limit",
            price=price,
        )

        if result and "orderId" in result:
            order = Order(
                order_id=result["orderId"],
                symbol=symbol,
                action=action,
                quantity=quantity,
                order_type="Limit",
                status=OrderStatus.WORKING,
                price=price,
            )
            self._orders[order.order_id] = order
            return order

        return None

    async def place_stop_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        stop_price: float,
    ) -> Optional[Order]:
        """Place a stop order."""
        can_trade, reason = self.can_trade()
        if not can_trade:
            return None

        result = await self.client.place_order(
            symbol=symbol,
            action=action,
            quantity=quantity,
            order_type="Stop",
            stop_price=stop_price,
        )

        if result and "orderId" in result:
            order = Order(
                order_id=result["orderId"],
                symbol=symbol,
                action=action,
                quantity=quantity,
                order_type="Stop",
                status=OrderStatus.WORKING,
                stop_price=stop_price,
            )
            self._orders[order.order_id] = order
            return order

        return None

    async def cancel_order(self, order_id: int) -> bool:
        """Cancel an order."""
        result = await self.client.cancel_order(order_id)

        if result:
            if order_id in self._orders:
                self._orders[order_id].status = OrderStatus.CANCELLED
            return True

        return False

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """Cancel all working orders."""
        cancelled = 0
        orders = await self.client.get_orders()

        for order in orders:
            if symbol and order.get("contractId") != symbol:
                continue

            if order.get("ordStatus") in ["Working", "Pending"]:
                result = await self.client.cancel_order(order["id"])
                if result:
                    cancelled += 1

        logger.info("Orders cancelled", count=cancelled)
        return cancelled

    async def flatten_position(self, symbol: str) -> bool:
        """Flatten/close position for a symbol."""
        result = await self.client.liquidate_position(symbol)

        if result:
            if symbol in self._positions:
                self._positions[symbol].side = PositionSide.FLAT
                self._positions[symbol].quantity = 0

            logger.info("Position flattened", symbol=symbol)
            return True

        return False

    async def flatten_all_positions(self) -> int:
        """Flatten all positions."""
        flattened = 0

        for symbol, position in self._positions.items():
            if position.side != PositionSide.FLAT:
                result = await self.flatten_position(symbol)
                if result:
                    flattened += 1

        logger.info("All positions flattened", count=flattened)
        return flattened

    # ==================== Event Handlers ====================

    def on_fill_event(self, data: Dict):
        """Handle fill event from WebSocket."""
        try:
            order_id = data.get("orderId")
            fill_price = data.get("price", 0)
            fill_qty = data.get("qty", 0)

            if order_id and order_id in self._orders:
                order = self._orders[order_id]
                order.fill_price = fill_price
                order.filled_qty += fill_qty

                if order.filled_qty >= order.quantity:
                    order.status = OrderStatus.FILLED

                logger.info(
                    "Order filled",
                    order_id=order_id,
                    price=fill_price,
                    qty=fill_qty,
                )

                if self._on_fill:
                    self._on_fill(order, fill_price, fill_qty)

        except Exception as e:
            logger.error("Fill event error", error=str(e))

    def on_position_event(self, data: Dict):
        """Handle position update from WebSocket."""
        try:
            symbol = str(data.get("contractId", ""))
            net_pos = data.get("netPos", 0)
            net_price = data.get("netPrice", 0)

            if net_pos > 0:
                side = PositionSide.LONG
            elif net_pos < 0:
                side = PositionSide.SHORT
            else:
                side = PositionSide.FLAT

            position = Position(
                symbol=symbol,
                side=side,
                quantity=abs(net_pos),
                avg_price=net_price,
            )
            self._positions[symbol] = position

            logger.info(
                "Position updated",
                symbol=symbol,
                side=side.value,
                qty=abs(net_pos),
            )

            if self._on_position_change:
                self._on_position_change(position)

        except Exception as e:
            logger.error("Position event error", error=str(e))

    def record_pnl(self, pnl: float):
        """Record P&L for daily tracking."""
        self._daily_pnl += pnl
        logger.info("P&L recorded", pnl=pnl, daily_total=self._daily_pnl)

        if self._daily_pnl <= -self.max_daily_loss:
            self.kill_trading(f"Daily loss limit: ${abs(self._daily_pnl):.2f}")

    # ==================== Getters ====================

    def get_position(self, symbol: str) -> Optional[Position]:
        """Get position for symbol."""
        return self._positions.get(symbol)

    def get_all_positions(self) -> Dict[str, Position]:
        """Get all positions."""
        return self._positions.copy()

    def get_order(self, order_id: int) -> Optional[Order]:
        """Get order by ID."""
        return self._orders.get(order_id)

    def get_working_orders(self) -> List[Order]:
        """Get all working orders."""
        return [o for o in self._orders.values() if o.status == OrderStatus.WORKING]

    def get_stats(self) -> Dict:
        """Get order manager statistics."""
        return {
            "daily_pnl": self._daily_pnl,
            "daily_trades": self._daily_trades,
            "max_daily_loss": self.max_daily_loss,
            "max_trades_per_day": self.max_trades_per_day,
            "is_killed": self._is_killed,
            "open_positions": sum(1 for p in self._positions.values() if p.side != PositionSide.FLAT),
            "working_orders": len(self.get_working_orders()),
        }
