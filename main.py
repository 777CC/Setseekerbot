"""
SET Day Trading Bot — Entry Point

Usage:
  python main.py                    # Run live/paper trading bot
  python main.py --backtest         # Run backtest on watchlist
  python main.py --backtest ADVANC  # Backtest a specific symbol
  python main.py --status           # Print portfolio status and exit
"""

import argparse
import sys

from loguru import logger

from config.settings import Settings
from bot import SETTradingBot
from backtest.engine import BacktestEngine
from backtest.report import BacktestReport
from strategies.composite import CompositeStrategy


def setup_logging(level: str = "INFO"):
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
        level=level,
        colorize=True,
    )
    logger.add(
        "data/logs/set_bot_{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="30 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
    )


def run_backtest(settings: Settings, symbol: str | None = None):
    """Run backtesting on one or all watchlist symbols."""
    import os
    os.makedirs("data/logs", exist_ok=True)

    engine = BacktestEngine(settings)
    strategy = CompositeStrategy(settings.strategy)
    data_fetcher = __import__("data.market_data", fromlist=["MarketDataFetcher"]).MarketDataFetcher(settings)

    symbols = [symbol] if symbol else settings.trading.watchlist[:10]  # Top 10 for demo

    logger.info(f"Running backtest on {len(symbols)} symbol(s)...")
    results = []

    for sym in symbols:
        logger.info(f"Fetching data for {sym}...")
        # Try API, fall back to simulation
        df = data_fetcher.get_historical_daily(sym, days=90)
        if df.empty:
            logger.warning(f"No data for {sym}, using simulated data")
            df = data_fetcher.generate_simulated_data(sym, bars=500)

        result = engine.run(
            df, strategy, symbol=sym,
            initial_capital=settings.trading.initial_capital,
        )
        BacktestReport.print_summary(result)
        BacktestReport.save_equity_curve(result)
        results.append(result)

    if len(results) > 1:
        logger.info("\n--- PORTFOLIO COMPARISON ---")
        BacktestReport.print_multi_summary(results)


def main():
    import os
    os.makedirs("data/logs", exist_ok=True)

    parser = argparse.ArgumentParser(description="SET Day Trading Bot")
    parser.add_argument("--backtest", nargs="?", const=True, metavar="SYMBOL",
                        help="Run backtest (optionally on a specific symbol)")
    parser.add_argument("--status", action="store_true", help="Print status and exit")
    parser.add_argument("--live", action="store_true",
                        help="Enable live trading (disables paper trading)")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    setup_logging(args.log_level)

    settings = Settings.load()

    if args.live:
        settings.paper_trading = False
        logger.warning("⚠️  LIVE TRADING MODE ENABLED — real money at risk!")

    logger.info(f"SET Trading Bot | Paper: {settings.paper_trading} | "
                f"Capital: ฿{settings.trading.initial_capital:,.0f}")

    if args.backtest is not None:
        symbol = args.backtest if isinstance(args.backtest, str) else None
        run_backtest(settings, symbol)
        return

    bot = SETTradingBot(settings)

    if args.status:
        bot.print_status()
        return

    bot.start()


if __name__ == "__main__":
    main()
