"""
Tradovate REST API Client.

Handles authentication and REST API calls for account management,
order placement, and market data requests.
"""

import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import structlog

logger = structlog.get_logger()


class TradovateClient:
    """
    Tradovate REST API client.

    Supports both demo and live environments.
    """

    # API Endpoints
    DEMO_URL = "https://demo.tradovateapi.com/v1"
    LIVE_URL = "https://live.tradovateapi.com/v1"

    # Market Data URLs
    DEMO_MD_URL = "https://md-demo.tradovateapi.com/v1"
    LIVE_MD_URL = "https://md-live.tradovateapi.com/v1"

    # WebSocket URLs
    DEMO_WS_URL = "wss://demo.tradovateapi.com/v1/websocket"
    LIVE_WS_URL = "wss://live.tradovateapi.com/v1/websocket"

    DEMO_MD_WS_URL = "wss://md-demo.tradovateapi.com/v1/websocket"
    LIVE_MD_WS_URL = "wss://md-live.tradovateapi.com/v1/websocket"

    def __init__(
        self,
        username: str,
        password: str,
        app_id: Optional[str] = None,
        app_version: Optional[str] = "1.0",
        cid: Optional[int] = None,
        secret: Optional[str] = None,
        demo: bool = True,
    ):
        """
        Initialize Tradovate client.

        Args:
            username: Tradovate username
            password: Tradovate password
            app_id: Application ID (optional, for OAuth)
            app_version: Application version
            cid: Client ID (for API key auth)
            secret: API secret (for API key auth)
            demo: Use demo environment (default True)
        """
        self.username = username
        self.password = password
        self.app_id = app_id
        self.app_version = app_version
        self.cid = cid
        self.secret = secret
        self.demo = demo

        # Set URLs based on environment
        self.base_url = self.DEMO_URL if demo else self.LIVE_URL
        self.md_url = self.DEMO_MD_URL if demo else self.LIVE_MD_URL
        self.ws_url = self.DEMO_WS_URL if demo else self.LIVE_WS_URL
        self.md_ws_url = self.DEMO_MD_WS_URL if demo else self.LIVE_MD_WS_URL

        # Session state
        self._session: Optional[aiohttp.ClientSession] = None
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
        self._user_id: Optional[int] = None
        self._accounts: List[Dict] = []
        self._current_account_id: Optional[int] = None

    async def connect(self) -> bool:
        """
        Connect to Tradovate and authenticate.

        Returns:
            True if connection successful
        """
        try:
            self._session = aiohttp.ClientSession()

            # Authenticate
            auth_result = await self._authenticate()

            if auth_result:
                # Get accounts
                await self._load_accounts()
                logger.info(
                    "Tradovate client connected",
                    demo=self.demo,
                    user_id=self._user_id,
                    accounts=len(self._accounts),
                )
                return True

            return False

        except Exception as e:
            logger.error("Failed to connect to Tradovate", error=str(e))
            return False

    async def disconnect(self):
        """Disconnect and cleanup."""
        if self._session:
            await self._session.close()
            self._session = None
        self._access_token = None
        logger.info("Tradovate client disconnected")

    async def _authenticate(self) -> bool:
        """Authenticate with Tradovate."""
        auth_data = {
            "name": self.username,
            "password": self.password,
            "appId": self.app_id or "TradovateBot",
            "appVersion": self.app_version,
            "deviceId": "python-bot",
        }

        # Add API key credentials if provided
        if self.cid and self.secret:
            auth_data["cid"] = self.cid
            auth_data["sec"] = self.secret

        try:
            async with self._session.post(
                f"{self.base_url}/auth/accesstokenrequest",
                json=auth_data,
            ) as response:
                if response.status == 200:
                    data = await response.json()

                    if "accessToken" in data:
                        self._access_token = data["accessToken"]
                        self._user_id = data.get("userId")

                        # Token expires in 24 hours typically
                        expiry_str = data.get("expirationTime")
                        if expiry_str:
                            self._token_expiry = datetime.fromisoformat(
                                expiry_str.replace("Z", "+00:00")
                            )
                        else:
                            self._token_expiry = datetime.utcnow() + timedelta(hours=24)

                        logger.info("Authentication successful", user_id=self._user_id)
                        return True
                    else:
                        error = data.get("errorText", "Unknown error")
                        logger.error("Authentication failed", error=error)
                        return False
                else:
                    text = await response.text()
                    logger.error("Authentication request failed", status=response.status, body=text)
                    return False

        except Exception as e:
            logger.error("Authentication error", error=str(e))
            return False

    async def _ensure_authenticated(self):
        """Ensure we have a valid token."""
        if not self._access_token:
            raise Exception("Not authenticated")

        # Check if token is about to expire (within 1 hour)
        if self._token_expiry and datetime.utcnow() > self._token_expiry - timedelta(hours=1):
            logger.info("Token expiring soon, re-authenticating")
            await self._authenticate()

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with auth token."""
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        use_md_url: bool = False,
    ) -> Optional[Dict]:
        """Make an authenticated API request."""
        await self._ensure_authenticated()

        base = self.md_url if use_md_url else self.base_url
        url = f"{base}/{endpoint}"

        try:
            async with self._session.request(
                method,
                url,
                json=data,
                params=params,
                headers=self._get_headers(),
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    text = await response.text()
                    logger.error(
                        "API request failed",
                        endpoint=endpoint,
                        status=response.status,
                        body=text,
                    )
                    return None

        except Exception as e:
            logger.error("API request error", endpoint=endpoint, error=str(e))
            return None

    async def _load_accounts(self):
        """Load user's trading accounts."""
        accounts = await self._request("GET", "account/list")
        if accounts:
            self._accounts = accounts
            # Set first account as default
            if accounts:
                self._current_account_id = accounts[0]["id"]
                logger.info(
                    "Loaded accounts",
                    count=len(accounts),
                    default_account=self._current_account_id,
                )

    @property
    def access_token(self) -> Optional[str]:
        """Get current access token."""
        return self._access_token

    @property
    def account_id(self) -> Optional[int]:
        """Get current account ID."""
        return self._current_account_id

    @property
    def accounts(self) -> List[Dict]:
        """Get all accounts."""
        return self._accounts

    def set_account(self, account_id: int):
        """Set the active trading account."""
        if any(a["id"] == account_id for a in self._accounts):
            self._current_account_id = account_id
            logger.info("Active account changed", account_id=account_id)
        else:
            raise ValueError(f"Account {account_id} not found")

    # ==================== Account Methods ====================

    async def get_account_balance(self, account_id: Optional[int] = None) -> Optional[Dict]:
        """Get account cash balance."""
        aid = account_id or self._current_account_id
        return await self._request("GET", f"cashBalance/getCashBalanceSnapshot", params={"accountId": aid})

    async def get_positions(self, account_id: Optional[int] = None) -> List[Dict]:
        """Get open positions."""
        aid = account_id or self._current_account_id
        result = await self._request("GET", "position/list", params={"accountId": aid})
        return result or []

    async def get_orders(self, account_id: Optional[int] = None) -> List[Dict]:
        """Get open orders."""
        aid = account_id or self._current_account_id
        result = await self._request("GET", "order/list", params={"accountId": aid})
        return result or []

    # ==================== Contract Methods ====================

    async def get_contract(self, symbol: str) -> Optional[Dict]:
        """Get contract details by symbol name."""
        result = await self._request("GET", "contract/find", params={"name": symbol})
        return result

    async def get_contract_by_id(self, contract_id: int) -> Optional[Dict]:
        """Get contract details by ID."""
        result = await self._request("GET", f"contract/item", params={"id": contract_id})
        return result

    async def search_contracts(self, query: str) -> List[Dict]:
        """Search for contracts."""
        result = await self._request("GET", "contract/suggest", params={"text": query, "nEntities": 10})
        return result or []

    # ==================== Order Methods ====================

    async def place_order(
        self,
        symbol: str,
        action: str,  # "Buy" or "Sell"
        quantity: int,
        order_type: str = "Market",  # "Market", "Limit", "Stop", "StopLimit"
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        account_id: Optional[int] = None,
    ) -> Optional[Dict]:
        """
        Place an order.

        Args:
            symbol: Contract symbol (e.g., "MNQH5" or "MESZ4")
            action: "Buy" or "Sell"
            quantity: Number of contracts
            order_type: Order type
            price: Limit price (for Limit/StopLimit orders)
            stop_price: Stop price (for Stop/StopLimit orders)
            account_id: Account ID (uses default if not specified)

        Returns:
            Order result or None if failed
        """
        aid = account_id or self._current_account_id

        # Get contract ID
        contract = await self.get_contract(symbol)
        if not contract:
            logger.error("Contract not found", symbol=symbol)
            return None

        order_data = {
            "accountSpec": self.username,
            "accountId": aid,
            "action": action,
            "symbol": symbol,
            "orderQty": quantity,
            "orderType": order_type,
            "isAutomated": True,
        }

        if price is not None:
            order_data["price"] = price
        if stop_price is not None:
            order_data["stopPrice"] = stop_price

        result = await self._request("POST", "order/placeorder", data=order_data)

        if result:
            logger.info(
                "Order placed",
                symbol=symbol,
                action=action,
                quantity=quantity,
                order_type=order_type,
                order_id=result.get("orderId"),
            )

        return result

    async def place_oso_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        stop_loss: float,
        take_profit: float,
        account_id: Optional[int] = None,
    ) -> Optional[Dict]:
        """
        Place order with bracket (OSO - Order Sends Order).

        Args:
            symbol: Contract symbol
            action: "Buy" or "Sell"
            quantity: Number of contracts
            stop_loss: Stop loss price
            take_profit: Take profit price
            account_id: Account ID

        Returns:
            Order result
        """
        aid = account_id or self._current_account_id

        # Determine bracket actions
        if action == "Buy":
            sl_action = "Sell"
            tp_action = "Sell"
        else:
            sl_action = "Buy"
            tp_action = "Buy"

        order_data = {
            "accountSpec": self.username,
            "accountId": aid,
            "action": action,
            "symbol": symbol,
            "orderQty": quantity,
            "orderType": "Market",
            "isAutomated": True,
            "bracket1": {
                "action": sl_action,
                "orderType": "Stop",
                "stopPrice": stop_loss,
            },
            "bracket2": {
                "action": tp_action,
                "orderType": "Limit",
                "price": take_profit,
            },
        }

        result = await self._request("POST", "order/placeoso", data=order_data)

        if result:
            logger.info(
                "OSO order placed",
                symbol=symbol,
                action=action,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )

        return result

    async def cancel_order(self, order_id: int) -> Optional[Dict]:
        """Cancel an order."""
        result = await self._request("POST", "order/cancelorder", data={"orderId": order_id})
        if result:
            logger.info("Order cancelled", order_id=order_id)
        return result

    async def modify_order(
        self,
        order_id: int,
        quantity: Optional[int] = None,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> Optional[Dict]:
        """Modify an existing order."""
        mod_data = {"orderId": order_id}
        if quantity is not None:
            mod_data["orderQty"] = quantity
        if price is not None:
            mod_data["price"] = price
        if stop_price is not None:
            mod_data["stopPrice"] = stop_price

        return await self._request("POST", "order/modifyorder", data=mod_data)

    async def liquidate_position(
        self,
        symbol: str,
        account_id: Optional[int] = None,
    ) -> Optional[Dict]:
        """Liquidate/flatten a position."""
        aid = account_id or self._current_account_id

        contract = await self.get_contract(symbol)
        if not contract:
            return None

        return await self._request(
            "POST",
            "order/liquidateposition",
            data={
                "accountId": aid,
                "contractId": contract["id"],
            }
        )

    # ==================== Market Data Methods ====================

    async def get_quote(self, symbol: str) -> Optional[Dict]:
        """Get current quote for a symbol."""
        contract = await self.get_contract(symbol)
        if not contract:
            return None

        return await self._request(
            "GET",
            f"md/getQuote",
            params={"symbol": symbol},
            use_md_url=True,
        )

    async def get_dom(self, symbol: str) -> Optional[Dict]:
        """Get depth of market."""
        return await self._request(
            "GET",
            f"md/getDOM",
            params={"symbol": symbol},
            use_md_url=True,
        )

    async def get_chart_data(
        self,
        symbol: str,
        chart_type: str = "MinuteBar",  # "Tick", "MinuteBar", "DailyBar"
        interval: int = 1,  # For MinuteBar: 1, 5, 15, 30, 60, etc.
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Optional[Dict]:
        """
        Get historical chart data.

        Args:
            symbol: Contract symbol
            chart_type: "Tick", "MinuteBar", or "DailyBar"
            interval: Bar interval (minutes for MinuteBar)
            start_time: Start of range
            end_time: End of range
        """
        contract = await self.get_contract(symbol)
        if not contract:
            return None

        params = {
            "symbol": symbol,
            "chartType": chart_type,
        }

        if chart_type == "MinuteBar":
            params["interval"] = interval

        if start_time:
            params["startTimestamp"] = start_time.isoformat()
        if end_time:
            params["endTimestamp"] = end_time.isoformat()

        return await self._request("GET", "md/getChart", params=params, use_md_url=True)
