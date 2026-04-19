"""
Notification system for trade alerts via LINE Notify.
"""

import requests
from loguru import logger


class Notifier:
    """Send trade notifications via LINE Notify."""

    LINE_API = "https://notify-api.line.me/api/notify"

    def __init__(self, token: str = ""):
        self.token = token
        self.enabled = bool(token)

    def send(self, message: str):
        """Send a notification message."""
        logger.info(f"[NOTIFY] {message}")
        if not self.enabled:
            return

        try:
            resp = requests.post(
                self.LINE_API,
                headers={"Authorization": f"Bearer {self.token}"},
                data={"message": message},
                timeout=5,
            )
            if resp.status_code != 200:
                logger.warning(f"LINE notify failed: {resp.status_code}")
        except Exception as e:
            logger.error(f"Notification error: {e}")

    def trade_alert(
        self,
        action: str,
        symbol: str,
        price: float,
        quantity: int,
        reason: str = "",
    ):
        """Send a formatted trade alert."""
        emoji = "🟢" if action == "BUY" else "🔴"
        msg = (
            f"\n{emoji} {action} {symbol}"
            f"\nPrice: ฿{price:,.2f}"
            f"\nQty: {quantity:,}"
            f"\nValue: ฿{price * quantity:,.2f}"
        )
        if reason:
            msg += f"\nSignal: {reason}"
        self.send(msg)

    def daily_summary(self, stats: dict):
        """Send end-of-day summary."""
        pnl = stats.get("realized_pnl", 0)
        pnl_emoji = "📈" if pnl >= 0 else "📉"
        msg = (
            f"\n{pnl_emoji} Daily Summary"
            f"\nP&L: ฿{pnl:,.2f}"
            f"\nTrades: {stats.get('total_trades', 0)}"
            f"\nWin Rate: {stats.get('win_rate', 0):.1f}%"
            f"\nPortfolio: ฿{stats.get('portfolio_value', 0):,.2f}"
        )
        self.send(msg)
