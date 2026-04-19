"""
Composite Strategy
Aggregates signals from multiple strategies with configurable weights.
Requires minimum signal agreement before generating actionable signals.
"""

import pandas as pd
from loguru import logger

from config.settings import StrategyConfig
from strategies.base import Signal, SignalType, Strategy
from strategies.momentum import MomentumStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.breakout import BreakoutStrategy
from strategies.vwap_strategy import VWAPStrategy


class CompositeStrategy(Strategy):
    """Combines multiple strategies with weighted voting."""

    name = "composite"

    def __init__(self, config: StrategyConfig | None = None):
        self.config = config or StrategyConfig()
        self.strategies: list[tuple[Strategy, float]] = [
            (MomentumStrategy(
                rsi_period=self.config.momentum_rsi_period,
                rsi_oversold=self.config.momentum_rsi_oversold,
                rsi_overbought=self.config.momentum_rsi_overbought,
                macd_fast=self.config.momentum_macd_fast,
                macd_slow=self.config.momentum_macd_slow,
                macd_signal=self.config.momentum_macd_signal,
            ), 1.2),
            (MeanReversionStrategy(
                bb_period=self.config.mean_rev_bb_period,
                bb_std=self.config.mean_rev_bb_std,
                lookback=self.config.mean_rev_lookback,
            ), 1.0),
            (BreakoutStrategy(
                lookback=self.config.breakout_lookback,
                volume_mult=self.config.breakout_volume_mult,
                atr_period=self.config.breakout_atr_period,
            ), 1.1),
            (VWAPStrategy(
                deviation_entry=self.config.vwap_deviation_entry,
                deviation_exit=self.config.vwap_deviation_exit,
            ), 1.5),
        ]

    def get_required_bars(self) -> int:
        return max(s.get_required_bars() for s, _ in self.strategies)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        if len(df) < self.get_required_bars():
            return Signal(SignalType.HOLD, symbol, reason="Insufficient data")

        signals: list[tuple[Signal, float]] = []
        for strategy, weight in self.strategies:
            try:
                sig = strategy.generate_signal(df, symbol)
                signals.append((sig, weight))
                logger.debug(
                    f"[{strategy.name}] {symbol}: {sig.signal_type.value} "
                    f"strength={sig.strength:.2f} - {sig.reason}"
                )
            except Exception as e:
                logger.warning(f"Strategy {strategy.name} error for {symbol}: {e}")

        # Aggregate weighted votes
        buy_weight = 0.0
        sell_weight = 0.0
        buy_count = 0
        sell_count = 0
        all_reasons = []
        best_stop_loss = 0.0
        best_take_profit = 0.0

        for sig, weight in signals:
            if sig.signal_type == SignalType.BUY:
                buy_weight += sig.strength * weight
                buy_count += 1
                all_reasons.append(f"[{sig.strategy_name}] {sig.reason}")
                if sig.stop_loss > 0:
                    best_stop_loss = max(best_stop_loss, sig.stop_loss)
                if sig.take_profit > 0:
                    best_take_profit = (
                        sig.take_profit if best_take_profit == 0
                        else min(best_take_profit, sig.take_profit)
                    )
            elif sig.signal_type == SignalType.SELL:
                sell_weight += sig.strength * weight
                sell_count += 1
                all_reasons.append(f"[{sig.strategy_name}] {sig.reason}")

        current_price = float(df["close"].iloc[-1])
        min_signals = self.config.min_signals_required

        # Require minimum number of agreeing strategies
        if buy_count >= min_signals and buy_weight > sell_weight:
            composite_strength = min(buy_weight / len(self.strategies), 1.0)
            return Signal(
                signal_type=SignalType.BUY,
                symbol=symbol,
                strength=composite_strength,
                price=current_price,
                stop_loss=best_stop_loss,
                take_profit=best_take_profit,
                reason=f"{buy_count} strategies agree BUY: " + " | ".join(all_reasons),
                strategy_name=self.name,
            )
        elif sell_count >= min_signals and sell_weight > buy_weight:
            composite_strength = min(sell_weight / len(self.strategies), 1.0)
            return Signal(
                signal_type=SignalType.SELL,
                symbol=symbol,
                strength=composite_strength,
                price=current_price,
                reason=f"{sell_count} strategies agree SELL: " + " | ".join(all_reasons),
                strategy_name=self.name,
            )

        return Signal(
            SignalType.HOLD, symbol, price=current_price,
            reason=f"Consensus not reached (buy={buy_count}, sell={sell_count})",
            strategy_name=self.name,
        )
