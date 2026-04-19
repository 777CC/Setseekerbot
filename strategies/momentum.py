"""
Momentum Day Trading Strategy
Combines RSI, MACD, and EMA crossover signals to identify
intraday momentum plays on SET stocks.
"""

import pandas as pd

from data.indicators import TechnicalIndicators as TI
from strategies.base import Signal, SignalType, Strategy


class MomentumStrategy(Strategy):
    name = "momentum"

    def __init__(
        self,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        ema_fast: int = 9,
        ema_slow: int = 21,
    ):
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow

    def get_required_bars(self) -> int:
        return self.macd_slow + self.macd_signal + 5

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        if len(df) < self.get_required_bars():
            return Signal(SignalType.HOLD, symbol, reason="Insufficient data")

        close = df["close"]
        current_price = float(close.iloc[-1])

        # Compute indicators
        rsi = TI.rsi(close, self.rsi_period)
        macd_line, signal_line, macd_hist = TI.macd(
            close, self.macd_fast, self.macd_slow, self.macd_signal
        )
        ema_fast = TI.ema(close, self.ema_fast)
        ema_slow = TI.ema(close, self.ema_slow)
        atr = TI.atr(df)

        current_rsi = float(rsi.iloc[-1])
        current_macd = float(macd_hist.iloc[-1])
        prev_macd = float(macd_hist.iloc[-2])
        current_ema_fast = float(ema_fast.iloc[-1])
        current_ema_slow = float(ema_slow.iloc[-1])
        current_atr = float(atr.iloc[-1])

        # Volume confirmation
        vol_ratio = TI.volume_ratio(df["volume"])
        current_vol_ratio = float(vol_ratio.iloc[-1])

        # Score components
        buy_score = 0.0
        sell_score = 0.0
        reasons = []

        # RSI signal
        if current_rsi < self.rsi_oversold:
            buy_score += 0.3
            reasons.append(f"RSI oversold ({current_rsi:.1f})")
        elif current_rsi > self.rsi_overbought:
            sell_score += 0.3
            reasons.append(f"RSI overbought ({current_rsi:.1f})")

        # MACD crossover
        if current_macd > 0 and prev_macd <= 0:
            buy_score += 0.3
            reasons.append("MACD bullish cross")
        elif current_macd < 0 and prev_macd >= 0:
            sell_score += 0.3
            reasons.append("MACD bearish cross")

        # EMA trend
        if current_ema_fast > current_ema_slow:
            buy_score += 0.2
            reasons.append("EMA bullish alignment")
        else:
            sell_score += 0.2
            reasons.append("EMA bearish alignment")

        # Volume confirmation
        if current_vol_ratio > 1.5:
            buy_score *= 1.2
            sell_score *= 1.2
            reasons.append(f"High volume ({current_vol_ratio:.1f}x)")

        # Generate signal
        if buy_score > sell_score and buy_score >= 0.4:
            stop_loss = current_price - 2 * current_atr
            take_profit = current_price + 3 * current_atr
            return Signal(
                signal_type=SignalType.BUY,
                symbol=symbol,
                strength=min(buy_score, 1.0),
                price=current_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                reason=" | ".join(reasons),
                strategy_name=self.name,
            )
        elif sell_score > buy_score and sell_score >= 0.4:
            return Signal(
                signal_type=SignalType.SELL,
                symbol=symbol,
                strength=min(sell_score, 1.0),
                price=current_price,
                reason=" | ".join(reasons),
                strategy_name=self.name,
            )

        return Signal(SignalType.HOLD, symbol, price=current_price,
                      reason="No momentum signal", strategy_name=self.name)
