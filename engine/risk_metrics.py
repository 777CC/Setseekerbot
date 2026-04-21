"""
Risk Metrics Calculator
Computes VaR, CVaR, drawdown series, position concentration,
and risk-of-ruin estimates for the live portfolio.
"""

from datetime import datetime

import numpy as np


def drawdown_series(equity: list[float]) -> list[float]:
    """Compute per-bar drawdown (as % below running peak)."""
    if not equity:
        return []
    peak = equity[0]
    series = []
    for v in equity:
        peak = max(peak, v)
        dd = (peak - v) / peak * 100 if peak > 0 else 0.0
        series.append(dd)
    return series


def max_drawdown(equity: list[float]) -> tuple[float, int, int]:
    """Return (max_dd_pct, peak_idx, trough_idx)."""
    if len(equity) < 2:
        return 0.0, 0, 0
    peak = equity[0]
    peak_idx = 0
    max_dd = 0.0
    mdd_peak = 0
    mdd_trough = 0
    for i, v in enumerate(equity):
        if v > peak:
            peak = v
            peak_idx = i
        dd = (peak - v) / peak * 100 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
            mdd_peak = peak_idx
            mdd_trough = i
    return max_dd, mdd_peak, mdd_trough


def var_cvar(returns: list[float], confidence: float = 0.95) -> tuple[float, float]:
    """
    Historical Value-at-Risk and Conditional VaR at given confidence level.
    Returns (VaR, CVaR) as positive fractions (e.g. 0.025 = 2.5% loss).
    """
    if len(returns) < 10:
        return 0.0, 0.0
    arr = np.array(returns)
    quantile = np.quantile(arr, 1 - confidence)
    var = -float(quantile) if quantile < 0 else 0.0
    tail = arr[arr <= quantile]
    cvar = -float(tail.mean()) if len(tail) > 0 and tail.mean() < 0 else var
    return var, cvar


def position_concentration(positions: dict, total_equity: float) -> list[dict]:
    """Compute per-position weight as % of total equity."""
    if total_equity <= 0 or not positions:
        return []
    rows = []
    for sym, pos in positions.items():
        qty = pos.get("quantity", 0)
        current = pos.get("current_price", pos.get("entry_price", 0))
        market_value = qty * current
        weight = market_value / total_equity * 100
        rows.append({
            "symbol": sym,
            "market_value": market_value,
            "weight_pct": weight,
            "unrealized_pnl": pos.get("unrealized_pnl", 0),
            "side": pos.get("side", "LONG"),
            "risk_amount": max(0, (current - pos.get("stop_loss", 0)) * qty)
            if pos.get("stop_loss", 0) > 0 else 0,
        })
    rows.sort(key=lambda r: r["weight_pct"], reverse=True)
    return rows


def risk_of_ruin(win_rate: float, avg_win: float, avg_loss: float,
                 risk_per_trade: float = 0.01) -> float:
    """
    Estimate probability of total ruin using Kelly-based approximation.
    Uses formula: RoR ≈ ((1-edge)/(1+edge))^(1/risk_per_trade)
    """
    if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1:
        return 1.0
    edge = win_rate * (avg_win / avg_loss) - (1 - win_rate)
    if edge <= 0:
        return 1.0
    ratio = (1 - edge) / (1 + edge)
    if ratio <= 0:
        return 0.0
    try:
        return float(ratio ** (1 / max(risk_per_trade, 0.001)))
    except (OverflowError, ValueError):
        return 1.0


def sharpe(returns: list[float], periods_per_year: int = 252) -> float:
    """Annualized Sharpe ratio."""
    if len(returns) < 2:
        return 0.0
    arr = np.array(returns)
    if arr.std() == 0:
        return 0.0
    return float(np.sqrt(periods_per_year) * arr.mean() / arr.std())


def sortino(returns: list[float], periods_per_year: int = 252) -> float:
    """Annualized Sortino ratio (uses downside deviation only)."""
    if len(returns) < 2:
        return 0.0
    arr = np.array(returns)
    downside = arr[arr < 0]
    if len(downside) == 0 or downside.std() == 0:
        return 0.0
    return float(np.sqrt(periods_per_year) * arr.mean() / downside.std())


