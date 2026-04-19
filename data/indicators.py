"""
Technical Indicators for Quantitative Day Trading
Computes RSI, MACD, Bollinger Bands, VWAP, OBV, ATR, Stochastic, and more.
All indicators are vectorized for performance.
"""

import numpy as np
import pandas as pd


class TechnicalIndicators:
    """Compute technical indicators on OHLCV DataFrames."""

    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """Relative Strength Index."""
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def macd(
        series: pd.Series,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """MACD line, signal line, histogram."""
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def bollinger_bands(
        series: pd.Series,
        period: int = 20,
        std_dev: float = 2.0,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Bollinger Bands: upper, middle, lower."""
        middle = series.rolling(window=period).mean()
        std = series.rolling(window=period).std()
        upper = middle + std_dev * std
        lower = middle - std_dev * std
        return upper, middle, lower

    @staticmethod
    def bb_percent(
        series: pd.Series,
        period: int = 20,
        std_dev: float = 2.0,
    ) -> pd.Series:
        """%B indicator - position within Bollinger Bands (0=lower, 1=upper)."""
        upper, middle, lower = TechnicalIndicators.bollinger_bands(
            series, period, std_dev
        )
        bandwidth = upper - lower
        return (series - lower) / bandwidth.replace(0, np.nan)

    @staticmethod
    def vwap(df: pd.DataFrame) -> pd.Series:
        """Volume Weighted Average Price (intraday)."""
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        cumulative_tp_vol = (typical_price * df["volume"]).cumsum()
        cumulative_vol = df["volume"].cumsum()
        return cumulative_tp_vol / cumulative_vol.replace(0, np.nan)

    @staticmethod
    def vwap_with_bands(
        df: pd.DataFrame,
        std_mult: float = 1.5,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """VWAP with standard deviation bands."""
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        cumulative_tp_vol = (typical_price * df["volume"]).cumsum()
        cumulative_vol = df["volume"].cumsum()
        vwap = cumulative_tp_vol / cumulative_vol.replace(0, np.nan)

        # Rolling VWAP standard deviation
        squared_diff = ((typical_price - vwap) ** 2 * df["volume"]).cumsum()
        variance = squared_diff / cumulative_vol.replace(0, np.nan)
        std = np.sqrt(variance)

        upper = vwap + std_mult * std
        lower = vwap - std_mult * std
        return vwap, upper, lower

    @staticmethod
    def obv(df: pd.DataFrame) -> pd.Series:
        """On-Balance Volume."""
        direction = np.sign(df["close"].diff())
        return (direction * df["volume"]).fillna(0).cumsum()

    @staticmethod
    def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Average True Range."""
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift(1)).abs()
        low_close = (df["low"] - df["close"].shift(1)).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return true_range.ewm(span=period, adjust=False).mean()

    @staticmethod
    def stochastic(
        df: pd.DataFrame,
        k_period: int = 14,
        d_period: int = 3,
    ) -> tuple[pd.Series, pd.Series]:
        """Stochastic Oscillator %K and %D."""
        lowest_low = df["low"].rolling(window=k_period).min()
        highest_high = df["high"].rolling(window=k_period).max()
        denom = (highest_high - lowest_low).replace(0, np.nan)
        k = 100 * (df["close"] - lowest_low) / denom
        d = k.rolling(window=d_period).mean()
        return k, d

    @staticmethod
    def ema(series: pd.Series, period: int) -> pd.Series:
        """Exponential Moving Average."""
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def sma(series: pd.Series, period: int) -> pd.Series:
        """Simple Moving Average."""
        return series.rolling(window=period).mean()

    @staticmethod
    def volume_ratio(volume: pd.Series, period: int = 20) -> pd.Series:
        """Current volume relative to N-period average."""
        avg_vol = volume.rolling(window=period).mean()
        return volume / avg_vol.replace(0, np.nan)

    @staticmethod
    def momentum(series: pd.Series, period: int = 10) -> pd.Series:
        """Price momentum (rate of change)."""
        shifted = series.shift(period)
        return (series - shifted) / shifted.replace(0, np.nan) * 100

    @staticmethod
    def williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Williams %R."""
        highest_high = df["high"].rolling(window=period).max()
        lowest_low = df["low"].rolling(window=period).min()
        denom = (highest_high - lowest_low).replace(0, np.nan)
        return -100 * (highest_high - df["close"]) / denom

    @staticmethod
    def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Average Directional Index (trend strength)."""
        high_diff = df["high"].diff()
        low_diff = -df["low"].diff()

        plus_dm = pd.Series(
            np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0),
            index=df.index,
        )
        minus_dm = pd.Series(
            np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0),
            index=df.index,
        )

        atr_val = TechnicalIndicators.atr(df, period)
        plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr_val.replace(0, np.nan)
        minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr_val.replace(0, np.nan)

        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        return dx.ewm(span=period, adjust=False).mean()

    @staticmethod
    def compute_all(df: pd.DataFrame, config=None) -> pd.DataFrame:
        """Compute all indicators and attach to DataFrame."""
        result = df.copy()

        # RSI
        result["rsi"] = TechnicalIndicators.rsi(df["close"])

        # MACD
        macd_line, signal_line, histogram = TechnicalIndicators.macd(df["close"])
        result["macd"] = macd_line
        result["macd_signal"] = signal_line
        result["macd_hist"] = histogram

        # Bollinger Bands
        bb_upper, bb_middle, bb_lower = TechnicalIndicators.bollinger_bands(df["close"])
        result["bb_upper"] = bb_upper
        result["bb_middle"] = bb_middle
        result["bb_lower"] = bb_lower
        result["bb_pct"] = TechnicalIndicators.bb_percent(df["close"])

        # VWAP
        result["vwap"] = TechnicalIndicators.vwap(df)
        vwap_val, vwap_upper, vwap_lower = TechnicalIndicators.vwap_with_bands(df)
        result["vwap_upper"] = vwap_upper
        result["vwap_lower"] = vwap_lower

        # Volume
        result["obv"] = TechnicalIndicators.obv(df)
        result["volume_ratio"] = TechnicalIndicators.volume_ratio(df["volume"])

        # ATR
        result["atr"] = TechnicalIndicators.atr(df)

        # Stochastic
        k, d = TechnicalIndicators.stochastic(df)
        result["stoch_k"] = k
        result["stoch_d"] = d

        # Moving averages
        result["ema_9"] = TechnicalIndicators.ema(df["close"], 9)
        result["ema_21"] = TechnicalIndicators.ema(df["close"], 21)
        result["sma_50"] = TechnicalIndicators.sma(df["close"], 50)

        # Momentum & trend
        result["momentum"] = TechnicalIndicators.momentum(df["close"])
        result["adx"] = TechnicalIndicators.adx(df)
        result["williams_r"] = TechnicalIndicators.williams_r(df)

        return result
