"""
Talks to NSE via nselib, and caches everything to disk.

The core idea: NSE publishes a "bhav copy" for every trading day - one CSV
containing open/high/low/close/volume for every stock that traded that day.
So to scan 100 stocks over 90 days we download 90 files, not 9,000. Each file
is cached forever, so the second run only fetches days we don't already have.
"""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import Lock

import pandas as pd

from . import config

log = logging.getLogger("nse")

# nselib is imported lazily so the server can boot and return a clear error
# message if the package is missing, rather than crashing on startup.
_lib_lock = Lock()
_lib = {}


def _nselib():
    with _lib_lock:
        if not _lib:
            from nselib import capital_market, indices  # noqa: PLC0415

            _lib["capital_market"] = capital_market
            _lib["indices"] = indices
    return _lib


class NSEUnavailable(RuntimeError):
    """NSE refused or returned nothing usable."""


# --------------------------------------------------------------------------
# Day cache
# --------------------------------------------------------------------------

def _day_path(d: date) -> Path:
    return config.BHAV_DIR / f"{d:%Y-%m-%d}.csv.gz"


def _nodata_path(d: date) -> Path:
    """Marker meaning 'NSE published nothing for this date'."""
    return config.BHAV_DIR / f"{d:%Y-%m-%d}.nodata"


def _nodata_is_settled(d: date) -> bool:
    """Should we trust an existing 'no data' marker, or look again?

    An old date with no file is a holiday and will never change. A recent date
    with no file usually just means NSE has not published yet - the file lands
    in the evening. Treating that as permanent is what would otherwise freeze
    the dashboard on yesterday's close, so recent markers expire and get
    re-checked on the next scan.
    """
    marker = _nodata_path(d)
    if not marker.exists():
        return False
    if (date.today() - d).days > config.NODATA_LOCK_DAYS:
        return True
    age_minutes = (time.time() - marker.stat().st_mtime) / 60
    if age_minutes >= config.NODATA_RECHECK_MINUTES:
        marker.unlink(missing_ok=True)
        return False
    return True


def _mark_nodata(d: date) -> None:
    _nodata_path(d).write_text("")


# Columns nselib returns from bhav_copy_with_delivery, after it strips spaces.
_RENAME = {
    "SYMBOL": "symbol",
    "SERIES": "series",
    "DATE1": "date",
    "PREV_CLOSE": "prev_close",
    "OPEN_PRICE": "open",
    "HIGH_PRICE": "high",
    "LOW_PRICE": "low",
    "LAST_PRICE": "last",
    "CLOSE_PRICE": "close",
    "AVG_PRICE": "vwap",
    "TTL_TRD_QNTY": "volume",
    "TURNOVER_LACS": "turnover_lacs",
    "NO_OF_TRADES": "trades",
    "DELIV_QTY": "deliv_qty",
    "DELIV_PER": "deliv_pct",
}
_NUMERIC = [
    "prev_close", "open", "high", "low", "last", "close", "vwap",
    "volume", "turnover_lacs", "trades", "deliv_qty", "deliv_pct",
]
_KEEP = ["symbol", "series", "date"] + _NUMERIC


def _normalise(raw: pd.DataFrame, d: date) -> pd.DataFrame:
    """NSE's CSV has padded headers, comma-grouped numbers and '-' for nulls.
    Turn it into clean typed columns we can do maths on."""
    raw = raw.copy()
    raw.columns = [str(c).strip().replace(" ", "").upper() for c in raw.columns]
    raw = raw.rename(columns=_RENAME)

    for col in _KEEP:
        if col not in raw.columns:
            raw[col] = pd.NA
    raw = raw[_KEEP]

    raw["symbol"] = raw["symbol"].astype(str).str.strip().str.upper()
    raw["series"] = raw["series"].astype(str).str.strip().str.upper()

    for col in _NUMERIC:
        s = raw[col].astype(str).str.strip().str.replace(",", "", regex=False)
        raw[col] = pd.to_numeric(s.replace({"-": None, "": None, "nan": None}), errors="coerce")

    # Every row in one bhav copy shares the same trade date. NSE formats it as
    # '12-Sep-2026'; we overwrite with the date we asked for, which is the same
    # value but guaranteed parseable.
    raw["date"] = pd.Timestamp(d)

    raw = raw[raw["series"].isin(config.EQUITY_SERIES)]
    raw = raw.dropna(subset=["close"])
    return raw.reset_index(drop=True)


def _fetch_day(d: date) -> pd.DataFrame | None:
    """Return one trading day, from cache if we have it. None means no data
    exists for that date (weekend or holiday)."""
    if _nodata_is_settled(d):
        return None

    path = _day_path(d)
    if path.exists():
        try:
            df = pd.read_csv(path, compression="gzip")
            df["date"] = pd.Timestamp(d)
            return df
        except Exception:
            path.unlink(missing_ok=True)  # corrupt file, refetch

    cm = _nselib()["capital_market"]
    last_err: Exception | None = None

    for attempt in range(config.MAX_RETRIES):
        try:
            raw = cm.bhav_copy_with_delivery(trade_date=d.strftime("%d-%m-%Y"))
        except FileNotFoundError:
            # nselib raises this when NSE has no file for the date: a holiday,
            # or a session it has not published yet.
            _mark_nodata(d)
            return None
        except Exception as exc:  # network wobble, throttle, malformed CSV
            last_err = exc
            time.sleep(config.RETRY_BACKOFF_SECONDS * (attempt + 1))
            continue

        if raw is None or raw.empty:
            _mark_nodata(d)
            return None

        df = _normalise(raw, d)
        if df.empty:
            _mark_nodata(d)
            return None

        df.to_csv(path, index=False, compression="gzip")
        return df

    raise NSEUnavailable(f"Could not fetch {d:%Y-%m-%d} after {config.MAX_RETRIES} tries: {last_err}")


