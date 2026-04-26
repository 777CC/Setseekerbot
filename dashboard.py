"""
SetseekerBot — Dashboard (Live + Backtest)
Run with:  streamlit run dashboard.py

Pages:
  • Live Trading — real-time portfolio view (auto-refresh every 10s)
  • Backtest     — run strategies against historical/simulated data
"""

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from config.settings import Settings, StrategyConfig
from data.market_data import MarketDataFetcher
from backtest.engine import BacktestEngine, BacktestResult
from engine import risk_metrics
from strategies.composite import CompositeStrategy
from strategies.momentum import MomentumStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.breakout import BreakoutStrategy
from strategies.vwap_strategy import VWAPStrategy
from utils import state_store
from utils.helpers import get_tick_size, round_to_tick, calculate_commission


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SetseekerBot",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

_CSS = """
<style>
    .pos-pnl { color: #50fa7b; font-weight: bold; }
    .neg-pnl { color: #ff5555; font-weight: bold; }
    div[data-testid="stMetricValue"] > div { font-size: 1.6rem; }
    .stTabs [data-baseweb="tab-list"] { gap: 6px; }
    .stTabs [data-baseweb="tab"] {
        background: #1e1e2e; border-radius: 6px; padding: 8px 16px;
    }
    .stTabs [aria-selected="true"] { background: #44475a; }
</style>
"""
st.markdown(_CSS, unsafe_allow_html=True)


def _fmt_thb(v: float) -> str:
    return f"฿{v:,.2f}"


_SETTRADE_URL = "https://www.settrade.com/th/equities/quote/{symbol}/overview"


def _sym_link(symbol: str) -> str:
    """Return an HTML link that opens the Settrade quote page in a new tab."""
    url = _SETTRADE_URL.format(symbol=symbol)
    return f'<a href="{url}" target="_blank" style="color:#8be9fd;text-decoration:none;font-weight:bold;">{symbol} ↗</a>'


