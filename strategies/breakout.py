"""
Breakout Day Trading Strategy
Detects price breakouts from consolidation ranges with volume confirmation.
Suitable for high-momentum SET stocks.
"""

import numpy as np
import pandas as pd

from data.indicators import TechnicalIndicators as TI
from strategies.base import Signal, SignalType, Strategy


class BreakoutStrategy(Strategy):
    name = "breakout"

    def __init__(
        self,
        lookback: int = 20,
        volume_mult: float = 1.5,
        atr_period: int = 14,
        adx_threshold: float = 25.0,
    ):
        self.lookback = lookback
        self.volume_mult = volume_mult
        self.atr_period = atr_period
        self.adx_threshold = adx_threshold

    def get_required_bars(self) -> int:
        return self.lookback + self.atr_period + 5

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        if len(df) < self.get_required_bars():
            return Signal(SignalType.HOLD, symbol, reason="Insufficient data")

        close = df["close"]
        current_price = float(close.iloc[-1])
        prev_price = float(close.iloc[-2])

        # Range boundaries
        lookback_data = df.iloc[-self.lookback - 1:-1]
        resistance = float(lookback_data["high"].max())
        support = float(lookback_data["low"].min())
        range_size = resistance - support

        # ATR for stop-loss
        atr = TI.atr(df, self.atr_period)
        current_atr = float(atr.iloc[-1])

        # Volume confirmation
        vol_ratio = TI.volume_ratio(df["volume"])
        current_vol_ratio = float(vol_ratio.iloc[-1])

        # ADX for trend strength
        adx = TI.adx(df)
        current_adx = float(adx.iloc[-1])

        # OBV trend
        obv = TI.obv(df)
        obv_slope = float(obv.iloc[-1] - obv.iloc[-5]) if len(obv) >= 5 else 0

        buy_score = 0.0
        sell_score = 0.0
        reasons = []

        # Breakout above resistance
        if current_price > resistance and prev_price <= resistance:
            buy_score += 0.4
            reasons.append(f"Breakout above ฿{resistance:.2f}")

            # Volume confirmation
            if current_vol_ratio >= self.volume_mult:
                buy_score += 0.25
                reasons.append(f"Volume surge ({current_vol_ratio:.1f}x)")

            # ADX confirms trend
            if current_adx > self.adx_threshold:
                buy_score += 0.15
                reasons.append(f"Strong trend (ADX={current_adx:.1f})")

            # OBV confirms buying pressure
            if obv_slope > 0:
                buy_score += 0.1
                reasons.append("OBV confirms buying")

        # Breakdown below support
        elif current_price < support and prev_price >= support:
            sell_score += 0.4
            reasons.append(f"Breakdown below ฿{support:.2f}")

            if current_vol_ratio >= self.volume_mult:
                sell_score += 0.25
                reasons.append(f"Volume surge ({current_vol_ratio:.1f}x)")

            if current_adx > self.adx_threshold:
                sell_score += 0.15
                reasons.append(f"Strong trend (ADX={current_adx:.1f})")

            if obv_slope < 0:
                sell_score += 0.1
                reasons.append("OBV confirms selling")

        # Near breakout detection (within 0.5% of levels)
        elif current_price > resistance * 0.995 and current_vol_ratio > 1.3:
            buy_score += 0.2
            reasons.append("Approaching resistance with volume")

        # Generate signal
        if buy_score > sell_score and buy_score >= 0.5:
            stop_loss = resistance - current_atr  # Stop just below breakout
            take_profit = current_price + 2 * range_size  # Measured move target
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
        elif sell_score > buy_score and sell_score >= 0.5:
            return Signal(
                signal_type=SignalType.SELL,
                symbol=symbol,
                strength=min(sell_score, 1.0),
                price=current_price,
                reason=" | ".join(reasons),
                strategy_name=self.name,
            )

        return Signal(SignalType.HOLD, symbol, price=current_price,
                      reason="No breakout signal", strategy_name=self.name)
