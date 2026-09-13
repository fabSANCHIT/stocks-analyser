"""FastAPI server. Run with:  uvicorn app.main:app --reload --port 8000"""
from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import config, freshness, snapshot, strategies, universe as universe_mod, yahoo

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")

app = FastAPI(title="NSE Dashboard API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------

class ScanRequest(BaseModel):
    """Params are whatever the chosen strategy declares, so this stays open.
    The strategy validates its own inputs."""
    strategy: str = strategies.DEFAULT_STRATEGY
    params: dict = Field(default_factory=dict)


def _snapshot():
    """The prebuilt price file, if one shipped with this deployment."""
    try:
        return snapshot.load(config.SNAPSHOT_PATH)
    except Exception as exc:
        log.warning("Snapshot unreadable: %s", exc)
        return None


def _no_data(extra: str = "") -> HTTPException:
    if config.SNAPSHOT_ONLY:
        return HTTPException(status_code=503, detail=(
            "This deployment serves a prebuilt snapshot and none was found. "
            "Build one locally with: python -m tools.build_snapshot "
            "then commit data/snapshot.json.gz and redeploy. " + extra
        ))
    return HTTPException(status_code=503, detail="No price data available. " + extra)


def _snapshot_closes(needed: int):
    snap = _snapshot()
    if not snap:
        return None
    closes = snapshot.closes_frame(snap)
    return closes.tail(needed), {
        "from_cache": len(closes), "downloaded": 0,
        "source": "snapshot", "built_at": snap["built_at"],
    }


def _nse_archive():
    """Imported only when actually selected - it pulls in nselib, which a
    hosted deployment does not ship."""
    from . import nse  # noqa: PLC0415
    return nse


def _load_closes(needed: int, symbols: list[str] | None = None):
    """Closing prices from the configured provider.

    Falls back to a bundled snapshot if the provider is unreachable, because
    showing slightly old prices with a clear label beats an error page.
    """
    if config.SNAPSHOT_ONLY:
        got = _snapshot_closes(needed)
        if got is None:
            raise _no_data()
        return got

    if config.DATA_PROVIDER == "yahoo":
        if not symbols:
            symbols = [m["symbol"] for m in _load_universe()["members"]]
        try:
            got = yahoo.fetch(symbols, trading_days=needed)
            return got.closes, {
                "from_cache": 0 if got.downloaded else len(got.closes),
                "downloaded": len(got.closes) if got.downloaded else 0,
                "source": "yahoo",
                "latest_session": got.closes.index[-1].date().isoformat() if len(got.closes) else None,
                "missing": got.missing,
            }
        except yahoo.YahooUnavailable as exc:
            fallback = _snapshot_closes(needed)
            if fallback is None:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            log.warning("Yahoo unavailable, serving snapshot: %s", exc)
            frame, stats = fallback
            stats["source"] = "snapshot (Yahoo unreachable)"
            return frame, stats

    nse = _nse_archive()
    try:
        panel = nse.load_panel(trading_days_needed=needed)
        return nse.close_matrix(panel.frame), {
            "from_cache": panel.from_cache,
            "downloaded": panel.downloaded,
            "source": "nse",
            "latest_session": panel.latest_session.isoformat() if panel.latest_session else None,
        }
    except nse.NSEUnavailable as exc:
        fallback = _snapshot_closes(needed)
        if fallback is None:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        log.warning("NSE unreachable, serving snapshot: %s", exc)
        frame, stats = fallback
        stats["source"] = "snapshot (NSE unreachable)"
        return frame, stats


def _load_universe(force: bool = False):
    try:
        return universe_mod.load(force=force)
    except universe_mod.UniverseUnavailable as exc:
        snap = _snapshot()
        if snap:
            return snap["universe"]
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _safe_int(frame: pd.DataFrame, key: str, column: str):
    """Read one cell without blowing up on a missing or duplicated symbol."""
    if key not in frame.index or column not in frame.columns:
        return None
    val = frame.at[key, column]
    if isinstance(val, pd.Series):
        val = val.iloc[0]
    return None if pd.isna(val) else int(val)


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"ok": True, "time": datetime.now().isoformat(timespec="seconds")}


