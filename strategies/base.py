"""
Base strategy interface and signal definitions.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

import pandas as pd


class SignalType(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Signal:
    signal_type: SignalType
    symbol: str
    strength: float = 0.0       # 0.0 to 1.0 confidence
    price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    reason: str = ""
    strategy_name: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def is_actionable(self) -> bool:
        return self.signal_type != SignalType.HOLD and self.strength > 0.3


class Strategy(ABC):
    """Base class for all trading strategies."""

    name: str = "base"

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        """Analyze data and generate a trading signal."""
        ...

    @abstractmethod
    def get_required_bars(self) -> int:
        """Minimum bars needed before strategy can generate signals."""
        ...
