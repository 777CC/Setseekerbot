# SetseekerBot — SET Quantitative Day Trading Bot

Automated day trading bot for the **Stock Exchange of Thailand (SET)** using quantitative strategies: momentum, mean reversion, price breakout, and VWAP deviation.

---

## Architecture

```
Setseekerbot/
├── main.py                  # Entry point (trade / backtest / status)
├── bot.py                   # Main orchestrator
├── config/
│   └── settings.py          # All parameters (risk, strategy, broker)
├── data/
│   ├── market_data.py       # Settrade Open API + simulation fallback
│   └── indicators.py        # RSI, MACD, BB, VWAP, ATR, OBV, ADX…
├── strategies/
│   ├── momentum.py          # RSI + MACD + EMA crossover
│   ├── mean_reversion.py    # Bollinger Bands + RSI reversion
│   ├── breakout.py          # Range breakout with volume confirm
│   ├── vwap_strategy.py     # VWAP deviation reversion/trend
│   └── composite.py         # Weighted multi-strategy consensus
├── engine/
│   ├── risk_manager.py      # Kelly sizing, stop-loss, drawdown limits
│   ├── executor.py          # Paper + live order execution
│   └── portfolio.py         # Position tracking, P&L, equity curve
├── backtest/
│   ├── engine.py            # Event-driven backtester
│   └── report.py            # Console tables + plotly equity charts
└── utils/
    ├── helpers.py            # SET tick sizes, commission calc
    └── notifier.py           # LINE Notify trade alerts
```

---

## Strategies

| Strategy | Signals Used | Style |
|---|---|---|
| **Momentum** | RSI + MACD crossover + EMA trend | Trend-following |
| **Mean Reversion** | Bollinger %B + RSI + Williams %R | Counter-trend |
| **Breakout** | N-bar high/low + Volume surge + ADX | Breakout |
| **VWAP** | VWAP std bands + RSI confirm | Intraday mean-reversion |
| **Composite** | Weighted vote across all 4 | Consensus |

The **Composite** strategy requires at least 2 strategies to agree before placing a trade, reducing false signals significantly.

---

## Risk Management

- **Position sizing**: Kelly Criterion (half-Kelly), fixed fractional, or volatility-based (ATR)
- **Stop-loss**: 2× ATR below entry, updated with trailing stop (1.5% trail)
- **Take-profit**: 3× ATR above entry (3:1 reward-to-risk)
- **Daily loss limit**: Trading halts if daily loss exceeds 2% of equity
- **Max drawdown**: Trading halts at 5% drawdown
- **Max positions**: 5 concurrent open positions
- **Lot sizing**: SET 100-share lots enforced automatically

---

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure credentials
cp .env.example .env
# Edit .env with your Settrade Open API credentials

# 3. Run in paper trading mode (default — no credentials needed)
python main.py

# 4. Run backtest on all watchlist symbols
python main.py --backtest

# 5. Backtest a single symbol
python main.py --backtest ADVANC

# 6. Print current portfolio status
python main.py --status

# 7. Live trading (requires valid broker credentials)
python main.py --live
```

---

## Configuration

Key parameters in `config/settings.py` or via `.env`:

| Variable | Default | Description |
|---|---|---|
| `INITIAL_CAPITAL` | 1,000,000 | Starting capital (THB) |
| `MAX_POSITION_PCT` | 0.10 | Max 10% per position |
| `MAX_DAILY_LOSS_PCT` | 0.02 | Halt at 2% daily loss |
| `MAX_OPEN_POSITIONS` | 5 | Concurrent position limit |
| `PAPER_TRADING` | true | Simulation mode |
| `LINE_NOTIFY_TOKEN` | — | LINE Notify token for alerts |

---

## SET Market Rules Implemented

- **Trading hours**: 09:30–16:30 (bot trades 09:55–16:20 for safety)
- **Tick sizes**: Price-dependent tick table (฿0.01 to ฿6.00)
- **Lot size**: Minimum 100 shares per order
- **Commission**: ~0.1578% per side (incl. VAT + regulatory fees)
- **No short selling**: Long-only strategies

---

## Disclaimer

This software is for **educational and research purposes only**. Trading stocks involves significant risk of loss. Always test thoroughly with paper trading before using real capital. Past backtest performance does not guarantee future results.
