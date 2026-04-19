"""
Utility functions for SET trading bot.
Includes tick size calculation, commission, and market hour checks.
"""

import math
from datetime import datetime, time


# SET tick size table
_TICK_TABLE = [
    (0, 2, 0.01),
    (2, 5, 0.02),
    (5, 10, 0.05),
    (10, 25, 0.10),
    (25, 50, 0.25),
    (50, 100, 0.50),
    (100, 200, 1.00),
    (200, 400, 2.00),
    (400, 800, 4.00),
    (800, float("inf"), 6.00),
]


def get_tick_size(price: float) -> float:
    """Get SET tick size for a given price level."""
    for low, high, tick in _TICK_TABLE:
        if low <= price < high:
            return tick
    return 6.00


def round_to_tick(price: float, direction: str = "nearest") -> float:
    """Round a price to the nearest valid SET tick."""
    tick = get_tick_size(price)
    if direction == "down":
        return math.floor(price / tick) * tick
    elif direction == "up":
        return math.ceil(price / tick) * tick
    else:
        return round(price / tick) * tick


def calculate_commission(value: float, rate: float = 0.001578) -> float:
    """
    Calculate trading commission for SET.
    Default rate: 0.1578% (commission + VAT + regulatory fees).
    """
    return value * rate


def is_market_hours(
    now: datetime | None = None,
    open_time: str = "09:30",
    close_time: str = "16:30",
) -> bool:
    """Check if current time is within SET market hours."""
    if now is None:
        now = datetime.now()

    # SET is closed on weekends
    if now.weekday() >= 5:
        return False

    market_open = time(*map(int, open_time.split(":")))
    market_close = time(*map(int, close_time.split(":")))
    return market_open <= now.time() <= market_close


def format_thai_baht(amount: float) -> str:
    """Format amount as Thai Baht."""
    if abs(amount) >= 1_000_000:
        return f"฿{amount:,.0f}"
    return f"฿{amount:,.2f}"


def calculate_sharpe_ratio(
    returns: list[float],
    risk_free_rate: float = 0.02,
    periods_per_year: int = 252,
) -> float:
    """Calculate annualized Sharpe ratio from a list of returns."""
    import numpy as np
    returns_arr = np.array(returns)
    if len(returns_arr) < 2 or returns_arr.std() == 0:
        return 0.0
    excess_returns = returns_arr - risk_free_rate / periods_per_year
    return float(np.sqrt(periods_per_year) * excess_returns.mean() / excess_returns.std())


def calculate_max_drawdown(equity_curve: list[float]) -> float:
    """Calculate maximum drawdown from an equity curve."""
    peak = equity_curve[0]
    max_dd = 0.0
    for value in equity_curve:
        if value > peak:
            peak = value
        dd = (peak - value) / peak
        if dd > max_dd:
            max_dd = dd
    return max_dd
