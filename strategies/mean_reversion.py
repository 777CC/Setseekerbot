"""
Mean Reversion Day Trading Strategy
Uses Bollinger Bands and RSI to identify overextended moves
that are likely to revert to the mean.
"""

import pandas as pd

from data.indicators import TechnicalIndicators as TI
from strategies.base import Signal, SignalType, Strategy


class MeanReversionStrategy(Strategy):
    name = "mean_reversion"

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        rsi_low: float = 25.0,
        rsi_high: float = 75.0,
        lookback: int = 60,
    ):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_low = rsi_low
        self.rsi_high = rsi_high
        self.lookback = lookback

    def get_required_bars(self) -> int:
        return max(self.bb_period, self.lookback) + 5

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        if len(df) < self.get_required_bars():
            return Signal(SignalType.HOLD, symbol, reason="Insufficient data")

        close = df["close"]
        current_price = float(close.iloc[-1])

        # Bollinger Bands
        bb_upper, bb_middle, bb_lower = TI.bollinger_bands(
            close, self.bb_period, self.bb_std
        )
        bb_pct = TI.bb_percent(close, self.bb_period, self.bb_std)

        # RSI
        rsi = TI.rsi(close, self.rsi_period)
        atr = TI.atr(df)

        current_bb_pct = float(bb_pct.iloc[-1])
        current_rsi = float(rsi.iloc[-1])
        current_bb_middle = float(bb_middle.iloc[-1])
        current_bb_lower = float(bb_lower.iloc[-1])
        current_bb_upper = float(bb_upper.iloc[-1])
        current_atr = float(atr.iloc[-1])

        # Williams %R for additional confirmation
        williams = TI.williams_r(df)
        current_williams = float(williams.iloc[-1])

        buy_score = 0.0
        sell_score = 0.0
        reasons = []

        # Price below lower BB = potential buy
        if current_bb_pct < 0.0:
            buy_score += 0.35
            reasons.append(f"Below lower BB (%B={current_bb_pct:.2f})")
        elif current_bb_pct > 1.0:
            sell_score += 0.35
            reasons.append(f"Above upper BB (%B={current_bb_pct:.2f})")

        # RSI confirmation
        if current_rsi < self.rsi_low:
            buy_score += 0.3
            reasons.append(f"RSI oversold ({current_rsi:.1f})")
        elif current_rsi > self.rsi_high:
            sell_score += 0.3
            reasons.append(f"RSI overbought ({current_rsi:.1f})")

        # Williams %R confirmation
        if current_williams < -80:
            buy_score += 0.15
            reasons.append(f"Williams oversold ({current_williams:.1f})")
        elif current_williams > -20:
            sell_score += 0.15
            reasons.append(f"Williams overbought ({current_williams:.1f})")

        # Check for reversal candle pattern (hammer / shooting star)
        last = df.iloc[-1]
        body = abs(last["close"] - last["open"])
        total_range = last["high"] - last["low"]
        if total_range > 0:
            body_ratio = body / total_range
            if body_ratio < 0.3:  # Small body = indecision/reversal
                if last["close"] > last["open"]:  # Bullish reversal
                    buy_score += 0.1
                    reasons.append("Bullish reversal candle")
                else:
                    sell_score += 0.1
                    reasons.append("Bearish reversal candle")

        # Generate signal
        if buy_score > sell_score and buy_score >= 0.45:
            stop_loss = current_price - 1.5 * current_atr
            take_profit = current_bb_middle  # Target: revert to mean
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
        elif sell_score > buy_score and sell_score >= 0.45:
            return Signal(
                signal_type=SignalType.SELL,
                symbol=symbol,
                strength=min(sell_score, 1.0),
                price=current_price,
                reason=" | ".join(reasons),
                strategy_name=self.name,
            )

        return Signal(SignalType.HOLD, symbol, price=current_price,
                      reason="No mean reversion signal", strategy_name=self.name)
