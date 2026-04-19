"""
Backtest Report Generator
Prints performance tables and saves equity curve charts.
"""

from datetime import datetime

from loguru import logger

from backtest.engine import BacktestResult


class BacktestReport:
    """Generate and display backtest performance reports."""

    @staticmethod
    def print_summary(result: BacktestResult):
        """Print a formatted performance summary to console."""
        divider = "=" * 60
        logger.info(divider)
        logger.info(f"  BACKTEST RESULTS: {result.symbol} | {result.strategy_name.upper()}")
        logger.info(divider)
        logger.info(f"  Period        : {result.start_date.date()} → {result.end_date.date()}")
        logger.info(f"  Initial Cap   : ฿{result.initial_capital:>15,.2f}")
        logger.info(f"  Final Cap     : ฿{result.final_capital:>15,.2f}")
        logger.info(f"  Total Return  : ฿{result.total_return:>+15,.2f}  ({result.total_return_pct:+.2f}%)")
        logger.info(f"  Annual Return : {result.annualized_return:>+14.2f}%")
        logger.info(f"  Sharpe Ratio  : {result.sharpe_ratio:>15.3f}")
        logger.info(f"  Max Drawdown  : {result.max_drawdown:>14.2f}%")
        logger.info("-" * 60)
        logger.info(f"  Total Trades  : {result.total_trades:>15,}")
        logger.info(f"  Win / Loss    : {result.winning_trades:>6,} / {result.losing_trades:<6,}")
        logger.info(f"  Win Rate      : {result.win_rate:>14.1f}%")
        logger.info(f"  Avg Win       : ฿{result.avg_win:>15,.2f}")
        logger.info(f"  Avg Loss      : ฿{result.avg_loss:>15,.2f}")
        logger.info(f"  Profit Factor : {result.profit_factor:>15.3f}")
        logger.info(f"  Avg Hold Bars : {result.avg_holding_bars:>15.1f}")
        logger.info(f"  Total Commiss : ฿{result.total_commission:>15,.2f}")
        logger.info(divider)

    @staticmethod
    def print_multi_summary(results: list[BacktestResult]):
        """Print comparison table for multiple symbol backtests."""
        if not results:
            logger.info("No results to display.")
            return

        logger.info("=" * 90)
        logger.info(
            f"{'Symbol':<10} {'Return%':>8} {'Sharpe':>8} {'MaxDD%':>8} "
            f"{'Trades':>7} {'WinRate':>8} {'PF':>7}"
        )
        logger.info("-" * 90)
        for r in sorted(results, key=lambda x: x.total_return_pct, reverse=True):
            pf_str = f"{r.profit_factor:.2f}" if r.profit_factor != float("inf") else "inf"
            logger.info(
                f"{r.symbol:<10} {r.total_return_pct:>+7.2f}% {r.sharpe_ratio:>8.3f} "
                f"{r.max_drawdown:>7.2f}% {r.total_trades:>7,} "
                f"{r.win_rate:>7.1f}% {pf_str:>7}"
            )
        logger.info("=" * 90)

        # Aggregate stats
        total_pnl = sum(r.total_return for r in results)
        avg_win_rate = sum(r.win_rate for r in results) / len(results)
        avg_sharpe = sum(r.sharpe_ratio for r in results) / len(results)
        logger.info(
            f"\n  Portfolio P&L : ฿{total_pnl:>+15,.2f}  "
            f"Avg Win Rate: {avg_win_rate:.1f}%  Avg Sharpe: {avg_sharpe:.3f}"
        )

    @staticmethod
    def save_equity_curve(result: BacktestResult, filepath: str | None = None):
        """Save equity curve chart as HTML using plotly."""
        try:
            import plotly.graph_objects as go

            if filepath is None:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                filepath = f"data/backtest_{result.symbol}_{ts}.html"

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                y=result.equity_curve,
                mode="lines",
                name="Equity",
                line=dict(color="royalblue", width=2),
            ))
            fig.add_hline(
                y=result.initial_capital,
                line_dash="dash",
                line_color="gray",
                annotation_text="Initial Capital",
            )

            # Mark trades
            for t in result.trades:
                color = "green" if t["pnl"] > 0 else "red"
                if t["exit_bar"] < len(result.equity_curve):
                    fig.add_vline(
                        x=t["exit_bar"],
                        line_color=color,
                        line_width=1,
                        opacity=0.4,
                    )

            fig.update_layout(
                title=f"{result.symbol} | {result.strategy_name} | "
                      f"Return: {result.total_return_pct:+.2f}% | "
                      f"Sharpe: {result.sharpe_ratio:.3f}",
                xaxis_title="Bar",
                yaxis_title="Portfolio Value (฿)",
                template="plotly_dark",
                height=500,
            )

            import os
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            fig.write_html(filepath)
            logger.info(f"Equity curve saved to {filepath}")

        except ImportError:
            logger.warning("plotly not installed; skipping chart save.")
        except Exception as e:
            logger.error(f"Chart save error: {e}")