# ── Sidebar: navigation ────────────────────────────────────────────────────────
with st.sidebar:
    st.title("📈 SetseekerBot")
    page = st.radio("Navigation",
                    ["🔴 Live Trading", "🧪 Backtest", "🛡️ Risk Management", "⚙️ Settings"],
                    label_visibility="collapsed")

    st.divider()
    state = state_store.load()
    mode = state.get("mode", "paper").upper()
    running = state.get("running", False)
    st.markdown(f"**Bot status:** {'🟢 Running' if running else '🔴 Stopped'}")
    st.markdown(f"**Mode:** `{mode}`")
    last_updated = state.get("last_updated")
    if last_updated:
        try:
            lu = datetime.fromisoformat(last_updated)
            st.markdown(f"**Updated:** {lu.strftime('%H:%M:%S')}")
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# LIVE TRADING PAGE
# ═══════════════════════════════════════════════════════════════════════════════
def render_live():
    # Auto-refresh ONLY on live page
    st.markdown('<meta http-equiv="refresh" content="10">', unsafe_allow_html=True)
    st.header("Live Trading")

    initial_capital = state.get("initial_capital", 0.0)
    cash = state.get("cash", 0.0)
    daily_pnl = state.get("daily_pnl", 0.0)
    daily_trades = state.get("daily_trades", 0)
    positions = state.get("positions", {})
    closed_trades = state.get("closed_trades", [])

    unrealized_total = sum(p.get("unrealized_pnl", 0.0) for p in positions.values())
    positions_value = sum(
        p.get("quantity", 0) * p.get("current_price", p.get("entry_price", 0))
        for p in positions.values()
    )
    total_equity = cash + positions_value
    total_return_pct = (
        (total_equity - initial_capital) / initial_capital * 100
        if initial_capital > 0 else 0.0
    )
    wins = [t for t in closed_trades if t.get("pnl", 0) > 0]
    win_rate = len(wins) / len(closed_trades) * 100 if closed_trades else 0.0
    realized_pnl = sum(t.get("pnl", 0) for t in closed_trades)

    # KPI row
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Total Equity", _fmt_thb(total_equity), f"{total_return_pct:+.2f}%")
    c2.metric("Cash", _fmt_thb(cash))
    c3.metric("Daily P&L", _fmt_thb(daily_pnl))
    c4.metric("Unrealized P&L", _fmt_thb(unrealized_total))
    c5.metric("Trades Today", str(daily_trades))
    c6.metric("Win Rate", f"{win_rate:.1f}%", f"{len(wins)}/{len(closed_trades)}")

    st.divider()

    # Equity curve + trade bars
    left, right = st.columns([3, 1])

    with left:
        st.subheader("Equity Curve")
        equity_history = state.get("equity_history", [])
        if equity_history:
            times = [row[0] for row in equity_history]
            values = [row[1] for row in equity_history]
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=times, y=values, mode="lines",
                line=dict(color="#50fa7b", width=2),
                fill="tozeroy", fillcolor="rgba(80,250,123,0.07)",
            ))
            if initial_capital:
                fig.add_hline(y=initial_capital, line_dash="dash",
                              line_color="#6272a4", annotation_text="Initial")
            fig.update_layout(template="plotly_dark", height=320,
                              margin=dict(l=0, r=0, t=10, b=0), showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No equity history yet.")

    with right:
        st.subheader("Trade P&L")
        if closed_trades:
            recent = closed_trades[-20:]
            pnls = [t.get("pnl", 0) for t in recent]
            syms = [t.get("symbol", "") for t in recent]
            colors = ["#50fa7b" if p > 0 else "#ff5555" for p in pnls]
            fig2 = go.Figure(go.Bar(x=list(range(len(pnls))), y=pnls,
                                    marker_color=colors, text=syms))
            fig2.update_layout(template="plotly_dark", height=320,
                               margin=dict(l=0, r=0, t=10, b=0),
                               xaxis=dict(showticklabels=False), showlegend=False)
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("No trades yet.")

    st.divider()
    st.subheader(f"Open Positions ({len(positions)})")
    if positions:
        pos_html = "<table style='width:100%;border-collapse:collapse;'>"
        pos_html += ("<tr style='border-bottom:1px solid #444;'>"
                     "<th style='text-align:left;padding:6px;'>Symbol</th>"
                     "<th>Qty</th><th>Entry ฿</th><th>Current ฿</th>"
                     "<th>P&L</th><th>P&L %</th><th>SL</th><th>TP</th>"
                     "<th>Strategy</th></tr>")
        for sym, pos in positions.items():
            entry = pos.get("entry_price", 0)
            current = pos.get("current_price", entry)
            upnl = pos.get("unrealized_pnl", 0)
            pnl_pct = (current - entry) / entry * 100 if entry else 0
            pnl_color = "#50fa7b" if upnl >= 0 else "#ff5555"
            pos_html += (
                f"<tr style='border-bottom:1px solid #333;'>"
                f"<td style='padding:6px;'>{_sym_link(sym)}</td>"
                f"<td style='text-align:right;'>{pos.get('quantity', 0):,}</td>"
                f"<td style='text-align:right;'>{entry:.2f}</td>"
                f"<td style='text-align:right;'>{current:.2f}</td>"
                f"<td style='text-align:right;color:{pnl_color};'>฿{upnl:,.2f}</td>"
                f"<td style='text-align:right;color:{pnl_color};'>{pnl_pct:+.2f}%</td>"
                f"<td style='text-align:right;'>{pos.get('stop_loss', 0):.2f}</td>"
                f"<td style='text-align:right;'>{pos.get('take_profit', 0):.2f}</td>"
                f"<td>{pos.get('strategy', '')}</td></tr>"
            )
        pos_html += "</table>"
        st.markdown(pos_html, unsafe_allow_html=True)
    else:
        st.info("No open positions.")

    st.divider()
    col_hist, col_signals = st.columns([3, 2])
    with col_hist:
        st.subheader("Recent Closed Trades")
        if closed_trades:
            recent = closed_trades[::-1][:50]
            ct_html = "<table style='width:100%;border-collapse:collapse;font-size:0.9em;'>"
            ct_html += ("<tr style='border-bottom:1px solid #444;'>"
                        "<th style='text-align:left;padding:4px;'>Symbol</th>"
                        "<th>Exit ฿</th><th>Qty</th><th>P&L</th>"
                        "<th>P&L %</th><th>Strategy</th><th>Time</th></tr>")
            for t in recent:
                pnl = t.get("pnl", 0)
                pnl_color = "#50fa7b" if pnl >= 0 else "#ff5555"
                sym = t.get("symbol", "")
                exit_time = t.get("exit_time", "")
                if isinstance(exit_time, str) and len(exit_time) > 16:
                    exit_time = exit_time[:16]
                ct_html += (
                    f"<tr style='border-bottom:1px solid #333;'>"
                    f"<td style='padding:4px;'>{_sym_link(sym)}</td>"
                    f"<td style='text-align:right;'>{t.get('exit_price', 0):.2f}</td>"
                    f"<td style='text-align:right;'>{t.get('quantity', 0):,}</td>"
                    f"<td style='text-align:right;color:{pnl_color};'>฿{pnl:,.2f}</td>"
                    f"<td style='text-align:right;color:{pnl_color};'>{t.get('pnl_pct', 0):+.2f}%</td>"
                    f"<td>{t.get('strategy', '')}</td>"
                    f"<td>{exit_time}</td></tr>"
                )
            ct_html += "</table>"
            st.markdown(ct_html, unsafe_allow_html=True)
        else:
            st.info("No closed trades yet.")

    with col_signals:
        st.subheader("Recent Signals")
        signals_log = state.get("signals_log", [])
        if signals_log:
            sig_html = "<table style='width:100%;border-collapse:collapse;font-size:0.9em;'>"
            sig_html += ("<tr style='border-bottom:1px solid #444;'>"
                         "<th style='text-align:left;padding:4px;'>Time</th>"
                         "<th>Symbol</th><th>Type</th>"
                         "<th>Price</th><th>Str</th><th>Reason</th></tr>")
            for s in signals_log[::-1]:
                sym = s.get("symbol", "")
                sig_type = s.get("type", "")
                type_color = "#50fa7b" if sig_type == "BUY" else "#ff5555"
                sig_time = s.get("time", "")
                if isinstance(sig_time, str) and len(sig_time) > 19:
                    sig_time = sig_time[11:19]
                sig_html += (
                    f"<tr style='border-bottom:1px solid #333;'>"
                    f"<td style='padding:4px;'>{sig_time}</td>"
                    f"<td>{_sym_link(sym)}</td>"
                    f"<td style='color:{type_color};font-weight:bold;'>{sig_type}</td>"
                    f"<td style='text-align:right;'>฿{s.get('price', 0):.2f}</td>"
                    f"<td style='text-align:right;'>{s.get('strength', 0):.2f}</td>"
                    f"<td style='font-size:0.85em;'>{s.get('reason', '')[:60]}</td></tr>"
                )
            sig_html += "</table>"
            st.markdown(sig_html, unsafe_allow_html=True)
        else:
            st.info("No signals yet.")


# ═══════════════════════════════════════════════════════════════════════════════
# BACKTEST PAGE
# ═══════════════════════════════════════════════════════════════════════════════
_DEFAULT_WATCHLIST = [
    "AOT", "ADVANC", "AWC", "BBL", "BDMS", "BEM", "BH", "CPALL", "CPF",
    "CPN", "DELTA", "EA", "GULF", "HMPRO", "KBANK", "KTB", "MINT", "OR",
    "PTT", "PTTEP", "SCB", "SCC", "SCGP", "TISCO", "TOP", "TRUE", "TTB", "TU",
]

_STRATEGY_MAP = {
    "Composite (all signals)": "composite",
    "Momentum (RSI + MACD)": "momentum",
    "Mean Reversion (BB + RSI)": "mean_reversion",
    "Breakout (Range + Volume)": "breakout",
    "VWAP Deviation": "vwap",
}


def _build_strategy(name: str, cfg: StrategyConfig):
    if name == "composite":
        return CompositeStrategy(cfg)
    if name == "momentum":
        return MomentumStrategy(
            rsi_period=cfg.momentum_rsi_period,
            rsi_oversold=cfg.momentum_rsi_oversold,
            rsi_overbought=cfg.momentum_rsi_overbought,
            macd_fast=cfg.momentum_macd_fast,
            macd_slow=cfg.momentum_macd_slow,
            macd_signal=cfg.momentum_macd_signal,
        )
    if name == "mean_reversion":
        return MeanReversionStrategy(
            bb_period=cfg.mean_rev_bb_period,
            bb_std=cfg.mean_rev_bb_std,
            lookback=cfg.mean_rev_lookback,
        )
    if name == "breakout":
        return BreakoutStrategy(
            lookback=cfg.breakout_lookback,
            volume_mult=cfg.breakout_volume_mult,
            atr_period=cfg.breakout_atr_period,
        )
    if name == "vwap":
        return VWAPStrategy(
            deviation_entry=cfg.vwap_deviation_entry,
            deviation_exit=cfg.vwap_deviation_exit,
        )
    return CompositeStrategy(cfg)


@st.cache_data(show_spinner=False)
def _load_data(symbol: str, data_source: str, bars: int,
               base_price: float, volatility: float) -> pd.DataFrame:
    settings = Settings.load()
    fetcher = MarketDataFetcher(settings)
    if data_source == "simulated":
        return fetcher.generate_simulated_data(
            symbol, bars=bars, base_price=base_price, volatility=volatility,
        )
    df = fetcher.get_historical_daily(symbol, days=max(bars // 5, 30))
    if df.empty:
        return fetcher.generate_simulated_data(
            symbol, bars=bars, base_price=base_price, volatility=volatility,
        )
    return df


def _plot_backtest(result: BacktestResult, df: pd.DataFrame):
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05,
        row_heights=[0.7, 0.3],
        subplot_titles=("Price & Trades", "Portfolio Equity"),
    )

    # Price candles
    fig.add_trace(
        go.Candlestick(
            x=df.index, open=df["open"], high=df["high"],
            low=df["low"], close=df["close"],
            increasing_line_color="#50fa7b", decreasing_line_color="#ff5555",
            name="Price", showlegend=False,
        ),
        row=1, col=1,
    )

    # Trade markers
    for t in result.trades:
        entry_idx = t["entry_bar"]
        exit_idx = t["exit_bar"]
        if entry_idx < len(df) and exit_idx < len(df):
            entry_time = df.index[entry_idx]
            exit_time = df.index[exit_idx]
            pnl_color = "#50fa7b" if t["pnl"] > 0 else "#ff5555"
            fig.add_trace(
                go.Scatter(
                    x=[entry_time], y=[t["entry_price"]],
                    mode="markers", marker=dict(symbol="triangle-up",
                                                size=12, color="#8be9fd"),
                    name="Entry", showlegend=False,
                    hovertext=f"BUY @ ฿{t['entry_price']:.2f}",
                ),
                row=1, col=1,
            )
            fig.add_trace(
                go.Scatter(
                    x=[exit_time], y=[t["exit_price"]],
                    mode="markers", marker=dict(symbol="triangle-down",
                                                size=12, color=pnl_color),
                    name="Exit", showlegend=False,
                    hovertext=f"SELL @ ฿{t['exit_price']:.2f} | P&L: ฿{t['pnl']:,.2f}",
                ),
                row=1, col=1,
            )

    # Equity curve
    if result.equity_curve:
        eq_times = df.index[-len(result.equity_curve):]
        fig.add_trace(
            go.Scatter(
                x=eq_times, y=result.equity_curve, mode="lines",
                line=dict(color="#bd93f9", width=2),
                fill="tozeroy", fillcolor="rgba(189,147,249,0.08)",
                name="Equity", showlegend=False,
            ),
            row=2, col=1,
        )
        fig.add_hline(
            y=result.initial_capital, line_dash="dash",
            line_color="#6272a4", row=2, col=1,
        )

    fig.update_layout(
        template="plotly_dark", height=620,
        margin=dict(l=0, r=0, t=40, b=0),
        xaxis_rangeslider_visible=False,
    )
    return fig


def render_backtest():
    st.header("🧪 Backtest")

    # ── Config form ──────────────────────────────────────────────────────
    with st.form("backtest_form", clear_on_submit=False):
        cfg_col1, cfg_col2, cfg_col3 = st.columns(3)
        with cfg_col1:
            symbol = st.selectbox(
                "Symbol", _DEFAULT_WATCHLIST, index=0,
                help="SET stock to backtest",
            )
            strategy_label = st.selectbox(
                "Strategy", list(_STRATEGY_MAP.keys()), index=0,
            )
        with cfg_col2:
            initial_capital = st.number_input(
                "Initial Capital (฿)", min_value=10_000.0,
                max_value=100_000_000.0, value=1_000_000.0, step=100_000.0,
            )
            bars = st.slider("Bars", min_value=100, max_value=1000, value=400, step=50)
        with cfg_col3:
            data_source = st.radio("Data source", ["simulated", "api"], index=0,
                                   help="API needs Settrade credentials")
            base_price = st.number_input("Base Price (฿) [sim only]",
                                         min_value=1.0, value=100.0)
            volatility = st.slider("Volatility [sim only]",
                                   min_value=0.005, max_value=0.08,
                                   value=0.02, step=0.005)

        with st.expander("⚙️ Advanced Strategy Parameters"):
            acol1, acol2, acol3 = st.columns(3)
            with acol1:
                rsi_period = st.number_input("RSI Period", 5, 30, 14)
                rsi_oversold = st.number_input("RSI Oversold", 10.0, 50.0, 30.0)
                rsi_overbought = st.number_input("RSI Overbought", 50.0, 90.0, 70.0)
            with acol2:
                bb_period = st.number_input("BB Period", 10, 50, 20)
                bb_std = st.number_input("BB Std Dev", 1.0, 4.0, 2.0, step=0.1)
                breakout_lookback = st.number_input("Breakout Lookback", 5, 50, 20)
            with acol3:
                vwap_dev = st.number_input("VWAP Deviation", 0.5, 4.0, 1.5, step=0.1)
                min_signals = st.number_input("Min Signals (Composite)", 1, 4, 2)
                volume_mult = st.number_input("Volume Multiplier", 1.0, 3.0, 1.5, step=0.1)

        submitted = st.form_submit_button("▶️ Run Backtest", type="primary",
                                          use_container_width=True)

    if not submitted:
        st.info("Configure parameters above and click **Run Backtest**.")
        return

    # ── Execute backtest ─────────────────────────────────────────────────
    cfg = StrategyConfig()
    cfg.momentum_rsi_period = int(rsi_period)
    cfg.momentum_rsi_oversold = float(rsi_oversold)
    cfg.momentum_rsi_overbought = float(rsi_overbought)
    cfg.mean_rev_bb_period = int(bb_period)
    cfg.mean_rev_bb_std = float(bb_std)
    cfg.breakout_lookback = int(breakout_lookback)
    cfg.breakout_volume_mult = float(volume_mult)
    cfg.vwap_deviation_entry = float(vwap_dev)
    cfg.min_signals_required = int(min_signals)

    with st.spinner(f"Running backtest on {symbol}..."):
        settings = Settings.load()
        settings.trading.initial_capital = float(initial_capital)

        df = _load_data(symbol, data_source, int(bars),
                        float(base_price), float(volatility))
        if df.empty:
            st.error("Failed to load data.")
            return

        strategy_name = _STRATEGY_MAP[strategy_label]
        strategy = _build_strategy(strategy_name, cfg)
        engine = BacktestEngine(settings)
        result = engine.run(df, strategy, symbol=symbol,
                            initial_capital=float(initial_capital))

    # ── Results: KPI cards ───────────────────────────────────────────────
    st.success(f"Backtest complete: **{symbol}** / {strategy_label}")

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Total Return", f"{result.total_return_pct:+.2f}%",
              _fmt_thb(result.total_return))
    k2.metric("Sharpe Ratio", f"{result.sharpe_ratio:.2f}")
    k3.metric("Max Drawdown", f"{result.max_drawdown:.2f}%")
    pf_str = (f"{result.profit_factor:.2f}"
              if result.profit_factor != float("inf") else "∞")
    k4.metric("Profit Factor", pf_str)
    k5.metric("Win Rate", f"{result.win_rate:.1f}%",
              f"{result.winning_trades}W / {result.losing_trades}L")
    k6.metric("Total Trades", str(result.total_trades))

    k7, k8, k9, k10 = st.columns(4)
    k7.metric("Final Capital", _fmt_thb(result.final_capital))
    k8.metric("Avg Win", _fmt_thb(result.avg_win))
    k9.metric("Avg Loss", _fmt_thb(result.avg_loss))
    k10.metric("Avg Hold (bars)", f"{result.avg_holding_bars:.1f}")

    st.divider()

    # ── Chart ────────────────────────────────────────────────────────────
    st.plotly_chart(_plot_backtest(result, df), use_container_width=True)

    # ── Trade table ──────────────────────────────────────────────────────
    st.subheader("Trade Log")
    if result.trades:
        df_tr = pd.DataFrame(result.trades)
        df_tr["entry_time"] = df.index[df_tr["entry_bar"]].astype(str)
        df_tr["exit_time"] = df.index[df_tr["exit_bar"]].astype(str)
        df_tr = df_tr[["entry_time", "exit_time", "entry_price", "exit_price",
                       "quantity", "pnl", "pnl_pct", "holding_bars",
                       "exit_reason", "commission"]]
        st.dataframe(
            df_tr.style.format({
                "entry_price": "฿{:.2f}", "exit_price": "฿{:.2f}",
                "quantity": "{:,}", "pnl": "฿{:,.2f}", "pnl_pct": "{:+.2f}%",
                "commission": "฿{:,.2f}",
            }),
            use_container_width=True, hide_index=True, height=400,
        )

        # CSV export
        csv = df_tr.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download Trades CSV", csv,
            file_name=f"backtest_{symbol}_{strategy_name}.csv",
            mime="text/csv",
        )
    else:
        st.warning("No trades generated — try different parameters or a longer period.")


