"""
SET Day Trading Bot - Main Orchestrator
Coordinates market data, signals, risk management, and order execution
in a unified trading loop aligned to SET market hours.
"""

import time
from datetime import datetime, time as dtime

import schedule
from loguru import logger

from config.settings import Settings
from data.market_data import MarketDataFetcher
from data.indicators import TechnicalIndicators as TI
from engine.executor import OrderExecutor
from engine.portfolio import Portfolio
from engine.risk_manager import RiskManager
from strategies.composite import CompositeStrategy
from strategies.base import SignalType
from utils.helpers import is_market_hours, format_thai_baht
from utils.notifier import Notifier
from utils import state_store


class SETTradingBot:
    """Main trading bot for SET day trading."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.running = False

        # Core components
        self.data = MarketDataFetcher(settings)
        self.strategy = CompositeStrategy(settings.strategy)
        self.risk = RiskManager(settings.risk, settings.trading)
        self.executor = OrderExecutor(settings)
        self.portfolio = Portfolio(
            initial_capital=settings.trading.initial_capital,
            commission_rate=settings.trading.commission_rate,
        )
        self.notifier = Notifier(settings.line_notify_token)

        # State
        self._scan_interval_secs = 60     # Scan every 60 seconds
        self._last_prices: dict[str, float] = {}

        mode = "PAPER" if settings.paper_trading else "LIVE"
        logger.info(f"SETTradingBot initialized | Mode: {mode} | "
                    f"Capital: {format_thai_baht(settings.trading.initial_capital)}")

        # Initialise state store
        state_store.save({
            **state_store._default_state(),
            "mode": mode.lower(),
            "initial_capital": settings.trading.initial_capital,
            "cash": settings.trading.initial_capital,
            "peak_equity": settings.trading.initial_capital,
            "watchlist": settings.trading.watchlist,
            "running": False,
        })

    # ------------------------------------------------------------------
    # Core trading loop
    # ------------------------------------------------------------------

    def start(self):
        """Start the trading bot with scheduled jobs."""
        logger.info("Starting SETTradingBot...")
        self.running = True
        state_store.update({"running": True})

        if not self.settings.paper_trading:
            authenticated = self.data.authenticate()
            if not authenticated:
                logger.error("Failed to authenticate with broker API. Exiting.")
                return

        # Schedule trading loop
        schedule.every(self._scan_interval_secs).seconds.do(self._trading_cycle)

        # Daily reset at market open
        schedule.every().day.at(self.settings.trading.market_open).do(self._on_market_open)

        # End-of-day wrap-up
        schedule.every().day.at(self.settings.trading.trading_end).do(self._on_market_close)

        # Equity snapshot every 5 minutes
        schedule.every(5).minutes.do(self._record_equity)

        logger.info("Scheduler running. Press Ctrl+C to stop.")
        try:
            while self.running:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutdown requested.")
        finally:
            self._shutdown()

    def stop(self):
        self.running = False

    # ------------------------------------------------------------------
    # Scheduled handlers
    # ------------------------------------------------------------------

    def _on_market_open(self):
        """Called at market open: reset daily counters."""
        logger.info("=" * 60)
        logger.info("  MARKET OPEN — Starting trading day")
        logger.info("=" * 60)
        self.risk.reset_daily()
        self.notifier.send("🔔 SET Market Open — Bot is active")

    def _on_market_close(self):
        """Called near market close: close all positions, send summary."""
        logger.info("Market close approaching — closing all positions...")
        self._close_all_positions(reason="end_of_day")

        stats = self.portfolio.get_stats()
        stats["portfolio_value"] = self.portfolio.cash
        self.notifier.daily_summary(stats)
        self._print_daily_summary(stats)

    def _trading_cycle(self):
        """Main per-tick trading cycle: scan watchlist and act on signals."""
        if not is_market_hours(
            open_time=self.settings.trading.trading_start,
            close_time=self.settings.trading.trading_end,
        ):
            return

        allowed, reason = self.risk.check_trade_allowed(len(self.portfolio.positions))
        if not allowed:
            logger.warning(f"Trading halted: {reason}")
            return

        # Update trailing stops and check exits for open positions
        self._manage_open_positions()

        # Scan for new entries
        if len(self.portfolio.positions) < self.settings.risk.max_open_positions:
            self._scan_for_entries()

    def _manage_open_positions(self):
        """Update stops and check exit conditions for all open positions."""
        for symbol, position in list(self.portfolio.positions.items()):
            df = self._get_data(symbol)
            if df is None or df.empty:
                continue

            current_price = float(df["close"].iloc[-1])
            self._last_prices[symbol] = current_price

            # Update trailing stop
            atr_series = TI.atr(df)
            if not atr_series.empty:
                position.trailing_stop = self.risk.update_trailing_stop(
                    current_price, position.entry_price,
                    position.trailing_stop, position.side
                )
                position.stop_loss = max(position.stop_loss, position.trailing_stop)

            # Check exit conditions
            should_exit, exit_reason = self.risk.should_exit(
                current_price, position.entry_price,
                position.stop_loss, position.take_profit, position.side
            )

            if not should_exit:
                # Check strategy exit signal
                sig = self.strategy.generate_signal(df, symbol)
                if sig.signal_type == SignalType.SELL and sig.strength > 0.4:
                    should_exit = True
                    exit_reason = f"Strategy signal: {sig.reason}"

            if should_exit:
                self._exit_position(symbol, current_price, exit_reason)

    def _scan_for_entries(self):
        """Scan watchlist for entry signals."""
        for symbol in self.settings.trading.watchlist:
            if symbol in self.portfolio.positions:
                continue  # Already holding

            df = self._get_data(symbol)
            if df is None or df.empty:
                continue

            sig = self.strategy.generate_signal(df, symbol)

            if sig.signal_type == SignalType.BUY and sig.is_actionable:
                logger.info(
                    f"Signal: BUY {symbol} @ ฿{sig.price:.2f} | "
                    f"Strength: {sig.strength:.2f} | {sig.reason}"
                )
                state_store.append_signal({
                    "time": datetime.now().isoformat(),
                    "symbol": symbol,
                    "type": "BUY",
                    "price": sig.price,
                    "strength": sig.strength,
                    "reason": sig.reason,
                })
                self._enter_position(sig, df)

    # ------------------------------------------------------------------
    # Entry / Exit helpers
    # ------------------------------------------------------------------

    def _enter_position(self, sig, df):
        """Execute a buy entry."""
        symbol = sig.symbol
        current_price = sig.price

        # Position sizing
        atr_series = TI.atr(df)
        atr_val = float(atr_series.iloc[-1]) if not atr_series.empty else current_price * 0.02
        stop_loss = sig.stop_loss if sig.stop_loss > 0 else self.risk.calculate_stop_loss(
            current_price, "BUY", atr_val
        )
        take_profit = sig.take_profit if sig.take_profit > 0 else self.risk.calculate_take_profit(
            current_price, "BUY", atr_val
        )

        size = self.risk.calculate_position_size(
            price=current_price,
            stop_loss=stop_loss,
            signal_strength=sig.strength,
            df=df,
        )

        if size.shares <= 0:
            logger.debug(f"Skipping {symbol}: {size.reason}")
            return

        # Place order
        order = self.executor.place_order(
            symbol=symbol,
            side="BUY",
            quantity=size.shares,
            price=current_price,
            reason=sig.reason,
        )

        if not order.is_filled:
            logger.warning(f"Order not filled for {symbol}: {order.reason}")
            return

        # Open portfolio position
        opened = self.portfolio.open_position(
            symbol=symbol,
            price=order.filled_price,
            quantity=order.filled_quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy=sig.strategy_name,
            reason=sig.reason,
        )

        if opened:
            self.notifier.trade_alert(
                "BUY", symbol, order.filled_price,
                order.filled_quantity, sig.reason
            )

    def _exit_position(self, symbol: str, price: float, reason: str):
        """Execute a sell exit."""
        order = self.executor.place_order(
            symbol=symbol,
            side="SELL",
            quantity=self.portfolio.positions[symbol].quantity,
            price=price,
            reason=reason,
        )

        if not order.is_filled:
            logger.warning(f"Exit order not filled for {symbol}: {order.reason}")
            return

        pnl = self.portfolio.close_position(symbol, order.filled_price, reason)
        self.risk.update_daily_pnl(pnl)

        self.notifier.trade_alert(
            "SELL", symbol, order.filled_price,
            order.filled_quantity, f"{reason} | P&L: {format_thai_baht(pnl)}"
        )

    def _close_all_positions(self, reason: str = "manual"):
        """Force close all open positions."""
        for symbol in list(self.portfolio.positions.keys()):
            df = self._get_data(symbol)
            price = (
                float(df["close"].iloc[-1])
                if df is not None and not df.empty
                else self.portfolio.positions[symbol].entry_price
            )
            self._exit_position(symbol, price, reason)

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    def _get_data(self, symbol: str):
        """Fetch latest intraday data, with simulation fallback."""
        if self.settings.paper_trading and not self.settings.broker.settrade_app_id:
            return self.data.generate_simulated_data(symbol)

        df = self.data.get_intraday_bars(
            symbol,
            interval=self.settings.trading.primary_timeframe,
            limit=200,
        )
        return df if not df.empty else None

    def _record_equity(self):
        """Snapshot portfolio equity."""
        self.portfolio.record_equity(self._last_prices)
        equity = self.portfolio.get_total_equity(self._last_prices)
        state_store.append_equity(datetime.now().isoformat(), equity)
        state_store.update({
            "cash": self.portfolio.cash,
            "daily_pnl": self.risk.daily_pnl,
            "daily_trades": self.risk.daily_trades,
            "peak_equity": self.risk.peak_equity,
            "positions": {
                sym: {
                    "side": pos.side,
                    "entry_price": pos.entry_price,
                    "quantity": pos.quantity,
                    "stop_loss": pos.stop_loss,
                    "take_profit": pos.take_profit,
                    "strategy": pos.strategy,
                    "entry_time": pos.entry_time.isoformat(),
                    "current_price": self._last_prices.get(sym, pos.entry_price),
                    "unrealized_pnl": pos.unrealized_pnl(
                        self._last_prices.get(sym, pos.entry_price)
                    ),
                }
                for sym, pos in self.portfolio.positions.items()
            },
            "closed_trades": [
                {
                    "symbol": t.symbol,
                    "side": t.side,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "quantity": t.quantity,
                    "pnl": t.pnl,
                    "pnl_pct": t.pnl_pct,
                    "strategy": t.strategy,
                    "reason": t.reason,
                    "entry_time": t.entry_time.isoformat(),
                    "exit_time": t.exit_time.isoformat(),
                }
                for t in self.portfolio.closed_trades[-100:]
            ],
        })

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def _print_daily_summary(self, stats: dict):
        logger.info("=" * 50)
        logger.info("  END-OF-DAY SUMMARY")
        logger.info("=" * 50)
        logger.info(f"  Trades        : {stats.get('total_trades', 0)}")
        logger.info(f"  Win Rate      : {stats.get('win_rate', 0):.1f}%")
        logger.info(f"  Realized P&L  : {format_thai_baht(stats.get('realized_pnl', 0))}")
        logger.info(f"  Total Commiss : {format_thai_baht(stats.get('total_commission', 0))}")
        logger.info(f"  Profit Factor : {stats.get('profit_factor', 0):.2f}")
        logger.info(f"  Cash Balance  : {format_thai_baht(stats.get('portfolio_value', 0))}")
        logger.info("=" * 50)

    def print_status(self):
        """Print current bot status."""
        self.portfolio.print_positions(self._last_prices)
        stats = self.portfolio.get_stats()
        logger.info(
            f"Daily P&L: {format_thai_baht(self.risk.daily_pnl)} | "
            f"Trades today: {self.risk.daily_trades} | "
            f"Cash: {format_thai_baht(self.portfolio.cash)}"
        )

    def _shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down bot...")
        state_store.update({"running": False})
        if self.portfolio.positions:
            logger.warning(
                f"Warning: {len(self.portfolio.positions)} open positions not closed."
            )
        logger.info("Bot stopped.")
