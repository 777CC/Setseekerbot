"""
SET Trading Bot - Configuration Settings
Manages all trading parameters, risk limits, and broker credentials.
"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class BrokerConfig:
    api_key: str = ""
    api_secret: str = ""
    account_id: str = ""
    settrade_app_id: str = ""
    settrade_app_secret: str = ""

    @classmethod
    def from_env(cls) -> "BrokerConfig":
        return cls(
            api_key=os.getenv("BROKER_API_KEY", ""),
            api_secret=os.getenv("BROKER_API_SECRET", ""),
            account_id=os.getenv("BROKER_ACCOUNT_ID", ""),
            settrade_app_id=os.getenv("SETTRADE_APP_ID", ""),
            settrade_app_secret=os.getenv("SETTRADE_APP_SECRET", ""),
        )


@dataclass
class RiskConfig:
    max_position_pct: float = 0.10       # Max 10% of portfolio per position
    max_daily_loss_pct: float = 0.02     # Stop trading if daily loss > 2%
    max_open_positions: int = 5          # Max concurrent positions
    stop_loss_pct: float = 0.02          # Default 2% stop-loss
    take_profit_pct: float = 0.03        # Default 3% take-profit
    trailing_stop_pct: float = 0.015     # 1.5% trailing stop
    max_drawdown_pct: float = 0.05       # Max 5% drawdown before halt
    position_size_method: str = "kelly"  # kelly, fixed, volatility


@dataclass
class TradingConfig:
    initial_capital: float = 1_000_000.0
    watchlist: list = field(default_factory=lambda: [
        "AOT", "ADVANC", "AWC", "BBL", "BDMS", "BEM", "BGRIM", "BH",
        "BTS", "CBG", "CENTEL", "COM7", "CPALL", "CPF", "CPN", "CRC",
        "DELTA", "EA", "EGCO", "GLOBAL", "GPSC", "GULF", "HMPRO",
        "INTUCH", "IVL", "JMT", "KBANK", "KCE", "KTB", "KTC",
        "LH", "MINT", "MTC", "OR", "OSP", "PTT", "PTTEP", "PTTGC",
        "RATCH", "SAWAD", "SCB", "SCC", "SCGP", "TISCO", "TOP",
        "TRUE", "TTB", "TU", "WHA",
    ])
    timeframes: list = field(default_factory=lambda: ["1m", "5m", "15m", "1h"])
    primary_timeframe: str = "5m"
    trading_start: str = "09:55"       # Start 25min after open for stability
    trading_end: str = "16:20"         # Stop 10min before close
    market_open: str = "09:30"
    market_close: str = "16:30"
    tick_size_rules: dict = field(default_factory=lambda: {
        # SET tick size rules based on price range
        (0, 2): 0.01,
        (2, 5): 0.02,
        (5, 10): 0.05,
        (10, 25): 0.10,
        (25, 50): 0.25,
        (50, 100): 0.50,
        (100, 200): 1.00,
        (200, 400): 2.00,
        (400, 800): 4.00,
        (800, float("inf")): 6.00,
    })
    min_trade_value: float = 0.0       # SET has no minimum
    commission_rate: float = 0.001578  # ~0.1578% (including VAT, fees)
    slippage_bps: float = 5.0          # 5 basis points slippage estimate


@dataclass
class StrategyConfig:
    # Momentum strategy
    momentum_rsi_period: int = 14
    momentum_rsi_oversold: float = 30.0
    momentum_rsi_overbought: float = 70.0
    momentum_macd_fast: int = 12
    momentum_macd_slow: int = 26
    momentum_macd_signal: int = 9

    # Mean reversion strategy
    mean_rev_bb_period: int = 20
    mean_rev_bb_std: float = 2.0
    mean_rev_lookback: int = 60

    # Breakout strategy
    breakout_lookback: int = 20
    breakout_volume_mult: float = 1.5
    breakout_atr_period: int = 14

    # VWAP strategy
    vwap_deviation_entry: float = 1.5
    vwap_deviation_exit: float = 0.5

    # Signal confirmation
    min_signals_required: int = 2      # Need at least 2 signals to trade
    signal_weight_rsi: float = 1.0
    signal_weight_macd: float = 1.2
    signal_weight_bb: float = 1.0
    signal_weight_vwap: float = 1.5
    signal_weight_volume: float = 0.8


@dataclass
class Settings:
    broker: BrokerConfig = field(default_factory=BrokerConfig.from_env)
    risk: RiskConfig = field(default_factory=RiskConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    line_notify_token: str = ""
    log_level: str = "INFO"
    paper_trading: bool = True  # Default to paper trading for safety

    @classmethod
    def load(cls) -> "Settings":
        settings = cls()
        settings.trading.initial_capital = float(
            os.getenv("INITIAL_CAPITAL", "1000000")
        )
        settings.risk.max_position_pct = float(
            os.getenv("MAX_POSITION_PCT", "0.10")
        )
        settings.risk.max_daily_loss_pct = float(
            os.getenv("MAX_DAILY_LOSS_PCT", "0.02")
        )
        settings.risk.max_open_positions = int(
            os.getenv("MAX_OPEN_POSITIONS", "5")
        )
        settings.line_notify_token = os.getenv("LINE_NOTIFY_TOKEN", "")
        settings.paper_trading = os.getenv("PAPER_TRADING", "true").lower() == "true"
        return settings
