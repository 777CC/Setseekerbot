"""
VWAP Day Trading Strategy
Trades deviations from VWAP (Volume Weighted Average Price).
VWAP is the gold standard for institutional intraday fair value.
"""

import pandas as pd

from data.indicators import TechnicalIndicators as TI
from strategies.base import Signal, SignalType, Strategy


class VWAPStrategy(Strategy):
    name = "vwap"

    def __init__(
        self,
        deviation_entry: float = 1.5,
        deviation_exit: float = 0.5,
        min_volume_ratio: float = 1.0,
    ):
        self.deviation_entry = deviation_entry
        self.deviation_exit = deviation_exit
        self.min_volume_ratio = min_volume_ratio

    def get_required_bars(self) -> int:
        return 30

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        if len(df) < self.get_required_bars():
            return Signal(SignalType.HOLD, symbol, reason="Insufficient data")

        close = df["close"]
        current_price = float(close.iloc[-1])

        # VWAP with bands
        vwap, vwap_upper, vwap_lower = TI.vwap_with_bands(
            df, std_mult=self.deviation_entry
        )
        current_vwap = float(vwap.iloc[-1])
        current_upper = float(vwap_upper.iloc[-1])
        current_lower = float(vwap_lower.iloc[-1])

        # Deviation from VWAP in %
        vwap_deviation = (current_price - current_vwap) / current_vwap * 100

        # Volume check
        vol_ratio = TI.volume_ratio(df["volume"])
        current_vol_ratio = float(vol_ratio.iloc[-1])

        # RSI for confirmation
        rsi = TI.rsi(close)
        current_rsi = float(rsi.iloc[-1])

        # ATR for stops
        atr = TI.atr(df)
        current_atr = float(atr.iloc[-1])

        buy_score = 0.0
        sell_score = 0.0
        reasons = []

        # Price below lower VWAP band = potential buy (reversion to VWAP)
        if current_price <= current_lower:
            buy_score += 0.4
            reasons.append(f"Below VWAP band (dev={vwap_deviation:.1f}%)")

            if current_rsi < 35:
                buy_score += 0.2
                reasons.append(f"RSI confirms ({current_rsi:.1f})")

            if current_vol_ratio >= self.min_volume_ratio:
                buy_score += 0.15
                reasons.append("Volume supports")

            # Check for price reversal (current bar closing above open)
            if df["close"].iloc[-1] > df["open"].iloc[-1]:
                buy_score += 0.1
                reasons.append("Bullish reversal bar")

        # Price above upper VWAP band = potential sell (reversion to VWAP)
        elif current_price >= current_upper:
            sell_score += 0.4
            reasons.append(f"Above VWAP band (dev={vwap_deviation:.1f}%)")

            if current_rsi > 65:
                sell_score += 0.2
                reasons.append(f"RSI confirms ({current_rsi:.1f})")

            if current_vol_ratio >= self.min_volume_ratio:
                sell_score += 0.15
                reasons.append("Volume supports")

            if df["close"].iloc[-1] < df["open"].iloc[-1]:
                sell_score += 0.1
                reasons.append("Bearish reversal bar")

        # Trend following: price crossing VWAP with momentum
        elif current_price > current_vwap and float(close.iloc[-2]) <= current_vwap:
            if current_vol_ratio > 1.3:
                buy_score += 0.3
                reasons.append("VWAP bullish cross with volume")

        elif current_price < current_vwap and float(close.iloc[-2]) >= current_vwap:
            if current_vol_ratio > 1.3:
                sell_score += 0.3
                reasons.append("VWAP bearish cross with volume")

        # Generate signal
        if buy_score > sell_score and buy_score >= 0.4:
            stop_loss = current_price - 1.5 * current_atr
            take_profit = current_vwap  # Target: revert to VWAP
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
                      reason="No VWAP signal", strategy_name=self.name)
