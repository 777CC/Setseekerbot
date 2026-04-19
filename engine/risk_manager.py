"""
Risk Management Engine
Handles position sizing (Kelly, fixed, volatility-based), stop-loss management,
daily drawdown limits, and exposure controls for SET day trading.
"""

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from loguru import logger

from config.settings import RiskConfig, TradingConfig
from data.indicators import TechnicalIndicators as TI
from utils.helpers import get_tick_size, round_to_tick, calculate_commission


@dataclass
class PositionSizeResult:
    shares: int
    value: float
    risk_per_share: float
    total_risk: float
    method: str
    reason: str = ""


class RiskManager:
    """Central risk management for all trading decisions."""

    def __init__(self, risk_config: RiskConfig, trading_config: TradingConfig):
        self.config = risk_config
        self.trading = trading_config
        self.daily_pnl: float = 0.0
        self.daily_trades: int = 0
        self.peak_equity: float = trading_config.initial_capital
        self.current_equity: float = trading_config.initial_capital

    def calculate_position_size(
        self,
        price: float,
        stop_loss: float,
        signal_strength: float,
        df: pd.DataFrame | None = None,
    ) -> PositionSizeResult:
        """Calculate optimal position size based on configured method."""
        method = self.config.position_size_method

        if method == "kelly":
            return self._kelly_sizing(price, stop_loss, signal_strength)
        elif method == "volatility":
            return self._volatility_sizing(price, df)
        else:
            return self._fixed_sizing(price, stop_loss)

    def _kelly_sizing(
        self, price: float, stop_loss: float, signal_strength: float
    ) -> PositionSizeResult:
        """
        Kelly Criterion position sizing.
        Uses half-Kelly for safety (less aggressive).
        """
        risk_per_share = abs(price - stop_loss)
        if risk_per_share == 0:
            risk_per_share = price * self.config.stop_loss_pct

        # Estimate win probability from signal strength
        win_prob = 0.45 + signal_strength * 0.2  # 45%-65% range
        avg_win = price * self.config.take_profit_pct
        avg_loss = risk_per_share

        if avg_loss == 0:
            return PositionSizeResult(0, 0, 0, 0, "kelly", "Zero risk")

        # Kelly fraction: f* = (bp - q) / b
        b = avg_win / avg_loss  # Win/loss ratio
        q = 1 - win_prob
        kelly_fraction = (b * win_prob - q) / b

        # Half-Kelly for safety
        kelly_fraction = max(0, kelly_fraction * 0.5)

        # Cap at max position size
        max_value = self.current_equity * self.config.max_position_pct
        kelly_value = self.current_equity * kelly_fraction
        position_value = min(kelly_value, max_value)

        shares = int(position_value / price)
        # SET stocks trade in lots of 100
        shares = (shares // 100) * 100

        if shares <= 0:
            return PositionSizeResult(0, 0, risk_per_share, 0, "kelly", "Size too small")

        actual_value = shares * price
        total_risk = shares * risk_per_share

        return PositionSizeResult(
            shares=shares,
            value=actual_value,
            risk_per_share=risk_per_share,
            total_risk=total_risk,
            method="kelly",
            reason=f"Kelly={kelly_fraction:.3f}, WinProb={win_prob:.2f}",
        )

    def _fixed_sizing(self, price: float, stop_loss: float) -> PositionSizeResult:
        """Fixed fractional position sizing (risk 1% of equity per trade)."""
        risk_per_share = abs(price - stop_loss)
        if risk_per_share == 0:
            risk_per_share = price * self.config.stop_loss_pct

        risk_budget = self.current_equity * 0.01  # Risk 1% per trade
        shares = int(risk_budget / risk_per_share)
        shares = (shares // 100) * 100

        # Cap at max position
        max_shares = int(self.current_equity * self.config.max_position_pct / price)
        max_shares = (max_shares // 100) * 100
        shares = min(shares, max_shares)

        if shares <= 0:
            return PositionSizeResult(0, 0, risk_per_share, 0, "fixed", "Size too small")

        return PositionSizeResult(
            shares=shares,
            value=shares * price,
            risk_per_share=risk_per_share,
            total_risk=shares * risk_per_share,
            method="fixed",
        )

    def _volatility_sizing(
        self, price: float, df: pd.DataFrame | None
    ) -> PositionSizeResult:
        """Volatility-based sizing using ATR."""
        if df is None or len(df) < 20:
            return self._fixed_sizing(price, price * (1 - self.config.stop_loss_pct))

        atr = float(TI.atr(df).iloc[-1])
        risk_per_share = 2 * atr  # 2x ATR stop

        risk_budget = self.current_equity * 0.01
        shares = int(risk_budget / risk_per_share)
        shares = (shares // 100) * 100

        max_shares = int(self.current_equity * self.config.max_position_pct / price)
        max_shares = (max_shares // 100) * 100
        shares = min(shares, max_shares)

        if shares <= 0:
            return PositionSizeResult(0, 0, risk_per_share, 0, "volatility", "Size too small")

        return PositionSizeResult(
            shares=shares,
            value=shares * price,
            risk_per_share=risk_per_share,
            total_risk=shares * risk_per_share,
            method="volatility",
            reason=f"ATR={atr:.2f}",
        )

    def check_trade_allowed(self, open_positions: int) -> tuple[bool, str]:
        """Pre-trade risk checks."""
        # Daily loss limit
        daily_loss_limit = self.current_equity * self.config.max_daily_loss_pct
        if self.daily_pnl < -daily_loss_limit:
            return False, f"Daily loss limit reached: ฿{self.daily_pnl:,.2f}"

        # Max positions
        if open_positions >= self.config.max_open_positions:
            return False, f"Max open positions reached: {open_positions}"

        # Max drawdown
        drawdown = (self.peak_equity - self.current_equity) / self.peak_equity
        if drawdown > self.config.max_drawdown_pct:
            return False, f"Max drawdown reached: {drawdown:.1%}"

        return True, "Trade allowed"

    def calculate_stop_loss(self, entry_price: float, side: str, atr: float) -> float:
        """Calculate stop-loss price."""
        if side == "BUY":
            sl = entry_price - 2 * atr
        else:
            sl = entry_price + 2 * atr
        return round_to_tick(sl)

    def calculate_take_profit(self, entry_price: float, side: str, atr: float) -> float:
        """Calculate take-profit price (3:1 reward-to-risk using ATR)."""
        if side == "BUY":
            tp = entry_price + 3 * atr
        else:
            tp = entry_price - 3 * atr
        return round_to_tick(tp)

    def update_trailing_stop(
        self, current_price: float, entry_price: float, current_stop: float, side: str
    ) -> float:
        """Update trailing stop-loss."""
        trail_pct = self.config.trailing_stop_pct

        if side == "BUY":
            new_stop = current_price * (1 - trail_pct)
            return round_to_tick(max(current_stop, new_stop))
        else:
            new_stop = current_price * (1 + trail_pct)
            return round_to_tick(min(current_stop, new_stop) if current_stop > 0 else new_stop)

    def should_exit(
        self,
        current_price: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        side: str,
    ) -> tuple[bool, str]:
        """Check if position should be exited."""
        if side == "BUY":
            if current_price <= stop_loss:
                return True, f"Stop-loss hit at ฿{current_price:.2f}"
            if take_profit > 0 and current_price >= take_profit:
                return True, f"Take-profit hit at ฿{current_price:.2f}"
        else:
            if current_price >= stop_loss:
                return True, f"Stop-loss hit at ฿{current_price:.2f}"
            if take_profit > 0 and current_price <= take_profit:
                return True, f"Take-profit hit at ฿{current_price:.2f}"

        return False, ""

    def update_daily_pnl(self, pnl: float):
        """Update running daily P&L."""
        self.daily_pnl += pnl
        self.current_equity += pnl
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity
        self.daily_trades += 1

    def reset_daily(self):
        """Reset daily counters (call at start of each trading day)."""
        logger.info(
            f"Daily reset | PnL: ฿{self.daily_pnl:,.2f} | "
            f"Trades: {self.daily_trades} | Equity: ฿{self.current_equity:,.2f}"
        )
        self.daily_pnl = 0.0
        self.daily_trades = 0