@app.get("/api/status")
def status():
    """Everything the Overview tab needs to describe the data source.

    This is the free-data replacement for Kite's /profile call: instead of
    reporting who you are, it reports what data you have.
    """
    snap = _snapshot()
    names = {"yahoo": "Yahoo Finance, split and dividend adjusted",
             "nse": "NSE India public archives"}
    using_nse = config.DATA_PROVIDER == "nse"
    out = {
        "source": names.get(config.DATA_PROVIDER, config.DATA_PROVIDER),
        "cost": "Free. No broker account, no API key, no login.",
        "provider": config.DATA_PROVIDER,
        "mode": "snapshot" if config.SNAPSHOT_ONLY else "live",
        "snapshot_built_at": snap["built_at"] if snap else None,
        "cache": (_nse_archive().cache_stats() if using_nse else
                  {"cached_days": 0, "earliest": None, "latest": None,
                   "size_mb": 0.0, "location": "held in memory"}),
        "universe": None,
        "freshness": None,
        # Yahoo answers cloud hosts, so a hosted deployment can refresh itself.
        "can_refresh": not config.SNAPSHOT_ONLY,
        "error": None,
    }

    latest = out["cache"].get("latest")
    if latest is None and config.DATA_PROVIDER == "yahoo":
        latest = yahoo.latest_cached_date()
    if latest is None and snap and snap.get("dates"):
        latest = snap["dates"][-1]
    # Nothing fetched yet on this instance is normal for an on-demand provider,
    # not a fault - don't report it as missing data.
    out["freshness"] = (freshness.describe(latest) if latest else
                        {"state": "unknown", "behind": None,
                         "expected_session": freshness.expected_last_session().isoformat(),
                         "message": "Nothing loaded yet. Press Generate or Refresh."})
    out["latest_session"] = latest
    try:
        uni = _load_universe()
        out["universe"] = {
            "index": uni["index"],
            "count": len(uni["members"]),
            "fetched": uni["fetched"],
            "industries": sorted({m["industry"] for m in uni["members"] if m["industry"]}),
        }
    except Exception as exc:
        out["error"] = str(exc)
    return out


@app.get("/api/universe")
def universe(refresh: bool = False):
    return _load_universe(force=refresh)


@app.get("/api/market")
def market(days: int = Query(3, ge=2, le=10)):
    """Latest session summary from whichever provider is configured."""
    if config.SNAPSHOT_ONLY:
        snap = _snapshot()
        if not snap or not snap.get("market"):
            raise _no_data("The snapshot has no market summary; rebuild it.")
        return snap["market"]

    uni = _load_universe()
    members = uni["members"]
    symbols = [m["symbol"] for m in members]

    if config.DATA_PROVIDER == "yahoo":
        try:
            return yahoo.market_summary(symbols, members)
        except yahoo.YahooUnavailable as exc:
            snap = _snapshot()
            if snap and snap.get("market"):
                return snap["market"]
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    nse = _nse_archive()
    try:
        panel = nse.load_panel(trading_days_needed=days)
    except nse.NSEUnavailable as exc:
        snap = _snapshot()
        if snap and snap.get("market"):
            return snap["market"]
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    closes = nse.close_matrix(panel.frame)
    if len(closes) < 2:
        raise HTTPException(status_code=503, detail="Need two trading days to compute change.")

    latest, prior = closes.index[-1], closes.index[-2]
    today = panel.frame[panel.frame["date"] == latest].drop_duplicates("symbol").set_index("symbol")
    chg = ((closes.loc[latest] - closes.loc[prior]) / closes.loc[prior] * 100).dropna()
    meta = {m["symbol"]: m for m in members}

    def rows(series: pd.Series, ascending: bool, n: int = 8):
        return [{
            "symbol": s,
            "company": meta.get(s, {}).get("company", s),
            "close": round(float(closes.at[latest, s]), 2),
            "change_pct": round(float(p), 2),
            "volume": _safe_int(today, s, "volume"),
        } for s, p in series.sort_values(ascending=ascending).head(n).items()]

    index_chg = chg[chg.index.isin(meta)] if meta else chg
    turnover = today.reindex(closes.columns)["turnover_lacs"].dropna().sort_values(ascending=False)

    return {
        "session_date": latest.date().isoformat(),
        "previous_date": prior.date().isoformat(),
        "breadth": {"advances": int((chg > 0).sum()), "declines": int((chg < 0).sum()),
                    "unchanged": int((chg == 0).sum())},
        "index_breadth": {"advances": int((index_chg > 0).sum()),
                          "declines": int((index_chg < 0).sum()),
                          "unchanged": int((index_chg == 0).sum()),
                          "label": config.UNIVERSE_INDEX_NAME},
        "gainers": rows(index_chg, False),
        "losers": rows(index_chg, True),
        "most_active": [{
            "symbol": s,
            "company": meta.get(s, {}).get("company", s),
            "turnover_cr": round(float(v) / 100, 2),
            "change_pct": round(float(chg.get(s, 0)), 2),
        } for s, v in turnover.head(8).items()],
        "stats": {"symbols_traded": int(len(chg)),
                  "days_from_cache": panel.from_cache,
                  "days_downloaded": panel.downloaded},
    }


