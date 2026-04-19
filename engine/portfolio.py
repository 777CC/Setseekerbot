"""
Portfolio Manager
Tracks open positions, realized/unrealized P&L, and portfolio state.
"""

from dataclasses import dataclass, field
from datetime import datetime

from loguru import logger

from utils.helpers import calculate_commission


@dataclass
class Position:
    symbol: str
    side: str              # "LONG" or "SHORT" (SET doesn't allow short selling easily)
    entry_price: float
    quantity: int
    stop_loss: float = 0.0
    take_profit: float = 0.0
    trailing_stop: float = 0.0
    entry_time: datetime = field(default_factory=datetime.now)
    strategy: str = ""
    signal_reason: str = ""

    @property
    def market_value(self) -> float:
        return self.quantity * self.entry_price

    def unrealized_pnl(self, current_price: float) -> float:
        if self.side == "LONG":
            return (current_price - self.entry_price) * self.quantity
        return (self.entry_price - current_price) * self.quantity

    def unrealized_pnl_pct(self, current_price: float) -> float:
        if self.entry_price == 0:
            return 0.0
        if self.side == "LONG":
            return (current_price - self.entry_price) / self.entry_price * 100
        return (self.entry_price - current_price) / self.entry_price * 100


@dataclass
class ClosedTrade:
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float
    pnl_pct: float
    commission: float
    entry_time: datetime
    exit_time: datetime
    strategy: str
    reason: str


class Portfolio:
    """Manages portfolio positions and tracks P&L."""

    def __init__(self, initial_capital: float, commission_rate: float = 0.001578):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.commission_rate = commission_rate
        self.positions: dict[str, Position] = {}
        self.closed_trades: list[ClosedTrade] = []
        self.equity_history: list[tuple[datetime, float]] = []

    def open_position(
        self,
        symbol: str,
        price: float,
        quantity: int,
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
        strategy: str = "",
        reason: str = "",
    ) -> bool:
        """Open a new long position."""
        if symbol in self.positions:
            logger.warning(f"Position already exists for {symbol}")
            return False

        cost = price * quantity
        commission = calculate_commission(cost, self.commission_rate)
        total_cost = cost + commission

        if total_cost > self.cash:
            logger.warning(
                f"Insufficient cash for {symbol}: need ฿{total_cost:,.2f}, "
                f"have ฿{self.cash:,.2f}"
            )
            return False

        self.cash -= total_cost
        self.positions[symbol] = Position(
            symbol=symbol,
            side="LONG",
            entry_price=price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trailing_stop=stop_loss,
            strategy=strategy,
            signal_reason=reason,
        )

        logger.info(
            f"Opened LONG {symbol} | Qty: {quantity} @ ฿{price:.2f} | "
            f"Cost: ฿{total_cost:,.2f} | SL: ฿{stop_loss:.2f} | TP: ฿{take_profit:.2f}"
        )
        return True

    def close_position(self, symbol: str, exit_price: float, reason: str = "") -> float:
        """Close an existing position. Returns realized P&L."""
        if symbol not in self.positions:
            logger.warning(f"No position found for {symbol}")
            return 0.0

        pos = self.positions[symbol]
        proceeds = exit_price * pos.quantity
        commission = calculate_commission(proceeds, self.commission_rate)
        net_proceeds = proceeds - commission

        self.cash += net_proceeds

        # Calculate P&L
        entry_cost = pos.entry_price * pos.quantity
        entry_commission = calculate_commission(entry_cost, self.commission_rate)
        pnl = net_proceeds - entry_cost - entry_commission
        pnl_pct = (exit_price - pos.entry_price) / pos.entry_price * 100

        # Record closed trade
        trade = ClosedTrade(
            symbol=symbol,
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            quantity=pos.quantity,
            pnl=pnl,
            pnl_pct=pnl_pct,
            commission=commission + entry_commission,
            entry_time=pos.entry_time,
            exit_time=datetime.now(),
            strategy=pos.strategy,
            reason=reason,
        )
        self.closed_trades.append(trade)

        pnl_icon = "+" if pnl >= 0 else ""
        logger.info(
            f"Closed {symbol} @ ฿{exit_price:.2f} | "
            f"P&L: {pnl_icon}฿{pnl:,.2f} ({pnl_pct:+.2f}%) | {reason}"
        )

        del self.positions[symbol]
        return pnl

    def get_total_equity(self, current_prices: dict[str, float]) -> float:
        """Calculate total portfolio equity (cash + positions)."""
        positions_value = sum(
            pos.quantity * current_prices.get(sym, pos.entry_price)
            for sym, pos in self.positions.items()
        )
        return self.cash + positions_value

    def get_unrealized_pnl(self, current_prices: dict[str, float]) -> float:
        """Total unrealized P&L across all positions."""
        return sum(
            pos.unrealized_pnl(current_prices.get(sym, pos.entry_price))
            for sym, pos in self.positions.items()
        )

    def record_equity(self, current_prices: dict[str, float]):
        """Record equity snapshot for tracking."""
        equity = self.get_total_equity(current_prices)
        self.equity_history.append((datetime.now(), equity))

    def get_stats(self) -> dict:
        """Get portfolio performance statistics."""
        if not self.closed_trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "realized_pnl": 0.0,
                "avg_pnl": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "profit_factor": 0.0,
                "largest_win": 0.0,
                "largest_loss": 0.0,
                "portfolio_value": self.cash,
                "open_positions": len(self.positions),
            }

        wins = [t for t in self.closed_trades if t.pnl > 0]
        losses = [t for t in self.closed_trades if t.pnl <= 0]
        total_pnl = sum(t.pnl for t in self.closed_trades)
        gross_profit = sum(t.pnl for t in wins) if wins else 0
        gross_loss = abs(sum(t.pnl for t in losses)) if losses else 0

        return {
            "total_trades": len(self.closed_trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": len(wins) / len(self.closed_trades) * 100,
            "realized_pnl": total_pnl,
            "avg_pnl": total_pnl / len(self.closed_trades),
            "avg_win": gross_profit / len(wins) if wins else 0,
            "avg_loss": -gross_loss / len(losses) if losses else 0,
            "profit_factor": gross_profit / gross_loss if gross_loss > 0 else float("inf"),
            "largest_win": max((t.pnl for t in wins), default=0),
            "largest_loss": min((t.pnl for t in losses), default=0),
            "total_commission": sum(t.commission for t in self.closed_trades),
            "portfolio_value": self.cash,
            "open_positions": len(self.positions),
        }

    def print_positions(self, current_prices: dict[str, float]):
        """Log all open positions with current P&L."""
        if not self.positions:
            logger.info("No open positions")
            return

        logger.info("=" * 70)
        logger.info(f"{'Symbol':<10} {'Qty':>8} {'Entry':>10} {'Current':>10} {'P&L':>12} {'%':>8}")
        logger.info("-" * 70)
        for sym, pos in self.positions.items():
            current = current_prices.get(sym, pos.entry_price)
            pnl = pos.unrealized_pnl(current)
            pnl_pct = pos.unrealized_pnl_pct(current)
            logger.info(
                f"{sym:<10} {pos.quantity:>8,} {pos.entry_price:>10.2f} "
                f"{current:>10.2f} {pnl:>12,.2f} {pnl_pct:>7.2f}%"
            )
        logger.info("=" * 70)
