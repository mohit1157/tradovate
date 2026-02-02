"""
Tradovate WebSocket Client.

Handles real-time market data streaming and order updates.
"""

import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, Any, Callable, List, Set
import websockets
from websockets.client import WebSocketClientProtocol
import structlog

logger = structlog.get_logger()


class TradovateWebSocket:
    """
    WebSocket client for Tradovate real-time data.

    Supports:
    - Real-time quotes
    - Live DOM (depth of market)
    - Tick data
    - Chart/candle updates
    - Order and position updates
    """

    def __init__(
        self,
        access_token: str,
        ws_url: str,
        md_ws_url: str,
    ):
        """
        Initialize WebSocket client.

        Args:
            access_token: Valid Tradovate access token
            ws_url: Trading WebSocket URL
            md_ws_url: Market data WebSocket URL
        """
        self.access_token = access_token
        self.ws_url = ws_url
        self.md_ws_url = md_ws_url

        # Connections
        self._trading_ws: Optional[WebSocketClientProtocol] = None
        self._market_ws: Optional[WebSocketClientProtocol] = None

        # Subscriptions
        self._quote_subscriptions: Set[str] = set()
        self._dom_subscriptions: Set[str] = set()
        self._chart_subscriptions: Dict[str, Dict] = {}

        # Callbacks
        self._on_quote: Optional[Callable] = None
        self._on_dom: Optional[Callable] = None
        self._on_chart: Optional[Callable] = None
        self._on_tick: Optional[Callable] = None
        self._on_order: Optional[Callable] = None
        self._on_position: Optional[Callable] = None
        self._on_fill: Optional[Callable] = None

        # State
        self._running = False
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}

    def set_callbacks(
        self,
        on_quote: Optional[Callable] = None,
        on_dom: Optional[Callable] = None,
        on_chart: Optional[Callable] = None,
        on_tick: Optional[Callable] = None,
        on_order: Optional[Callable] = None,
        on_position: Optional[Callable] = None,
        on_fill: Optional[Callable] = None,
    ):
        """Set callback functions for different event types."""
        self._on_quote = on_quote
        self._on_dom = on_dom
        self._on_chart = on_chart
        self._on_tick = on_tick
        self._on_order = on_order
        self._on_position = on_position
        self._on_fill = on_fill

    async def connect(self) -> bool:
        """Connect to WebSocket servers."""
        try:
            self._running = True

            # Connect to market data WebSocket
            self._market_ws = await websockets.connect(self.md_ws_url)
            await self._authorize(self._market_ws)
            logger.info("Market data WebSocket connected")

            # Connect to trading WebSocket
            self._trading_ws = await websockets.connect(self.ws_url)
            await self._authorize(self._trading_ws)
            logger.info("Trading WebSocket connected")

            # Start message handlers
            asyncio.create_task(self._handle_market_messages())
            asyncio.create_task(self._handle_trading_messages())

            return True

        except Exception as e:
            logger.error("WebSocket connection failed", error=str(e))
            return False

    async def disconnect(self):
        """Disconnect from WebSocket servers."""
        self._running = False

        if self._market_ws:
            await self._market_ws.close()
            self._market_ws = None

        if self._trading_ws:
            await self._trading_ws.close()
            self._trading_ws = None

        logger.info("WebSocket disconnected")

    async def _authorize(self, ws: WebSocketClientProtocol):
        """Authorize WebSocket connection."""
        auth_message = f"authorize\n0\n\n{self.access_token}"
        await ws.send(auth_message)

        # Wait for auth response
        response = await ws.recv()
        logger.debug("WebSocket auth response", response=response[:100])

    def _next_request_id(self) -> int:
        """Get next request ID."""
        self._request_id += 1
        return self._request_id

    async def _send_request(
        self,
        ws: WebSocketClientProtocol,
        endpoint: str,
        body: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """Send a request and wait for response."""
        req_id = self._next_request_id()

        # Format: endpoint\nid\n\nbody_json
        body_str = json.dumps(body) if body else ""
        message = f"{endpoint}\n{req_id}\n\n{body_str}"

        # Create future for response
        future = asyncio.Future()
        self._pending_requests[req_id] = future

        await ws.send(message)

        try:
            result = await asyncio.wait_for(future, timeout=10.0)
            return result
        except asyncio.TimeoutError:
            logger.warning("Request timeout", endpoint=endpoint, req_id=req_id)
            return None
        finally:
            self._pending_requests.pop(req_id, None)

    async def _handle_market_messages(self):
        """Handle incoming market data messages."""
        while self._running and self._market_ws:
            try:
                message = await self._market_ws.recv()
                await self._process_message(message, is_market_data=True)
            except websockets.ConnectionClosed:
                logger.warning("Market data WebSocket closed")
                break
            except Exception as e:
                logger.error("Market message error", error=str(e))

    async def _handle_trading_messages(self):
        """Handle incoming trading messages."""
        while self._running and self._trading_ws:
            try:
                message = await self._trading_ws.recv()
                await self._process_message(message, is_market_data=False)
            except websockets.ConnectionClosed:
                logger.warning("Trading WebSocket closed")
                break
            except Exception as e:
                logger.error("Trading message error", error=str(e))

    async def _process_message(self, message: str, is_market_data: bool):
        """Process incoming WebSocket message."""
        try:
            # Tradovate message format: type\nid\n\ndata
            parts = message.split("\n", 3)

            if len(parts) < 1:
                return

            msg_type = parts[0]

            # Handle heartbeat
            if msg_type == "h" or message.strip() == "":
                return

            # Parse response ID if present
            req_id = None
            if len(parts) >= 2 and parts[1].isdigit():
                req_id = int(parts[1])

            # Parse JSON data
            data = None
            if len(parts) >= 4 and parts[3]:
                try:
                    data = json.loads(parts[3])
                except json.JSONDecodeError:
                    data = parts[3]

            # Handle pending request response
            if req_id and req_id in self._pending_requests:
                self._pending_requests[req_id].set_result(data)
                return

            # Handle different message types
            if is_market_data:
                await self._handle_market_event(msg_type, data)
            else:
                await self._handle_trading_event(msg_type, data)

        except Exception as e:
            logger.error("Message processing error", error=str(e), message=message[:100])

    async def _handle_market_event(self, msg_type: str, data: Any):
        """Handle market data events."""
        if not data:
            return

        if msg_type == "md/subscribeQuote" or "quotes" in str(data):
            if self._on_quote and isinstance(data, dict):
                await self._safe_callback(self._on_quote, data)

        elif msg_type == "md/subscribeDOM" or "dom" in str(data):
            if self._on_dom and isinstance(data, dict):
                await self._safe_callback(self._on_dom, data)

        elif msg_type == "md/getChart" or "bars" in str(data):
            if self._on_chart and isinstance(data, dict):
                await self._safe_callback(self._on_chart, data)

        # Handle real-time data pushes (format varies)
        if isinstance(data, dict):
            if "entries" in data:  # Quote update
                for entry in data.get("entries", []):
                    if self._on_quote:
                        await self._safe_callback(self._on_quote, entry)
            elif "bids" in data or "asks" in data:  # DOM update
                if self._on_dom:
                    await self._safe_callback(self._on_dom, data)

    async def _handle_trading_event(self, msg_type: str, data: Any):
        """Handle trading events (orders, positions, fills)."""
        if not data:
            return

        if isinstance(data, dict):
            entity_type = data.get("entityType", "")

            if entity_type == "order" or "order" in msg_type.lower():
                if self._on_order:
                    await self._safe_callback(self._on_order, data)

            elif entity_type == "position" or "position" in msg_type.lower():
                if self._on_position:
                    await self._safe_callback(self._on_position, data)

            elif entity_type == "fill" or "fill" in msg_type.lower():
                if self._on_fill:
                    await self._safe_callback(self._on_fill, data)

    async def _safe_callback(self, callback: Callable, data: Any):
        """Safely execute callback."""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(data)
            else:
                callback(data)
        except Exception as e:
            logger.error("Callback error", error=str(e))

    # ==================== Subscription Methods ====================

    async def subscribe_quote(self, symbol: str):
        """Subscribe to real-time quotes for a symbol."""
        if not self._market_ws:
            return

        self._quote_subscriptions.add(symbol)

        await self._send_request(
            self._market_ws,
            "md/subscribeQuote",
            {"symbol": symbol},
        )
        logger.info("Subscribed to quote", symbol=symbol)

    async def unsubscribe_quote(self, symbol: str):
        """Unsubscribe from quotes."""
        if not self._market_ws:
            return

        self._quote_subscriptions.discard(symbol)

        await self._send_request(
            self._market_ws,
            "md/unsubscribeQuote",
            {"symbol": symbol},
        )

    async def subscribe_dom(self, symbol: str):
        """Subscribe to depth of market."""
        if not self._market_ws:
            return

        self._dom_subscriptions.add(symbol)

        await self._send_request(
            self._market_ws,
            "md/subscribeDOM",
            {"symbol": symbol},
        )
        logger.info("Subscribed to DOM", symbol=symbol)

    async def subscribe_chart(
        self,
        symbol: str,
        chart_type: str = "MinuteBar",
        interval: int = 1,
    ):
        """
        Subscribe to chart/candle updates.

        Args:
            symbol: Contract symbol
            chart_type: "Tick", "MinuteBar", or "DailyBar"
            interval: Bar interval
        """
        if not self._market_ws:
            return

        subscription_key = f"{symbol}_{chart_type}_{interval}"
        self._chart_subscriptions[subscription_key] = {
            "symbol": symbol,
            "chartType": chart_type,
            "interval": interval,
        }

        body = {
            "symbol": symbol,
            "chartDescription": {
                "underlyingType": "MinuteBar" if chart_type == "MinuteBar" else chart_type,
                "elementSize": interval,
                "elementSizeUnit": "UnderlyingUnits",
            },
        }

        await self._send_request(
            self._market_ws,
            "md/getChart",
            body,
        )
        logger.info("Subscribed to chart", symbol=symbol, interval=interval)

    async def subscribe_user_updates(self):
        """Subscribe to order, position, and fill updates."""
        if not self._trading_ws:
            return

        # Subscribe to user sync for real-time updates
        await self._send_request(
            self._trading_ws,
            "user/syncrequest",
            {"users": []},
        )
        logger.info("Subscribed to user updates")

    # ==================== Utility Methods ====================

    async def send_heartbeat(self):
        """Send heartbeat to keep connection alive."""
        if self._market_ws:
            await self._market_ws.send("")
        if self._trading_ws:
            await self._trading_ws.send("")

    async def start_heartbeat(self, interval: int = 25):
        """Start heartbeat task."""
        while self._running:
            await asyncio.sleep(interval)
            await self.send_heartbeat()