@app.get("/api/strategies")
def list_strategies():
    """Drives the whole Signals tab: the strategy picker, the input form and
    the results table are all built from what this returns."""
    return {
        "default": strategies.DEFAULT_STRATEGY,
        "strategies": [s.spec() for s in strategies.REGISTRY.values()],
    }


@app.post("/api/signals/scan")
def scan(req: ScanRequest):
    started = datetime.now()

    try:
        strategy = strategies.get(req.strategy)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Anything the caller left out falls back to the strategy's own default.
    params = {**strategies.defaults_for(req.strategy), **(req.params or {})}
    for spec in strategy.params:
        val = params.get(spec.key)
        if spec.kind == "int":
            params[spec.key] = int(val)
        elif spec.kind == "float":
            params[spec.key] = float(val)
        elif spec.kind == "bool":
            params[spec.key] = bool(val)
        if spec.min is not None and isinstance(params[spec.key], (int, float)) \
                and not isinstance(params[spec.key], bool):
            if params[spec.key] < spec.min or (spec.max is not None and params[spec.key] > spec.max):
                raise HTTPException(
                    status_code=422,
                    detail=f"{spec.label} must be between {spec.min} and {spec.max}.",
                )

    uni = _load_universe()
    members = uni["members"][: int(params["max_stocks"])]
    wanted = [m["symbol"] for m in members]
    meta = {m["symbol"]: m for m in members}

    closes, stats = _load_closes(strategy.min_history(params), symbols=wanted)
    present = [s for s in wanted if s in closes.columns]
    missing = [s for s in wanted if s not in closes.columns]
    closes = closes[present]

    try:
        found = strategy.run(closes, params)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    for row in found:
        info = meta.get(row["symbol"], {})
        row["company"] = info.get("company", row["symbol"])
        row["industry"] = info.get("industry", "")

    return {
        "strategy": strategy.id,
        "params": params,
        "results": found,
        "summary": {
            "bullish": sum(1 for r in found if r["crossover"] == "bullish"),
            "bearish": sum(1 for r in found if r["crossover"] == "bearish"),
            "whipsaw": sum(1 for r in found if r["whipsaw"]),
            "scanned": len(present),
            "requested": len(wanted),
            "no_data": missing,
            "trading_days_loaded": len(closes),
            "history_from": closes.index[0].date().isoformat() if len(closes) else None,
            "history_to": closes.index[-1].date().isoformat() if len(closes) else None,
            "days_from_cache": stats["from_cache"],
            "days_downloaded": stats["downloaded"],
            "data_source": stats["source"],
            "latest_session": stats.get("latest_session"),
            "provider": config.DATA_PROVIDER,
            "elapsed_seconds": round((datetime.now() - started).total_seconds(), 1),
        },
    }


