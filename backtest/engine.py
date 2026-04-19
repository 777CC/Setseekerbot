"""
Backtesting Engine
Event-driven backtester that replays historical OHLCV bars and evaluates
strategy performance with realistic SET market rules.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from config.settings import Settings
from data.indicators import TechnicalIndicators as TI
from engine.portfolio import Portfolio, ClosedTrade
from engine.risk_manager import RiskManager
from strategies.base import Signal, SignalType, Strategy
from utils.helpers import calculate_commission, round_to_tick, get_tick_size


@dataclass
class BacktestResult:
    symbol: str
    strategy_name: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    total_return: float
    total_return_pct: float
    annualized_return: float
    sharpe_ratio: float
    max_drawdown: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    avg_holding_bars: float
    total_commission: float
    equity_curve: list[float] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)


class BacktestEngine:
    """Event-driven backtesting engine for SET trading strategies."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def run(
        self,
        df: pd.DataFrame,
        strategy: Strategy,
        symbol: str = "TEST",
        initial_capital: float = 1_000_000.0,
        warmup_bars: int | None = None,
    ) -> BacktestResult:
        """
        Run backtest on historical data.
        df must have columns: open, high, low, close, volume
        """
        if warmup_bars is None:
            warmup_bars = strategy.get_required_bars()

        capital = initial_capital
        cash = initial_capital
        commission_rate = self.settings.trading.commission_rate
        slippage_bps = self.settings.trading.slippage_bps

        equity_curve: list[float] = []
        trades: list[dict] = []

        # Position state
        in_position = False
        entry_price = 0.0
        entry_bar = 0
        quantity = 0
        stop_loss = 0.0
        take_profit = 0.0

        for i in range(warmup_bars, len(df)):
            bar = df.iloc[i]
            window = df.iloc[: i + 1]
            current_price = float(bar["close"])
            current_high = float(bar["high"])
            current_low = float(bar["low"])

            # ------ Manage open position ------
            if in_position:
                # Check stop-loss (uses bar's low/high for realism)
                sl_hit = current_low <= stop_loss
                tp_hit = take_profit > 0 and current_high >= take_profit

                exit_price = None
                exit_reason = ""

                if sl_hit:
                    exit_price = stop_loss
                    exit_reason = "stop_loss"
                elif tp_hit:
                    exit_price = take_profit
                    exit_reason = "take_profit"
                else:
                    # Update trailing stop
                    new_trail = current_price * (1 - self.settings.risk.trailing_stop_pct)
                    stop_loss = max(stop_loss, round_to_tick(new_trail))

                    # Check sell signal
                    sig = strategy.generate_signal(window, symbol)
                    if sig.signal_type == SignalType.SELL and sig.strength > 0.3:
                        exit_price = current_price * (1 - slippage_bps / 10_000)
                        exit_price = round_to_tick(exit_price)
                        exit_reason = "signal"

                if exit_price is not None:
                    proceeds = exit_price * quantity
                    comm = calculate_commission(proceeds, commission_rate)
                    net_proceeds = proceeds - comm

                    entry_cost = entry_price * quantity
                    entry_comm = calculate_commission(entry_cost, commission_rate)
                    pnl = net_proceeds - entry_cost - entry_comm

                    cash += net_proceeds
                    in_position = False

                    trades.append({
                        "entry_bar": entry_bar,
                        "exit_bar": i,
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "quantity": quantity,
                        "pnl": pnl,
                        "pnl_pct": pnl / (entry_cost + entry_comm) * 100,
                        "holding_bars": i - entry_bar,
                        "exit_reason": exit_reason,
                        "commission": comm + entry_comm,
                    })

            # ------ Look for entry ------
            if not in_position:
                sig = strategy.generate_signal(window, symbol)

                if sig.signal_type == SignalType.BUY and sig.strength > 0.3:
                    # Apply slippage
                    buy_price = current_price * (1 + slippage_bps / 10_000)
                    buy_price = round_to_tick(buy_price)

                    # Size: use 10% of cash, in 100-share lots
                    max_value = cash * self.settings.risk.max_position_pct
                    shares = int(max_value / buy_price)
                    shares = (shares // 100) * 100

                    if shares > 0:
                        cost = buy_price * shares
                        comm = calculate_commission(cost, commission_rate)
                        total_cost = cost + comm

                        if total_cost <= cash:
                            cash -= total_cost
                            in_position = True
                            entry_price = buy_price
                            entry_bar = i
                            quantity = shares

                            # Set stops from signal or defaults
                            atr_series = TI.atr(window)
                            atr_val = float(atr_series.iloc[-1]) if not atr_series.empty else buy_price * 0.02
                            stop_loss = round_to_tick(
                                sig.stop_loss if sig.stop_loss > 0
                                else buy_price - 2 * atr_val
                            )
                            take_profit = round_to_tick(
                                sig.take_profit if sig.take_profit > 0
                                else buy_price + 3 * atr_val
                            )

            # Equity snapshot
            position_value = quantity * current_price if in_position else 0.0
            equity_curve.append(cash + position_value)

        # Close any open position at end
        if in_position and len(df) > 0:
            exit_price = float(df["close"].iloc[-1])
            proceeds = exit_price * quantity
            comm = calculate_commission(proceeds, commission_rate)
            entry_cost = entry_price * quantity
            entry_comm = calculate_commission(entry_cost, commission_rate)
            pnl = (proceeds - comm) - entry_cost - entry_comm
            cash += proceeds - comm
            trades.append({
                "entry_bar": entry_bar,
                "exit_bar": len(df) - 1,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "quantity": quantity,
                "pnl": pnl,
                "pnl_pct": pnl / (entry_cost + entry_comm) * 100,
                "holding_bars": len(df) - 1 - entry_bar,
                "exit_reason": "end_of_data",
                "commission": comm + entry_comm,
            })
            equity_curve[-1] = cash

        return self._compute_result(
            symbol=symbol,
            strategy_name=strategy.name,
            initial_capital=initial_capital,
            final_capital=cash,
            equity_curve=equity_curve,
            trades=trades,
            df=df,
            warmup_bars=warmup_bars,
        )

    def _compute_result(
        self,
        symbol: str,
        strategy_name: str,
        initial_capital: float,
        final_capital: float,
        equity_curve: list[float],
        trades: list[dict],
        df: pd.DataFrame,
        warmup_bars: int,
    ) -> BacktestResult:
        """Compute performance metrics from backtest results."""
        total_return = final_capital - initial_capital
        total_return_pct = total_return / initial_capital * 100

        # Annualized return
        n_days = max(len(df) - warmup_bars, 1) / 78  # ~78 bars/day for 5-min bars
        annualized = (
            (final_capital / initial_capital) ** (252 / max(n_days, 1)) - 1
        ) * 100 if n_days > 0 else 0.0

        # Sharpe ratio
        if len(equity_curve) > 1:
            eq = np.array(equity_curve)
            daily_returns = np.diff(eq) / eq[:-1]
            sharpe = (
                np.sqrt(252 * 78) * daily_returns.mean() / daily_returns.std()
                if daily_returns.std() > 0 else 0.0
            )
        else:
            sharpe = 0.0

        # Max drawdown
        if equity_curve:
            peak = equity_curve[0]
            max_dd = 0.0
            for v in equity_curve:
                peak = max(peak, v)
                dd = (peak - v) / peak
                max_dd = max(max_dd, dd)
        else:
            max_dd = 0.0

        # Trade stats
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        gross_profit = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in losses))

        return BacktestResult(
            symbol=symbol,
            strategy_name=strategy_name,
            start_date=df.index[warmup_bars] if len(df) > warmup_bars else datetime.now(),
            end_date=df.index[-1] if len(df) > 0 else datetime.now(),
            initial_capital=initial_capital,
            final_capital=final_capital,
            total_return=total_return,
            total_return_pct=total_return_pct,
            annualized_return=annualized,
            sharpe_ratio=float(sharpe),
            max_drawdown=max_dd * 100,
            total_trades=len(trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate=len(wins) / len(trades) * 100 if trades else 0.0,
            avg_win=gross_profit / len(wins) if wins else 0.0,
            avg_loss=-gross_loss / len(losses) if losses else 0.0,
            profit_factor=gross_profit / gross_loss if gross_loss > 0 else float("inf"),
            avg_holding_bars=np.mean([t["holding_bars"] for t in trades]) if trades else 0.0,
            total_commission=sum(t["commission"] for t in trades),
            equity_curve=equity_curve,
            trades=trades,
        )

    def run_multi_symbol(
        self,
        data: dict[str, pd.DataFrame],
        strategy: Strategy,
        initial_capital: float = 1_000_000.0,
    ) -> list[BacktestResult]:
        """Run backtest across multiple symbols."""
        results = []
        for symbol, df in data.items():
            logger.info(f"Backtesting {symbol}...")
            result = self.run(df, strategy, symbol=symbol, initial_capital=initial_capital)
            results.append(result)
        return results
