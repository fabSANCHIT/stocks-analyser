"""
Yahoo Finance price provider.

Why this exists alongside the NSE archive reader: NSE refuses data-centre IP
ranges, which makes live collection impossible from a host like Vercel. Yahoo
generally does not, so this is what makes a hosted deployment able to refresh
on demand.

Three things shape the design.

**Batch, don't loop.** `yf.download` accepts many tickers in one call and
returns a single frame. Asking for 100 tickers individually would be 100 round
trips and a near-certain rate limit; asking in chunks is a handful.

**Yahoo rate-limits shared IPs.** Cloud hosts share addresses between many
customers, so a 429 is a normal event rather than an exception - it is widely
reported on Streamlit Cloud and similar. Hence chunking, exponential backoff,
and an in-process cache so repeated scans on a warm instance cost nothing.

**Prices come back adjusted.** `auto_adjust=True` applies split and dividend
adjustments, which removes the false crossovers that raw NSE bhav prices
produce around an ex-date. This is a real accuracy win over the archive reader.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from threading import Lock

import pandas as pd

from . import config

log = logging.getLogger("yahoo")

SUFFIX = ".NS"  # Yahoo's exchange suffix for NSE equities


class YahooUnavailable(RuntimeError):
    """Yahoo returned nothing usable."""


_yf = {}
_yf_lock = Lock()


def _lib():
    with _yf_lock:
        if "mod" not in _yf:
            import yfinance  # noqa: PLC0415

            yfinance.set_tz_cache_location(str(config.CACHE_DIR / "yf-tz"))
            _yf["mod"] = yfinance
    return _yf["mod"]


# --------------------------------------------------------------- caching --

@dataclass
class _Entry:
    frame: pd.DataFrame
    fetched: datetime
    covers: int


_cache: dict[str, _Entry] = {}
_cache_lock = Lock()


def clear_cache() -> None:
    """Drop held downloads so the next fetch really goes to Yahoo. The Refresh
    button calls this; without it a press inside the cache window would look
    like it worked while changing nothing."""
    with _cache_lock:
        _cache.clear()


def latest_cached_date() -> str | None:
    """Most recent session in anything already downloaded, or None if this
    instance has not fetched yet. Lets the status endpoint report freshness
    without paying for a network call."""
    with _cache_lock:
        entries = list(_cache.values())
    best = None
    for entry in entries:
        try:
            idx = pd.to_datetime(entry.frame.index).tz_localize(None)
        except TypeError:
            idx = pd.to_datetime(entry.frame.index)
        if len(idx):
            day = idx.max().date().isoformat()
            best = day if best is None or day > best else best
    return best


def _cache_key(symbols: list[str]) -> str:
    return f"{len(symbols)}:{hash(tuple(sorted(symbols)))}"


def _fresh_enough(entry: _Entry, needed: int) -> bool:
    if entry.covers < needed:
        return False
    age = (datetime.now() - entry.fetched).total_seconds() / 60
    return age < config.YAHOO_CACHE_MINUTES


# ----------------------------------------------------------------- fetch --

def _download(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    yf = _lib()
    last_err: Exception | None = None

    for attempt in range(config.YAHOO_MAX_RETRIES):
        try:
            frame = yf.download(
                tickers=tickers,
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                interval="1d",
                auto_adjust=True,
                actions=False,
                progress=False,
                threads=True,
                group_by="column",
                timeout=config.YAHOO_TIMEOUT_SECONDS,
            )
            if frame is not None and not frame.empty:
                return frame
            last_err = YahooUnavailable("empty response")
        except Exception as exc:
            last_err = exc
            if "rate" not in str(exc).lower() and "429" not in str(exc):
                log.warning("Yahoo error on attempt %s: %s", attempt + 1, exc)

        # Jittered backoff. Without the jitter, parallel instances retry in
        # lockstep and trip the limit again together.
        delay = config.YAHOO_BACKOFF_SECONDS * (2 ** attempt) + random.uniform(0, 0.6)
        time.sleep(delay)

    raise YahooUnavailable(
        f"Yahoo Finance did not return data after {config.YAHOO_MAX_RETRIES} attempts "
        f"({last_err}). This is usually rate limiting, which is common on shared "
        f"cloud IP addresses. Waiting a minute and trying again normally works."
    )


def _extract(frame: pd.DataFrame, field_name: str, tickers: list[str]) -> pd.DataFrame:
    """Pull one field out of whatever shape yfinance returned.

    With several tickers the columns are a MultiIndex of (field, ticker). With
    exactly one ticker they are flat, so handle both rather than assuming.
    """
    if isinstance(frame.columns, pd.MultiIndex):
        if field_name not in frame.columns.get_level_values(0):
            raise YahooUnavailable(f"Yahoo response had no {field_name} data.")
        out = frame[field_name].copy()
    else:
        if field_name not in frame.columns:
            raise YahooUnavailable(f"Yahoo response had no {field_name} data.")
        out = frame[[field_name]].copy()
        out.columns = [tickers[0]]

    out.columns = [str(c).removesuffix(SUFFIX).upper() for c in out.columns]
    out.index = pd.to_datetime(out.index).tz_localize(None).normalize()
    return out.sort_index()


@dataclass
class Fetched:
    closes: pd.DataFrame
    volumes: pd.DataFrame | None = None
    downloaded: bool = True
    missing: list[str] = field(default_factory=list)


def fetch(symbols: list[str], trading_days: int) -> Fetched:
    """Daily adjusted closes for the given NSE symbols, newest last."""
    if not symbols:
        raise YahooUnavailable("No symbols requested.")

    key = _cache_key(symbols)
    with _cache_lock:
        hit = _cache.get(key)
        if hit and _fresh_enough(hit, trading_days):
            closes = _extract(hit.frame, "Close", [])
            return Fetched(closes=closes.tail(trading_days),
                           volumes=_safe_volumes(hit.frame),
                           downloaded=False)

    # Calendar days needed to contain the wanted number of sessions, with room
    # for weekends and the long Indian holiday stretches.
    calendar_days = int(trading_days * 1.55) + 25
    end = date.today()
    start = end - timedelta(days=calendar_days)

    tickers = [f"{s}{SUFFIX}" for s in symbols]
    chunks = [tickers[i:i + config.YAHOO_CHUNK_SIZE]
              for i in range(0, len(tickers), config.YAHOO_CHUNK_SIZE)]

    frames = []
    for i, chunk in enumerate(chunks):
        if i:
            time.sleep(config.YAHOO_CHUNK_PAUSE_SECONDS)
        frames.append(_download(chunk, start, end))

    combined = frames[0] if len(frames) == 1 else pd.concat(frames, axis=1)

    with _cache_lock:
        _cache[key] = _Entry(frame=combined, fetched=datetime.now(), covers=trading_days)

    closes = _extract(combined, "Close", tickers)
    # Drop stocks Yahoo knows nothing about, and sessions where nothing traded.
    closes = closes.dropna(axis=1, how="all").dropna(axis=0, how="all")
    missing = [s for s in symbols if s not in closes.columns]

    return Fetched(closes=closes.tail(trading_days),
                   volumes=_safe_volumes(combined),
                   downloaded=True, missing=missing)


def _safe_volumes(frame: pd.DataFrame) -> pd.DataFrame | None:
    try:
        return _extract(frame, "Volume", [])
    except Exception:
        return None


def market_summary(symbols: list[str], members: list[dict]) -> dict:
    """The Overview tab, computed from the same download the scanner uses."""
    got = fetch(symbols, trading_days=3)
    closes = got.closes
    if len(closes) < 2:
        raise YahooUnavailable("Need two sessions to compute a daily change.")

    latest, prior = closes.index[-1], closes.index[-2]
    change = ((closes.loc[latest] - closes.loc[prior]) / closes.loc[prior] * 100).dropna()
    meta = {m["symbol"]: m for m in members}

    vol_row = None
    if got.volumes is not None and latest in got.volumes.index:
        vol_row = got.volumes.loc[latest]

    def rows(ascending: bool):
        out = []
        for sym, pct in change.sort_values(ascending=ascending).head(8).items():
            vol = vol_row.get(sym) if vol_row is not None else None
            out.append({
                "symbol": sym,
                "company": meta.get(sym, {}).get("company", sym),
                "close": round(float(closes.at[latest, sym]), 2),
                "change_pct": round(float(pct), 2),
                "volume": int(vol) if vol is not None and pd.notna(vol) else None,
            })
        return out

    active = []
    if vol_row is not None:
        turnover = (vol_row * closes.loc[latest]).dropna().sort_values(ascending=False)
        active = [{
            "symbol": s,
            "company": meta.get(s, {}).get("company", s),
            "turnover_cr": round(float(v) / 1e7, 2),
            "change_pct": round(float(change.get(s, 0)), 2),
        } for s, v in turnover.head(8).items()]

    counts = {"advances": int((change > 0).sum()),
              "declines": int((change < 0).sum()),
              "unchanged": int((change == 0).sum())}

    return {
        "session_date": latest.date().isoformat(),
        "previous_date": prior.date().isoformat(),
        "breadth": counts,
        "index_breadth": {**counts, "label": config.UNIVERSE_INDEX_NAME},
        "gainers": rows(False),
        "losers": rows(True),
        "most_active": active,
        "stats": {"symbols_traded": int(len(change)),
                  "days_from_cache": 0 if got.downloaded else 1,
                  "days_downloaded": 1 if got.downloaded else 0},
    }
