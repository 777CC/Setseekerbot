"""
Order Execution Engine
Handles order placement, execution simulation (paper trading),
and live order routing via Settrade Open API.
Enforces SET market rules: tick sizes, lot sizes, trading hours.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from loguru import logger

from config.settings import Settings
from utils.helpers import round_to_tick, calculate_commission, get_tick_size


class OrderStatus(Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"       # SET uses ATO/ATC for market orders
    ATO = "ATO"             # At-The-Open
    ATC = "ATC"             # At-The-Close


@dataclass
class Order:
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    price: float
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    filled_price: float = 0.0
    commission: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    filled_at: Optional[datetime] = None
    reason: str = ""

    @property
    def is_filled(self) -> bool:
        return self.status == OrderStatus.FILLED

    @property
    def net_value(self) -> float:
        value = self.filled_quantity * self.filled_price
        if self.side == OrderSide.BUY:
            return -(value + self.commission)
        return value - self.commission


class OrderExecutor:
    """Executes orders via paper trading simulation or live API."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.paper_trading = settings.paper_trading
        self._order_counter = 0
        self.order_history: list[Order] = []
        self._pending_orders: list[Order] = []

    def _generate_order_id(self) -> str:
        self._order_counter += 1
        return f"ORD-{datetime.now().strftime('%Y%m%d')}-{self._order_counter:06d}"

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        order_type: str = "LIMIT",
        reason: str = "",
    ) -> Order:
        """Place a new order."""
        # Validate lot size (SET: multiples of 100)
        if quantity % 100 != 0:
            quantity = (quantity // 100) * 100
            if quantity == 0:
                order = Order(
                    order_id=self._generate_order_id(),
                    symbol=symbol,
                    side=OrderSide(side),
                    order_type=OrderType(order_type),
                    quantity=0,
                    price=price,
                    status=OrderStatus.REJECTED,
                    reason="Quantity below minimum lot size (100)",
                )
                self.order_history.append(order)
                return order

        # Round price to valid tick
        price = round_to_tick(price)

        order = Order(
            order_id=self._generate_order_id(),
            symbol=symbol,
            side=OrderSide(side),
            order_type=OrderType(order_type),
            quantity=quantity,
            price=price,
            reason=reason,
        )

        if self.paper_trading:
            return self._execute_paper(order)
        else:
            return self._execute_live(order)

    def _execute_paper(self, order: Order) -> Order:
        """Simulate order execution for paper trading."""
        # Simulate slippage
        slippage_bps = self.settings.trading.slippage_bps
        slippage_pct = slippage_bps / 10_000

        if order.side == OrderSide.BUY:
            fill_price = order.price * (1 + slippage_pct)
        else:
            fill_price = order.price * (1 - slippage_pct)

        fill_price = round_to_tick(fill_price)

        # Calculate commission
        trade_value = order.quantity * fill_price
        commission = calculate_commission(
            trade_value, self.settings.trading.commission_rate
        )

        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.filled_price = fill_price
        order.commission = commission
        order.filled_at = datetime.now()

        self.order_history.append(order)

        logger.info(
            f"[PAPER] {order.side.value} {order.symbol} | "
            f"Qty: {order.quantity} @ ฿{fill_price:.2f} | "
            f"Value: ฿{trade_value:,.2f} | Commission: ฿{commission:.2f} | "
            f"{order.reason}"
        )

        return order

    def _execute_live(self, order: Order) -> Order:
        """Execute order via Settrade Open API."""
        try:
            import requests

            resp = requests.post(
                f"https://api.settrade.com/api/order/v1/place",
                headers={
                    "Authorization": f"Bearer {self.settings.broker.api_key}",
                },
                json={
                    "accountNo": self.settings.broker.account_id,
                    "symbol": order.symbol,
                    "side": order.side.value,
                    "type": order.order_type.value,
                    "quantity": order.quantity,
                    "price": order.price,
                },
                timeout=5,
            )

            if resp.status_code == 200:
                data = resp.json()
                order.order_id = data.get("orderId", order.order_id)
                order.status = OrderStatus.SUBMITTED
                logger.info(f"[LIVE] Order submitted: {order.order_id} {order.symbol}")
            else:
                order.status = OrderStatus.REJECTED
                order.reason = f"API error: {resp.status_code} - {resp.text}"
                logger.error(f"Order rejected: {order.reason}")

        except Exception as e:
            order.status = OrderStatus.REJECTED
            order.reason = f"Execution error: {e}"
            logger.error(f"Order execution failed: {e}")

        self.order_history.append(order)
        return order

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""
        for order in self._pending_orders:
            if order.order_id == order_id:
                order.status = OrderStatus.CANCELLED
                self._pending_orders.remove(order)
                logger.info(f"Order cancelled: {order_id}")
                return True
        return False

    def get_filled_orders(self, symbol: str | None = None) -> list[Order]:
        """Get all filled orders, optionally filtered by symbol."""
        orders = [o for o in self.order_history if o.is_filled]
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return orders

    def get_daily_summary(self) -> dict:
        """Get summary of today's orders."""
        today = datetime.now().date()
        today_orders = [
            o for o in self.order_history
            if o.created_at.date() == today and o.is_filled
        ]

        total_buy = sum(
            o.filled_quantity * o.filled_price
            for o in today_orders if o.side == OrderSide.BUY
        )
        total_sell = sum(
            o.filled_quantity * o.filled_price
            for o in today_orders if o.side == OrderSide.SELL
        )
        total_commission = sum(o.commission for o in today_orders)

        return {
            "total_orders": len(today_orders),
            "buy_value": total_buy,
            "sell_value": total_sell,
            "total_commission": total_commission,
            "net_value": total_sell - total_buy - total_commission,
        }
