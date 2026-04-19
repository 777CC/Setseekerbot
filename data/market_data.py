"""
SET Market Data Fetcher
Fetches real-time and historical price data for SET-listed stocks.
Supports Settrade Open API and web scraping fallback.
"""

import time
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import requests
from loguru import logger

from config.settings import Settings


class MarketDataFetcher:
    """Fetches and manages market data for SET stocks."""

    BASE_URL = "https://api.settrade.com/api"
    MARKETDATA_URL = "https://marketdata.settrade.com/api"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._session = requests.Session()
        self._token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
        self._cache: dict[str, pd.DataFrame] = {}

    def authenticate(self) -> bool:
        """Authenticate with Settrade Open API."""
        try:
            resp = self._session.post(
                f"{self.BASE_URL}/oam/v1/login",
                json={
                    "appId": self.settings.broker.settrade_app_id,
                    "appSecret": self.settings.broker.settrade_app_secret,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                self._token = data.get("accessToken")
                self._token_expiry = datetime.now() + timedelta(
                    seconds=data.get("expiresIn", 3600)
                )
                self._session.headers.update(
                    {"Authorization": f"Bearer {self._token}"}
                )
                logger.info("Settrade API authenticated successfully")
                return True
            logger.warning(f"Auth failed: {resp.status_code}")
            return False
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False

    def _ensure_auth(self):
        if self._token is None or (
            self._token_expiry and datetime.now() >= self._token_expiry
        ):
            self.authenticate()

    def get_quote(self, symbol: str) -> Optional[dict]:
        """Get real-time quote for a SET stock."""
        self._ensure_auth()
        try:
            resp = self._session.get(
                f"{self.MARKETDATA_URL}/quote/v1/{symbol}",
                timeout=5,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"Quote fetch error for {symbol}: {e}")
        return None

    def get_intraday_bars(
        self,
        symbol: str,
        interval: str = "5m",
        limit: int = 200,
    ) -> pd.DataFrame:
        """
        Get intraday OHLCV bars for a symbol.
        interval: '1m', '5m', '15m', '1h'
        """
        self._ensure_auth()
        try:
            resp = self._session.get(
                f"{self.MARKETDATA_URL}/chart/v1/{symbol}/intraday",
                params={"interval": interval, "limit": limit},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                df = self._parse_ohlcv(data)
                self._cache[f"{symbol}_{interval}"] = df
                return df
        except Exception as e:
            logger.error(f"Intraday bars error for {symbol}: {e}")

        # Return cached data if available
        cache_key = f"{symbol}_{interval}"
        if cache_key in self._cache:
            logger.warning(f"Using cached data for {symbol}")
            return self._cache[cache_key]
        return pd.DataFrame()

    def get_historical_daily(
        self,
        symbol: str,
        days: int = 60,
    ) -> pd.DataFrame:
        """Get historical daily OHLCV data."""
        self._ensure_auth()
        try:
            end = datetime.now()
            start = end - timedelta(days=days)
            resp = self._session.get(
                f"{self.MARKETDATA_URL}/chart/v1/{symbol}/history",
                params={
                    "start": start.strftime("%Y-%m-%d"),
                    "end": end.strftime("%Y-%m-%d"),
                    "interval": "1D",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                return self._parse_ohlcv(resp.json())
        except Exception as e:
            logger.error(f"Historical data error for {symbol}: {e}")
        return pd.DataFrame()

    def get_market_status(self) -> dict:
        """Get SET market status (pre-open, open, intermission, close)."""
        try:
            resp = self._session.get(
                f"{self.MARKETDATA_URL}/market-status/v1/SET",
                timeout=5,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"Market status error: {e}")
        return {"status": "unknown"}

    def get_best_bid_offer(self, symbol: str) -> Optional[dict]:
        """Get best 5 bids and offers for a symbol."""
        self._ensure_auth()
        try:
            resp = self._session.get(
                f"{self.MARKETDATA_URL}/quote/v1/{symbol}/bbo",
                timeout=5,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"BBO error for {symbol}: {e}")
        return None

    def get_ticker_trades(self, symbol: str, limit: int = 50) -> pd.DataFrame:
        """Get recent tick-by-tick trades."""
        self._ensure_auth()
        try:
            resp = self._session.get(
                f"{self.MARKETDATA_URL}/quote/v1/{symbol}/trades",
                params={"limit": limit},
                timeout=5,
            )
            if resp.status_code == 200:
                trades = resp.json()
                return pd.DataFrame(trades)
        except Exception as e:
            logger.error(f"Ticker trades error for {symbol}: {e}")
        return pd.DataFrame()

    def get_set_index(self) -> Optional[dict]:
        """Get current SET Index value."""
        try:
            resp = self._session.get(
                f"{self.MARKETDATA_URL}/index/v1/SET",
                timeout=5,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"SET Index error: {e}")
        return None

    def scan_top_movers(self, direction: str = "gainer", limit: int = 20) -> list:
        """Scan for top gainers/losers/most-active."""
        try:
            resp = self._session.get(
                f"{self.MARKETDATA_URL}/ranking/v1/{direction}",
                params={"market": "SET", "limit": limit},
                timeout=5,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"Top movers scan error: {e}")
        return []

    @staticmethod
    def _parse_ohlcv(data: dict | list) -> pd.DataFrame:
        """Parse OHLCV data into a standardized DataFrame."""
        if isinstance(data, dict):
            bars = data.get("bars", data.get("data", []))
        else:
            bars = data

        if not bars:
            return pd.DataFrame()

        df = pd.DataFrame(bars)
        column_map = {
            "o": "open", "h": "high", "l": "low", "c": "close",
            "v": "volume", "t": "timestamp", "val": "value",
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        }
        df.rename(columns={k: v for k, v in column_map.items() if k in df.columns},
                  inplace=True)

        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)

        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
            df.set_index("timestamp", inplace=True)
            df.sort_index(inplace=True)

        return df

    def generate_simulated_data(
        self,
        symbol: str,
        bars: int = 200,
        base_price: float = 100.0,
        volatility: float = 0.02,
    ) -> pd.DataFrame:
        """Generate simulated intraday data for paper trading / backtesting."""
        np.random.seed(hash(symbol) % 2**31)
        timestamps = pd.date_range(
            end=datetime.now(),
            periods=bars,
            freq="5min",
        )

        returns = np.random.normal(0, volatility, bars)
        prices = base_price * np.exp(np.cumsum(returns))

        highs = prices * (1 + np.abs(np.random.normal(0, volatility / 2, bars)))
        lows = prices * (1 - np.abs(np.random.normal(0, volatility / 2, bars)))
        opens = lows + (highs - lows) * np.random.random(bars)
        volumes = np.random.randint(10000, 500000, bars)

        df = pd.DataFrame({
            "open": opens,
            "high": highs,
            "low": lows,
            "close": prices,
            "volume": volumes,
        }, index=timestamps)
        df.index.name = "timestamp"
        return df
