"""
Shared State Store
Provides a thread-safe, JSON-backed state object so the trading bot
can write its live state and the Streamlit dashboard can read it.
"""

import json
import threading
from datetime import datetime
from pathlib import Path

_STATE_FILE = Path("data/bot_state.json")
_lock = threading.Lock()


def _default_state() -> dict:
    return {
        "last_updated": None,
        "mode": "paper",
        "running": False,
        "cash": 0.0,
        "initial_capital": 0.0,
        "daily_pnl": 0.0,
        "daily_trades": 0,
        "peak_equity": 0.0,
        "positions": {},       # symbol -> position dict
        "equity_history": [],  # list of [iso_timestamp, value]
        "closed_trades": [],   # list of trade dicts
        "signals_log": [],     # last 50 signals seen
        "watchlist": [],
    }


def load() -> dict:
    """Load state from disk, returning default if missing."""
    try:
        if _STATE_FILE.exists():
            with _lock:
                return json.loads(_STATE_FILE.read_text())
    except Exception:
        pass
    return _default_state()


def save(state: dict):
    """Persist state dict to disk atomically."""
    state["last_updated"] = datetime.now().isoformat()
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STATE_FILE.with_suffix(".tmp")
        with _lock:
            tmp.write_text(json.dumps(state, default=str))
            tmp.replace(_STATE_FILE)
    except Exception as e:
        pass  # Non-critical; dashboard will just show stale data


def update(updates: dict):
    """Merge updates into current state and save."""
    state = load()
    state.update(updates)
    save(state)


def append_signal(signal_dict: dict):
    """Append a signal entry; keeps last 50."""
    state = load()
    log = state.get("signals_log", [])
    log.append(signal_dict)
    state["signals_log"] = log[-50:]
    save(state)


def append_equity(timestamp: str, value: float):
    """Append an equity snapshot; keeps last 2000 points."""
    state = load()
    history = state.get("equity_history", [])
    history.append([timestamp, value])
    state["equity_history"] = history[-2000:]
    save(state)
