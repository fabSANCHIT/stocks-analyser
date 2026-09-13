"""
Snapshots.

The scanner has two jobs that want very different homes.

  Collecting  - talks to NSE, downloads many files, takes a minute, needs an
                IP address that NSE will actually answer.
  Serving     - reads prices, does arithmetic, returns JSON in milliseconds.

Locally they happily live together. On a host like Vercel they can't: the
filesystem is wiped between requests, functions time out, and NSE tends to
refuse cloud IP ranges outright.

A snapshot splits them. You run the collector somewhere NSE will talk to you -
your own laptop - and it writes one small file containing every closing price
plus a precomputed market summary. The server reads that file and never touches
NSE at all. Around 250 KB for 100 stocks over 300 sessions, small enough to
commit to your repository.
"""
from __future__ import annotations

import gzip
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

SCHEMA = 1


def build(days: int = 300, max_stocks: int = 150) -> dict:
    """Collect from NSE and return a snapshot payload. Run this locally."""
    from . import nse

    universe = nse.load_universe(force=True)
    members = universe["members"][:max_stocks]
    symbols = [m["symbol"] for m in members]

    panel = nse.load_panel(trading_days_needed=days)
    closes = nse.close_matrix(panel.frame)
    keep = [s for s in symbols if s in closes.columns]
    closes = closes[keep]

    return {
        "schema": SCHEMA,
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "universe": {**universe, "members": members},
        "dates": [d.date().isoformat() for d in closes.index],
        "symbols": list(closes.columns),
        # Row-major, None for a session the stock didn't trade.
        "closes": [[None if pd.isna(v) else round(float(v), 2) for v in row]
                   for row in closes.to_numpy()],
        "market": _summarise(panel.frame, closes, members),
    }


def _summarise(frame: pd.DataFrame, closes: pd.DataFrame, members: list[dict]) -> dict | None:
    """Precompute the Overview tab so the server does no work for it."""
    if len(closes) < 2:
        return None
    latest, prior = closes.index[-1], closes.index[-2]
    today = frame[frame["date"] == latest].drop_duplicates("symbol").set_index("symbol")
    chg = ((closes.loc[latest] - closes.loc[prior]) / closes.loc[prior] * 100).dropna()
    meta = {m["symbol"]: m for m in members}

    def rows(ascending: bool):
        return [{
            "symbol": s,
            "company": meta.get(s, {}).get("company", s),
            "close": round(float(closes.at[latest, s]), 2),
            "change_pct": round(float(p), 2),
            "volume": int(today.at[s, "volume"]) if s in today.index
                      and pd.notna(today.at[s, "volume"]) else None,
        } for s, p in chg.sort_values(ascending=ascending).head(8).items()]

    turnover = today.reindex(closes.columns)["turnover_lacs"].dropna().sort_values(ascending=False)
    return {
        "session_date": latest.date().isoformat(),
        "previous_date": prior.date().isoformat(),
        "breadth": {"advances": int((chg > 0).sum()), "declines": int((chg < 0).sum()),
                    "unchanged": int((chg == 0).sum())},
        "index_breadth": {"advances": int((chg > 0).sum()), "declines": int((chg < 0).sum()),
                          "unchanged": int((chg == 0).sum()), "label": "Nifty 100"},
        "gainers": rows(False),
        "losers": rows(True),
        "most_active": [{
            "symbol": s,
            "company": meta.get(s, {}).get("company", s),
            "turnover_cr": round(float(v) / 100, 2),
            "change_pct": round(float(chg.get(s, 0)), 2),
        } for s, v in turnover.head(8).items()],
        "stats": {"symbols_traded": int(len(chg)), "days_from_cache": 0, "days_downloaded": 0},
    }


def write(path: Path, days: int = 300, max_stocks: int = 150) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build(days=days, max_stocks=max_stocks)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    return path


_cache: dict = {}


def load(path: Path) -> dict | None:
    """Read a snapshot, holding it in memory so repeat requests are free."""
    if not path.exists():
        return None
    stamp = path.stat().st_mtime
    if _cache.get("stamp") == stamp:
        return _cache["payload"]
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        payload = json.load(fh)
    if payload.get("schema") != SCHEMA:
        raise ValueError(
            f"Snapshot at {path} uses schema {payload.get('schema')}, "
            f"this build expects {SCHEMA}. Rebuild it."
        )
    _cache.update(stamp=stamp, payload=payload)
    return payload


def closes_frame(payload: dict) -> pd.DataFrame:
    return pd.DataFrame(
        payload["closes"],
        index=pd.to_datetime(payload["dates"]),
        columns=payload["symbols"],
    ).astype("float64")