def calmar(total_return_pct: float, max_dd_pct: float) -> float:
    """Calmar ratio: annualized return / max drawdown."""
    if max_dd_pct <= 0:
        return 0.0
    return total_return_pct / max_dd_pct


def compute_returns(equity: list[float]) -> list[float]:
    """Convert equity curve to per-bar returns."""
    if len(equity) < 2:
        return []
    arr = np.array(equity)
    returns = np.diff(arr) / arr[:-1]
    returns = returns[np.isfinite(returns)]
    return returns.tolist()


def compute_risk_summary(state: dict, initial_capital: float,
                         max_daily_loss_pct: float = 0.02,
                         max_drawdown_pct: float = 0.05,
                         max_position_pct: float = 0.10,
                         max_open_positions: int = 5) -> dict:
    """
    Produce a comprehensive risk summary for the live portfolio.
    """
    positions = state.get("positions", {})
    cash = state.get("cash", 0.0)
    daily_pnl = state.get("daily_pnl", 0.0)
    peak_equity = state.get("peak_equity", initial_capital)
    equity_history = state.get("equity_history", [])
    closed_trades = state.get("closed_trades", [])

    positions_value = sum(
        p.get("quantity", 0) * p.get("current_price", p.get("entry_price", 0))
        for p in positions.values()
    )
    total_equity = cash + positions_value

    # Limit utilization
    current_dd_pct = (
        (peak_equity - total_equity) / peak_equity * 100
        if peak_equity > 0 else 0.0
    )
    daily_loss_limit = initial_capital * max_daily_loss_pct
    daily_loss_used = max(0, -daily_pnl) / daily_loss_limit * 100 if daily_loss_limit > 0 else 0
    dd_used = current_dd_pct / (max_drawdown_pct * 100) * 100 if max_drawdown_pct > 0 else 0
    positions_used = len(positions) / max_open_positions * 100 if max_open_positions > 0 else 0

    # Concentration
    concentration = position_concentration(positions, total_equity)
    largest_pos_pct = concentration[0]["weight_pct"] if concentration else 0.0

    # Return-based risk
    equity_values = [row[1] for row in equity_history] if equity_history else [total_equity]
    returns = compute_returns(equity_values)
    var_95, cvar_95 = var_cvar(returns, 0.95)
    dd_series = drawdown_series(equity_values)
    mdd, _, _ = max_drawdown(equity_values)

    # Trade-based risk
    wins = [t for t in closed_trades if t.get("pnl", 0) > 0]
    losses = [t for t in closed_trades if t.get("pnl", 0) <= 0]
    win_rate = len(wins) / len(closed_trades) if closed_trades else 0.5
    avg_win = np.mean([t["pnl"] for t in wins]) if wins else 0.0
    avg_loss = abs(np.mean([t["pnl"] for t in losses])) if losses else 1.0
    ror = risk_of_ruin(win_rate, avg_win, avg_loss, 0.01) * 100

    # Total risk exposure (sum of distance-to-stop × qty for open positions)
    total_risk = sum(r["risk_amount"] for r in concentration)
    risk_pct = total_risk / total_equity * 100 if total_equity > 0 else 0

    return {
        "total_equity": total_equity,
        "cash": cash,
        "positions_value": positions_value,
        "num_positions": len(positions),
        "current_drawdown_pct": current_dd_pct,
        "max_drawdown_pct": mdd,
        "daily_pnl": daily_pnl,
        "daily_loss_limit": daily_loss_limit,
        "daily_loss_used_pct": min(daily_loss_used, 999),
        "drawdown_used_pct": min(dd_used, 999),
        "positions_used_pct": min(positions_used, 999),
        "largest_position_pct": largest_pos_pct,
        "concentration": concentration,
        "drawdown_series": dd_series,
        "equity_timestamps": [row[0] for row in equity_history] if equity_history else [],
        "var_95": var_95 * 100,
        "cvar_95": cvar_95 * 100,
        "var_95_amount": var_95 * total_equity,
        "risk_of_ruin_pct": ror,
        "win_rate": win_rate * 100,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "total_risk_amount": total_risk,
        "total_risk_pct": risk_pct,
    }