# ═══════════════════════════════════════════════════════════════════════════════
# RISK MANAGEMENT PAGE
# ═══════════════════════════════════════════════════════════════════════════════
def _limit_bar(label: str, used_pct: float, limit_desc: str):
    """Render a colored progress bar for a risk limit."""
    if used_pct >= 100:
        color = "#ff5555"      # Red — breached
        status = "⚠️ BREACHED"
    elif used_pct >= 75:
        color = "#ffb86c"      # Orange — warning
        status = "⚡ Warning"
    elif used_pct >= 50:
        color = "#f1fa8c"      # Yellow — caution
        status = "Caution"
    else:
        color = "#50fa7b"      # Green — safe
        status = "✓ Safe"

    pct_display = min(used_pct, 100)
    st.markdown(
        f"""
        <div style="margin-bottom: 16px;">
          <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
            <span><b>{label}</b> <span style="color: #888; font-size: 0.85em;">({limit_desc})</span></span>
            <span style="color: {color};">{used_pct:.1f}% — {status}</span>
          </div>
          <div style="background: #282a36; border-radius: 4px; height: 10px; overflow: hidden;">
            <div style="width: {pct_display}%; height: 100%; background: {color};
                        transition: width 0.3s ease;"></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_risk():
    st.header("🛡️ Risk Management")

    settings = Settings.load()

    # Allow user overrides via session state
    if "risk_overrides" not in st.session_state:
        st.session_state.risk_overrides = {
            "max_position_pct": settings.risk.max_position_pct,
            "max_daily_loss_pct": settings.risk.max_daily_loss_pct,
            "max_open_positions": settings.risk.max_open_positions,
            "max_drawdown_pct": settings.risk.max_drawdown_pct,
            "stop_loss_pct": settings.risk.stop_loss_pct,
            "take_profit_pct": settings.risk.take_profit_pct,
            "trailing_stop_pct": settings.risk.trailing_stop_pct,
            "sizing_method": settings.risk.position_size_method,
        }
    r = st.session_state.risk_overrides

    summary = risk_metrics.compute_risk_summary(
        state,
        initial_capital=state.get("initial_capital", settings.trading.initial_capital),
        max_daily_loss_pct=r["max_daily_loss_pct"],
        max_drawdown_pct=r["max_drawdown_pct"],
        max_position_pct=r["max_position_pct"],
        max_open_positions=r["max_open_positions"],
    )

    # ── KPI Row ──────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Total Equity", _fmt_thb(summary["total_equity"]))
    k2.metric("Current Drawdown",
              f"{summary['current_drawdown_pct']:.2f}%",
              f"Max: {summary['max_drawdown_pct']:.2f}%",
              delta_color="inverse")
    k3.metric("VaR (95%)",
              f"{summary['var_95']:.2f}%",
              _fmt_thb(summary['var_95_amount']),
              delta_color="inverse")
    k4.metric("CVaR (95%)", f"{summary['cvar_95']:.2f}%", delta_color="inverse")
    k5.metric("Total Risk",
              _fmt_thb(summary["total_risk_amount"]),
              f"{summary['total_risk_pct']:.2f}% of equity")
    k6.metric("Risk of Ruin",
              f"{summary['risk_of_ruin_pct']:.2f}%",
              "at 1% risk/trade",
              delta_color="inverse")

    st.divider()

    # ── Risk Limits Utilization ─────────────────────────────────────────
    col_limits, col_concentration = st.columns([3, 2])

    with col_limits:
        st.subheader("Risk Limits — Utilization")
        _limit_bar(
            "Daily Loss",
            summary["daily_loss_used_pct"],
            f"Limit: {_fmt_thb(summary['daily_loss_limit'])} "
            f"| Used: {_fmt_thb(max(0, -summary['daily_pnl']))}",
        )
        _limit_bar(
            "Drawdown",
            summary["drawdown_used_pct"],
            f"Limit: {r['max_drawdown_pct'] * 100:.1f}% "
            f"| Current: {summary['current_drawdown_pct']:.2f}%",
        )
        _limit_bar(
            "Open Positions",
            summary["positions_used_pct"],
            f"Limit: {r['max_open_positions']} "
            f"| Current: {summary['num_positions']}",
        )
        _limit_bar(
            "Largest Position",
            summary["largest_position_pct"] / (r["max_position_pct"] * 100) * 100
            if r["max_position_pct"] > 0 else 0,
            f"Limit: {r['max_position_pct'] * 100:.1f}% "
            f"| Largest: {summary['largest_position_pct']:.1f}%",
        )

    with col_concentration:
        st.subheader("Position Concentration")
        if summary["concentration"]:
            labels = [r["symbol"] for r in summary["concentration"]]
            weights = [r["weight_pct"] for r in summary["concentration"]]
            cash_weight = (summary["cash"] / summary["total_equity"] * 100
                           if summary["total_equity"] > 0 else 100)
            labels.append("Cash")
            weights.append(cash_weight)
            colors = ["#ff5555", "#ff79c6", "#bd93f9", "#8be9fd",
                      "#50fa7b", "#f1fa8c", "#ffb86c"] * 3
            fig = go.Figure(go.Pie(
                labels=labels, values=weights, hole=0.55,
                marker_colors=colors[:len(labels)],
                textinfo="label+percent",
            ))
            fig.update_layout(template="plotly_dark", height=320,
                              margin=dict(l=0, r=0, t=0, b=0),
                              showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No open positions.")

    st.divider()

    # ── Drawdown chart ──────────────────────────────────────────────────
    st.subheader("Drawdown History")
    if summary["drawdown_series"] and summary["equity_timestamps"]:
        fig_dd = go.Figure()
        fig_dd.add_trace(go.Scatter(
            x=summary["equity_timestamps"],
            y=[-d for d in summary["drawdown_series"]],
            mode="lines",
            line=dict(color="#ff5555", width=2),
            fill="tozeroy",
            fillcolor="rgba(255,85,85,0.15)",
            name="Drawdown %",
        ))
        fig_dd.add_hline(
            y=-r["max_drawdown_pct"] * 100,
            line_dash="dash", line_color="#ff5555",
            annotation_text=f"Limit: -{r['max_drawdown_pct'] * 100:.1f}%",
        )
        fig_dd.update_layout(
            template="plotly_dark", height=260,
            margin=dict(l=0, r=0, t=10, b=0),
            yaxis_title="Drawdown %",
            xaxis_title=None, showlegend=False,
        )
        st.plotly_chart(fig_dd, use_container_width=True)
    else:
        st.info("Drawdown chart will appear once equity history is populated.")

    st.divider()

    # ── Position risk table ─────────────────────────────────────────────
    st.subheader("Per-Position Risk Breakdown")
    if summary["concentration"]:
        risk_html = "<table style='width:100%;border-collapse:collapse;'>"
        risk_html += ("<tr style='border-bottom:1px solid #444;'>"
                      "<th style='text-align:left;padding:6px;'>Symbol</th>"
                      "<th>Side</th><th>Market Value</th><th>Weight %</th>"
                      "<th>Unreal P&L</th><th>Risk to Stop</th></tr>")
        for r_item in summary["concentration"]:
            sym = r_item["symbol"]
            upnl = r_item["unrealized_pnl"]
            pnl_color = "#50fa7b" if upnl >= 0 else "#ff5555"
            risk_html += (
                f"<tr style='border-bottom:1px solid #333;'>"
                f"<td style='padding:6px;'>{_sym_link(sym)}</td>"
                f"<td>{r_item['side']}</td>"
                f"<td style='text-align:right;'>฿{r_item['market_value']:,.2f}</td>"
                f"<td style='text-align:right;'>{r_item['weight_pct']:.2f}%</td>"
                f"<td style='text-align:right;color:{pnl_color};'>฿{upnl:,.2f}</td>"
                f"<td style='text-align:right;'>฿{r_item['risk_amount']:,.2f}</td></tr>"
            )
        risk_html += "</table>"
        st.markdown(risk_html, unsafe_allow_html=True)
    else:
        st.info("No open positions to analyze.")

    st.divider()

    # ── Pre-Trade Risk Calculator ───────────────────────────────────────
    st.subheader("🧮 Pre-Trade Risk Calculator")
    st.caption("Evaluate position size & risk before entering a trade.")

    with st.form("risk_calc"):
        calc_col1, calc_col2, calc_col3 = st.columns(3)
        with calc_col1:
            calc_symbol = st.text_input("Symbol", value="ADVANC")
            calc_entry = st.number_input("Entry Price (฿)",
                                         min_value=0.01, value=250.0, step=0.5)
            calc_stop = st.number_input("Stop Loss (฿)",
                                        min_value=0.0, value=245.0, step=0.5)
        with calc_col2:
            calc_target = st.number_input("Take Profit (฿)",
                                          min_value=0.0, value=260.0, step=0.5)
            calc_equity = st.number_input(
                "Account Equity (฿)", min_value=10_000.0,
                value=float(summary["total_equity"])
                if summary["total_equity"] > 0 else 1_000_000.0,
                step=10_000.0,
            )
            calc_risk_pct = st.slider("Risk per Trade (%)",
                                      min_value=0.25, max_value=5.0,
                                      value=1.0, step=0.25)
        with calc_col3:
            calc_win_prob = st.slider("Win Probability (%)",
                                      min_value=30.0, max_value=80.0,
                                      value=55.0, step=2.5)
            calc_method = st.radio("Sizing Method",
                                   ["Fixed %", "Kelly (half)", "Volatility"])
            calc_side = st.radio("Side", ["BUY (long)", "SELL (short)"])

        calc_submitted = st.form_submit_button("📊 Calculate", type="primary",
                                               use_container_width=True)

    if calc_submitted:
        side = "BUY" if calc_side.startswith("BUY") else "SELL"
        if side == "BUY":
            risk_per_share = max(calc_entry - calc_stop, 0.0001)
            reward_per_share = max(calc_target - calc_entry, 0.0)
        else:
            risk_per_share = max(calc_stop - calc_entry, 0.0001)
            reward_per_share = max(calc_entry - calc_target, 0.0)

        rr_ratio = reward_per_share / risk_per_share if risk_per_share > 0 else 0
        risk_budget = calc_equity * calc_risk_pct / 100

        if calc_method == "Fixed %":
            shares = int(risk_budget / risk_per_share)
        elif calc_method == "Kelly (half)":
            wp = calc_win_prob / 100
            b = rr_ratio
            kelly = (b * wp - (1 - wp)) / b if b > 0 else 0
            kelly = max(0, kelly * 0.5)
            kelly_value = calc_equity * kelly
            shares = int(kelly_value / calc_entry)
        else:
            # Volatility = 2x risk_per_share as proxy
            shares = int(risk_budget / (2 * risk_per_share))

        shares = (shares // 100) * 100  # SET 100-lot
        position_value = shares * calc_entry
        position_pct = position_value / calc_equity * 100 if calc_equity else 0
        total_risk = shares * risk_per_share
        total_reward = shares * reward_per_share
        commission = calculate_commission(position_value * 2)

        expected_value = (
            (calc_win_prob / 100) * total_reward
            - (1 - calc_win_prob / 100) * total_risk
            - commission
        )

        # Checks
        alerts = []
        if position_pct > r["max_position_pct"] * 100:
            alerts.append(f"⚠️ Exceeds max position size "
                          f"({r['max_position_pct'] * 100:.1f}%)")
        if rr_ratio < 1.5:
            alerts.append(f"⚠️ Risk/reward ratio too low ({rr_ratio:.2f} < 1.5)")
        if risk_per_share == 0.0001:
            alerts.append("⚠️ Stop-loss is at or beyond entry price")
        if shares <= 0:
            alerts.append("⚠️ Position size too small (< 100 shares)")

        # Output
        st.markdown("### Results")
        rc1, rc2, rc3, rc4 = st.columns(4)
        rc1.metric("Recommended Shares", f"{shares:,}")
        rc2.metric("Position Value", _fmt_thb(position_value),
                   f"{position_pct:.2f}% of equity")
        rc3.metric("Total Risk", _fmt_thb(total_risk))
        rc4.metric("R/R Ratio", f"{rr_ratio:.2f}")

        rc5, rc6, rc7, rc8 = st.columns(4)
        rc5.metric("Potential Reward", _fmt_thb(total_reward))
        rc6.metric("Expected Value", _fmt_thb(expected_value),
                   delta_color="normal")
        rc7.metric("Round-trip Commission", _fmt_thb(commission))
        rc8.metric("Risk/Share", _fmt_thb(risk_per_share))

        if alerts:
            for a in alerts:
                st.warning(a)
        else:
            st.success("✅ Trade passes all risk checks.")

    st.divider()

    # ── Risk Limits Editor ──────────────────────────────────────────────
    st.subheader("⚙️ Risk Limits Editor")
    st.caption("Changes apply to this dashboard session. Edit `config/settings.py` for persistence.")

    with st.form("risk_limits_editor"):
        e1, e2, e3 = st.columns(3)
        with e1:
            new_max_pos = st.slider("Max Position %", 1.0, 50.0,
                                    r["max_position_pct"] * 100, 1.0) / 100
            new_max_daily = st.slider("Max Daily Loss %", 0.5, 10.0,
                                      r["max_daily_loss_pct"] * 100, 0.25) / 100
        with e2:
            new_max_dd = st.slider("Max Drawdown %", 1.0, 30.0,
                                   r["max_drawdown_pct"] * 100, 0.5) / 100
            new_max_openp = st.slider("Max Open Positions", 1, 20,
                                      r["max_open_positions"], 1)
        with e3:
            new_sl = st.slider("Default Stop Loss %", 0.5, 10.0,
                               r["stop_loss_pct"] * 100, 0.25) / 100
            new_tp = st.slider("Default Take Profit %", 0.5, 20.0,
                               r["take_profit_pct"] * 100, 0.25) / 100

        if st.form_submit_button("💾 Save Overrides", type="primary"):
            st.session_state.risk_overrides.update({
                "max_position_pct": new_max_pos,
                "max_daily_loss_pct": new_max_daily,
                "max_drawdown_pct": new_max_dd,
                "max_open_positions": int(new_max_openp),
                "stop_loss_pct": new_sl,
                "take_profit_pct": new_tp,
            })
            st.success("Risk limits updated for this session.")
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# SETTINGS PAGE
# ═══════════════════════════════════════════════════════════════════════════════
def render_settings():
    st.header("⚙️ Settings")
    settings = Settings.load()

    st.subheader("Trading")
    c1, c2 = st.columns(2)
    c1.metric("Initial Capital", _fmt_thb(settings.trading.initial_capital))
    c1.metric("Primary Timeframe", settings.trading.primary_timeframe)
    c1.metric("Commission Rate", f"{settings.trading.commission_rate * 100:.4f}%")
    c2.metric("Market Open", settings.trading.market_open)
    c2.metric("Market Close", settings.trading.market_close)
    c2.metric("Slippage (bps)", f"{settings.trading.slippage_bps}")

    st.subheader("Risk")
    r1, r2 = st.columns(2)
    r1.metric("Max Position %", f"{settings.risk.max_position_pct * 100:.1f}%")
    r1.metric("Max Daily Loss %", f"{settings.risk.max_daily_loss_pct * 100:.1f}%")
    r1.metric("Max Open Positions", str(settings.risk.max_open_positions))
    r2.metric("Stop Loss %", f"{settings.risk.stop_loss_pct * 100:.1f}%")
    r2.metric("Take Profit %", f"{settings.risk.take_profit_pct * 100:.1f}%")
    r2.metric("Sizing Method", settings.risk.position_size_method)

    st.subheader("Watchlist")
    wl_cols = st.columns(6)
    for i, sym in enumerate(settings.trading.watchlist):
        wl_cols[i % 6].markdown(_sym_link(sym), unsafe_allow_html=True)

    st.info("Edit `config/settings.py` or `.env` to change these values.")


# ── Route to page ──────────────────────────────────────────────────────────────
if page.startswith("🔴"):
    render_live()
elif page.startswith("🧪"):
    render_backtest()
elif page.startswith("🛡️"):
    render_risk()
else:
    render_settings()
