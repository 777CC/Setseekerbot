"""
SetseekerBot — Live Dashboard
Run with:  streamlit run dashboard.py

Reads from data/bot_state.json written by the trading bot.
Auto-refreshes every 10 seconds.
"""

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils import state_store

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SetseekerBot Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Auto-refresh ───────────────────────────────────────────────────────────────
REFRESH_SECS = 10
st.markdown(
    f"""
    <meta http-equiv="refresh" content="{REFRESH_SECS}">
    <style>
        .metric-card {{
            background: #1e1e2e;
            border-radius: 10px;
            padding: 16px 20px;
            margin-bottom: 8px;
        }}
        .pos-pnl  {{ color: #50fa7b; font-weight: bold; }}
        .neg-pnl  {{ color: #ff5555; font-weight: bold; }}
        .neutral  {{ color: #f8f8f2; }}
        div[data-testid="stMetricValue"] > div {{ font-size: 1.6rem; }}
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Load state ─────────────────────────────────────────────────────────────────
state = state_store.load()


def _fmt_thb(v: float) -> str:
    return f"฿{v:,.2f}"


def _pnl_color(v: float) -> str:
    return "pos-pnl" if v >= 0 else "neg-pnl"


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("📈 SetseekerBot")
    mode = state.get("mode", "paper").upper()
    running = state.get("running", False)

    status_icon = "🟢 Running" if running else "🔴 Stopped"
    st.markdown(f"**Status:** {status_icon}")
    st.markdown(f"**Mode:** `{mode}`")

    last_updated = state.get("last_updated")
    if last_updated:
        try:
            lu = datetime.fromisoformat(last_updated)
            st.markdown(f"**Updated:** {lu.strftime('%H:%M:%S')}")
        except Exception:
            pass

    st.divider()
    st.caption(f"Auto-refresh every {REFRESH_SECS}s")
    if st.button("🔄 Refresh now"):
        st.rerun()

# ── Top KPI row ────────────────────────────────────────────────────────────────
initial_capital = state.get("initial_capital", 0.0)
cash = state.get("cash", 0.0)
daily_pnl = state.get("daily_pnl", 0.0)
daily_trades = state.get("daily_trades", 0)
positions = state.get("positions", {})
closed_trades = state.get("closed_trades", [])

# Calculate total equity (cash + unrealized)
unrealized_total = sum(
    p.get("unrealized_pnl", 0.0) for p in positions.values()
)
total_equity = cash + sum(
    p.get("quantity", 0) * p.get("current_price", p.get("entry_price", 0))
    for p in positions.values()
)

total_return_pct = (
    (total_equity - initial_capital) / initial_capital * 100
    if initial_capital > 0 else 0.0
)

# Win rate from closed trades
wins = [t for t in closed_trades if t.get("pnl", 0) > 0]
win_rate = len(wins) / len(closed_trades) * 100 if closed_trades else 0.0
realized_pnl = sum(t.get("pnl", 0) for t in closed_trades)

st.subheader("Portfolio Overview")
col1, col2, col3, col4, col5, col6 = st.columns(6)

col1.metric("Total Equity", _fmt_thb(total_equity),
            f"{total_return_pct:+.2f}%")
col2.metric("Cash", _fmt_thb(cash))
col3.metric("Daily P&L", _fmt_thb(daily_pnl),
            f"{daily_pnl / initial_capital * 100:+.2f}%" if initial_capital else None,
            delta_color="normal")
col4.metric("Unrealized P&L", _fmt_thb(unrealized_total),
            delta_color="normal")
col5.metric("Trades Today", str(daily_trades))
col6.metric("Win Rate", f"{win_rate:.1f}%",
            f"{len(wins)}/{len(closed_trades)} trades")

st.divider()

# ── Equity Curve ───────────────────────────────────────────────────────────────
equity_history = state.get("equity_history", [])

left, right = st.columns([3, 1])

with left:
    st.subheader("Equity Curve")
    if equity_history:
        times = [row[0] for row in equity_history]
        values = [row[1] for row in equity_history]

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=times, y=values,
            mode="lines",
            name="Portfolio Value",
            line=dict(color="#50fa7b", width=2),
            fill="tozeroy",
            fillcolor="rgba(80,250,123,0.07)",
        ))
        if initial_capital:
            fig.add_hline(
                y=initial_capital,
                line_dash="dash",
                line_color="#6272a4",
                annotation_text="Initial Capital",
                annotation_position="top left",
            )
        fig.update_layout(
            template="plotly_dark",
            height=320,
            margin=dict(l=0, r=0, t=10, b=0),
            xaxis_title=None,
            yaxis_title="฿",
            showlegend=False,
            xaxis=dict(showgrid=False),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No equity history yet — start the bot to populate data.")

# ── Daily P&L bar per trade ────────────────────────────────────────────────────
with right:
    st.subheader("Trade P&L")
    if closed_trades:
        recent = closed_trades[-20:]
        pnls = [t.get("pnl", 0) for t in recent]
        symbols = [t.get("symbol", "") for t in recent]
        colors = ["#50fa7b" if p > 0 else "#ff5555" for p in pnls]

        fig2 = go.Figure(go.Bar(
            x=list(range(len(pnls))),
            y=pnls,
            marker_color=colors,
            text=symbols,
            textposition="outside",
        ))
        fig2.update_layout(
            template="plotly_dark",
            height=320,
            margin=dict(l=0, r=0, t=10, b=0),
            xaxis=dict(showticklabels=False),
            yaxis_title="฿",
            showlegend=False,
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("No closed trades yet.")

st.divider()

# ── Open Positions ─────────────────────────────────────────────────────────────
st.subheader(f"Open Positions  ({len(positions)})")

if positions:
    rows = []
    for sym, pos in positions.items():
        entry = pos.get("entry_price", 0)
        current = pos.get("current_price", entry)
        qty = pos.get("quantity", 0)
        upnl = pos.get("unrealized_pnl", 0)
        upnl_pct = (current - entry) / entry * 100 if entry else 0
        rows.append({
            "Symbol": sym,
            "Side": pos.get("side", "LONG"),
            "Qty": f"{qty:,}",
            "Entry ฿": f"{entry:.2f}",
            "Current ฿": f"{current:.2f}",
            "Unreal P&L": upnl,
            "P&L %": upnl_pct,
            "Stop ฿": f"{pos.get('stop_loss', 0):.2f}",
            "TP ฿": f"{pos.get('take_profit', 0):.2f}",
            "Strategy": pos.get("strategy", ""),
        })

    df_pos = pd.DataFrame(rows)

    def _color_pnl(val):
        if isinstance(val, float):
            color = "#50fa7b" if val >= 0 else "#ff5555"
            return f"color: {color}"
        return ""

    st.dataframe(
        df_pos.style
            .applymap(_color_pnl, subset=["Unreal P&L", "P&L %"])
            .format({"Unreal P&L": "฿{:,.2f}", "P&L %": "{:+.2f}%"}),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No open positions.")

st.divider()

# ── Trade History ──────────────────────────────────────────────────────────────
col_hist, col_signals = st.columns([3, 2])

with col_hist:
    st.subheader("Recent Closed Trades")
    if closed_trades:
        df_trades = pd.DataFrame(closed_trades[::-1][:50])  # newest first
        display_cols = ["symbol", "side", "entry_price", "exit_price",
                        "quantity", "pnl", "pnl_pct", "strategy", "reason", "exit_time"]
        df_trades = df_trades[[c for c in display_cols if c in df_trades.columns]]
        df_trades.columns = [c.replace("_", " ").title() for c in df_trades.columns]

        def _color_row(row):
            pnl_val = row.get("Pnl", row.get("P&L", 0))
            color = "rgba(80,250,123,0.08)" if pnl_val > 0 else "rgba(255,85,85,0.08)"
            return [f"background-color: {color}"] * len(row)

        st.dataframe(
            df_trades.style
                .apply(_color_row, axis=1)
                .format({"Pnl": "฿{:,.2f}", "Pnl Pct": "{:+.2f}%"}, na_action="ignore"),
            use_container_width=True,
            hide_index=True,
            height=350,
        )
    else:
        st.info("No closed trades yet.")

# ── Signals Log ────────────────────────────────────────────────────────────────
with col_signals:
    st.subheader("Recent Signals")
    signals_log = state.get("signals_log", [])
    if signals_log:
        df_sig = pd.DataFrame(signals_log[::-1])
        df_sig["time"] = pd.to_datetime(df_sig["time"]).dt.strftime("%H:%M:%S")
        df_sig.columns = [c.title() for c in df_sig.columns]

        def _sig_color(row):
            color = (
                "rgba(80,250,123,0.10)" if row.get("Type") == "BUY"
                else "rgba(255,85,85,0.10)"
            )
            return [f"background-color: {color}"] * len(row)

        st.dataframe(
            df_sig.style.apply(_sig_color, axis=1),
            use_container_width=True,
            hide_index=True,
            height=350,
        )
    else:
        st.info("No signals logged yet.")

st.divider()

# ── Performance Stats ──────────────────────────────────────────────────────────
st.subheader("Performance Statistics")

if closed_trades:
    losses_list = [t for t in closed_trades if t.get("pnl", 0) <= 0]
    gross_profit = sum(t.get("pnl", 0) for t in wins)
    gross_loss = abs(sum(t.get("pnl", 0) for t in losses_list))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    avg_win = gross_profit / len(wins) if wins else 0
    avg_loss = gross_loss / len(losses_list) if losses_list else 0
    largest_win = max((t.get("pnl", 0) for t in wins), default=0)
    largest_loss = min((t.get("pnl", 0) for t in losses_list), default=0)
    total_commission = sum(0.001578 * t.get("quantity", 0) * t.get("exit_price", 0)
                           for t in closed_trades)

    sc1, sc2, sc3, sc4, sc5, sc6 = st.columns(6)
    sc1.metric("Realized P&L", _fmt_thb(realized_pnl))
    sc2.metric("Profit Factor", f"{profit_factor:.2f}" if profit_factor != float("inf") else "∞")
    sc3.metric("Avg Win", _fmt_thb(avg_win))
    sc4.metric("Avg Loss", _fmt_thb(-avg_loss))
    sc5.metric("Largest Win", _fmt_thb(largest_win))
    sc6.metric("Largest Loss", _fmt_thb(largest_loss))
else:
    st.info("Performance stats will appear after first closed trade.")

# ── Strategy breakdown donut ───────────────────────────────────────────────────
if closed_trades:
    st.subheader("P&L by Strategy")
    strategy_pnl: dict[str, float] = {}
    for t in closed_trades:
        strat = t.get("strategy", "unknown")
        strategy_pnl[strat] = strategy_pnl.get(strat, 0) + t.get("pnl", 0)

    if strategy_pnl:
        labels = list(strategy_pnl.keys())
        values = [abs(v) for v in strategy_pnl.values()]
        colors_pie = ["#50fa7b" if strategy_pnl[l] >= 0 else "#ff5555" for l in labels]

        fig3 = go.Figure(go.Pie(
            labels=labels,
            values=values,
            hole=0.5,
            marker_colors=colors_pie,
            textinfo="label+percent",
        ))
        fig3.update_layout(
            template="plotly_dark",
            height=280,
            margin=dict(l=0, r=0, t=10, b=0),
            showlegend=True,
        )
        st.plotly_chart(fig3, use_container_width=True)