@dataclass
class PanelResult:
    """A price history panel plus a note on how much work it took to build."""
    frame: pd.DataFrame
    trading_days: list[date] = field(default_factory=list)
    from_cache: int = 0
    downloaded: int = 0
    failed: list[str] = field(default_factory=list)

    @property
    def latest_session(self) -> date | None:
        return self.trading_days[-1] if self.trading_days else None


def load_panel(trading_days_needed: int, end: date | None = None) -> PanelResult:
    """Build a tidy frame of daily bars covering the last N *trading* days.

    We walk backwards through the calendar until we've collected enough days
    that actually had trading. Weekends and holidays cost nothing after the
    first run because we remember them.
    """
    end = end or date.today()
    # Roughly 1.55 calendar days per trading day, plus slack for long holidays.
    horizon = int(trading_days_needed * 1.6) + 20
    candidates = [end - timedelta(days=i) for i in range(horizon)]
    # Cheap pre-filter; NSE never trades on a weekend.
    candidates = [d for d in candidates if d.weekday() < 5]

    cached_before = {d for d in candidates if _day_path(d).exists()}

    frames: dict[date, pd.DataFrame] = {}
    failed: list[str] = []

    def work(d: date):
        try:
            return d, _fetch_day(d)
        except NSEUnavailable as exc:
            failed.append(str(exc))
            return d, None

    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
        for d, df in pool.map(work, candidates):
            if df is not None and not df.empty:
                frames[d] = df

    if not frames:
        raise NSEUnavailable(
            "No trading data could be downloaded. NSE may be blocking this "
            "machine, or you may be offline. Cloud servers are often blocked - "
            "this works most reliably from a home or office connection."
        )

    trading_days = sorted(frames)[-trading_days_needed:]
    panel = pd.concat([frames[d] for d in trading_days], ignore_index=True)

    return PanelResult(
        frame=panel,
        trading_days=trading_days,
        from_cache=sum(1 for d in trading_days if d in cached_before),
        downloaded=sum(1 for d in trading_days if d not in cached_before),
        failed=failed,
    )


def close_matrix(panel: pd.DataFrame) -> pd.DataFrame:
    """Reshape tidy bars into a date x symbol grid of closing prices."""
    return (
        panel.pivot_table(index="date", columns="symbol", values="close", aggfunc="last")
        .sort_index()
    )


# --------------------------------------------------------------------------
# Index universe
# --------------------------------------------------------------------------

_UNIVERSE_FILE = config.META_DIR / "universe.json"


def load_universe(force: bool = False) -> dict:
    """Nifty 100 constituents from the official NIFTY Indices CSV.

    Returns {"index": str, "fetched": iso, "members": [{symbol, company, industry}]}
    """
    if not force and _UNIVERSE_FILE.exists():
        try:
            cached = json.loads(_UNIVERSE_FILE.read_text())
            age = datetime.now() - datetime.fromisoformat(cached["fetched"])
            if age < timedelta(days=config.UNIVERSE_TTL_DAYS) and cached.get("members"):
                return cached
        except Exception:
            pass

    idx = _nselib()["indices"]
    try:
        df = idx.constituent_stock_list(
            index_category=config.UNIVERSE_INDEX_CATEGORY,
            index_name=config.UNIVERSE_INDEX_NAME,
        )
    except Exception as exc:
        if _UNIVERSE_FILE.exists():  # stale is better than nothing
            return json.loads(_UNIVERSE_FILE.read_text())
        raise NSEUnavailable(f"Could not load {config.UNIVERSE_INDEX_NAME} constituents: {exc}") from exc

    df.columns = [str(c).strip().lower() for c in df.columns]
    sym_col = next((c for c in df.columns if "symbol" in c), None)
    name_col = next((c for c in df.columns if "company" in c or c == "name"), None)
    ind_col = next((c for c in df.columns if "industry" in c or "sector" in c), None)

    if sym_col is None:
        raise NSEUnavailable(f"Constituent CSV had unexpected columns: {list(df.columns)}")

    members = []
    for _, row in df.iterrows():
        sym = str(row[sym_col]).strip().upper()
        if not sym or sym == "NAN":
            continue
        members.append({
            "symbol": sym,
            "company": str(row[name_col]).strip() if name_col else sym,
            "industry": str(row[ind_col]).strip() if ind_col else "",
        })

    payload = {
        "index": config.UNIVERSE_INDEX_NAME,
        "fetched": datetime.now().isoformat(timespec="seconds"),
        "members": members,
    }
    _UNIVERSE_FILE.write_text(json.dumps(payload, indent=2))
    return payload


def cache_stats() -> dict:
    days = sorted(p.stem.replace(".csv", "") for p in config.BHAV_DIR.glob("*.csv.gz"))
    size = sum(p.stat().st_size for p in config.BHAV_DIR.glob("*")) / 1_048_576
    return {
        "cached_days": len(days),
        "earliest": days[0] if days else None,
        "latest": days[-1] if days else None,
        "size_mb": round(size, 2),
        "location": str(config.CACHE_DIR),
    }