@app.get("/api/stock/{symbol}")
def stock(symbol: str, days: int = Query(200, ge=60, le=400),
          short_window: int = 6, long_window: int = 30,
          fast_span: int = 12, slow_span: int = 26, signal_span: int = 9):
    """Price history with both indicator sets, for the Stock tab charts."""
    from . import indicators as ind

    symbol = symbol.strip().upper()
    all_closes, _ = _load_closes(days, symbols=[symbol])
    if symbol not in all_closes.columns:
        raise HTTPException(status_code=404, detail=f"No NSE equity data for {symbol}.")
    closes = all_closes[[symbol]].dropna()
    if closes.empty:
        raise HTTPException(status_code=404, detail=f"No NSE equity data for {symbol}.")
    sma_s = ind.sma(closes, short_window)
    sma_l = ind.sma(closes, long_window)
    macd, sig, hist = ind.macd_lines(closes, fast_span, slow_span, signal_span)

    def col(frame):
        return frame[symbol].tolist()

    def clean(v):
        return None if pd.isna(v) else round(float(v), 4)

    series = [{
        "date": d.date().isoformat(),
        "close": clean(c),
        "sma_short": clean(a), "sma_long": clean(b),
        "macd": clean(m), "signal": clean(g), "hist": clean(h),
    } for d, c, a, b, m, g, h in zip(
        closes.index, col(closes), col(sma_s), col(sma_l), col(macd), col(sig), col(hist)
    )]

    # Mark every crossover on the chart, each carrying its own angle so the
    # strength of a signal is visible at the point it happened.
    marks = {
        "sma": ind.detect_crossovers(sma_s, sma_l, closes, sma_l, lookback=len(closes)),
        "macd": ind.detect_crossovers(macd, sig, closes, closes, lookback=len(closes)),
    }
    for key in marks:
        marks[key] = [{
            "date": m["crossover_date"], "crossover": m["crossover"],
            "angle": m["angle"], "grade": m["angle_grade"],
        } for m in marks[key]]

    try:
        info = next(m for m in _load_universe()["members"] if m["symbol"] == symbol)
    except Exception:
        info = {"company": symbol, "industry": ""}

    return {
        "symbol": symbol,
        "company": info.get("company", symbol),
        "industry": info.get("industry", ""),
        "windows": {"short": short_window, "long": long_window,
                    "fast": fast_span, "slow": slow_span, "signal": signal_span},
        "series": series,
        "crossovers": marks,
    }


@app.post("/api/refresh")
def refresh():
    """Pull the newest prices now.

    This is what the Refresh button calls. With the Yahoo provider it works
    identically on your laptop and on a hosted deployment, because Yahoo answers
    cloud IP addresses - which is the whole reason that provider exists.
    """
    started = datetime.now()
    uni = _load_universe(force=True)
    symbols = [m["symbol"] for m in uni["members"]]

    if config.DATA_PROVIDER == "yahoo":
        yahoo.clear_cache()          # force a real fetch rather than reusing one
        try:
            got = yahoo.fetch(symbols, trading_days=200)
        except yahoo.YahooUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        latest = got.closes.index[-1].date().isoformat() if len(got.closes) else None
        return {
            "mode": "live",
            "provider": "yahoo",
            "sessions": len(got.closes),
            "symbols": len(got.closes.columns),
            "latest_session": latest,
            "freshness": freshness.describe(latest),
            "elapsed_seconds": round((datetime.now() - started).total_seconds(), 1),
            "message": f"Refreshed {len(got.closes.columns)} stocks to {latest}.",
        }

    nse = _nse_archive()
    try:
        panel = nse.load_panel(trading_days_needed=200)
    except nse.NSEUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    latest = panel.latest_session.isoformat() if panel.latest_session else None
    return {
        "mode": "live",
        "provider": "nse",
        "downloaded": panel.downloaded,
        "from_cache": panel.from_cache,
        "latest_session": latest,
        "freshness": freshness.describe(latest),
        "elapsed_seconds": round((datetime.now() - started).total_seconds(), 1),
        "message": (f"Downloaded {panel.downloaded} new session(s)."
                    if panel.downloaded else "Already up to date."),
    }



@app.post("/api/cache/warm")
def warm(days: int = Query(120, ge=10, le=400)):
    """Pre-download history so the first scan of the day is instant."""
    if config.DATA_PROVIDER != "nse":
        raise HTTPException(status_code=400, detail=(
            f"Nothing to warm: the {config.DATA_PROVIDER} provider fetches on demand "
            f"and keeps its own short-lived cache. Just press Generate."
        ))
    nse = _nse_archive()
    try:
        panel = nse.load_panel(trading_days_needed=days)
    except nse.NSEUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "trading_days": len(panel.trading_days),
        "from_cache": panel.from_cache,
        "downloaded": panel.downloaded,
        "cache": nse.cache_stats(),
    }
