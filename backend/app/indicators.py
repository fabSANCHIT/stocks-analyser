"""
Indicator maths shared by every strategy.

Two ideas do most of the work here.

1. Every crossover strategy reduces to the same shape: a fast line, a slow
   line, and the days the fast one cuts through the slow one. SMA 6/30 and
   MACD 12/26/9 differ only in how the two lines are produced. So the
   detection code below is written once against "fast" and "slow" and reused.

2. Crossover strength is the angle between those two lines. That needs care -
   see the note on `crossing_angle`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ----------------------------------------------------------------- lines --

def sma(frame: pd.DataFrame, window: int) -> pd.DataFrame:
    return frame.rolling(window, min_periods=window).mean()


def ema(frame: pd.DataFrame, span: int) -> pd.DataFrame:
    """Standard MACD-style EMA: smoothing factor 2/(span+1), seeded once the
    first `span` observations exist so early values aren't distorted."""
    out = frame.ewm(span=span, adjust=False, min_periods=span).mean()
    return out


def macd_lines(closes: pd.DataFrame, fast: int, slow: int, signal: int):
    """Returns (macd_line, signal_line, histogram)."""
    macd_line = ema(closes, fast) - ema(closes, slow)
    signal_line = ema(macd_line, signal)
    return macd_line, signal_line, macd_line - signal_line


# ----------------------------------------------------------------- angle --

def _slope_pct_per_day(values: np.ndarray, basis: float) -> float | None:
    """Least-squares slope of a short run of points, expressed as percent of
    `basis` per day. Regression rather than a two-point difference so one odd
    session doesn't swing the answer."""
    clean = values[~np.isnan(values)]
    if len(clean) < 2 or not basis or np.isnan(basis) or basis == 0:
        return None
    x = np.arange(len(clean), dtype=float)
    slope = np.polyfit(x, clean, 1)[0]
    return float(slope / abs(basis) * 100.0)


def crossing_angle(fast_slope_pct: float | None, slow_slope_pct: float | None) -> float | None:
    """Angle in degrees between two lines given their slopes.

    Why the percent normalisation in `_slope_pct_per_day` matters: a raw slope
    in rupees-per-day is meaningless across stocks. A 2,800-rupee stock and a
    95-rupee stock making identical percentage moves produce wildly different
    raw slopes, so a raw angle would just rank stocks by share price. Working
    in percent-of-price per day makes the number comparable across the index.

    Uses the exact formula for the angle between two lines rather than the
    small-angle shortcut, since a fast average in a sharp move can be steep
    enough for the difference to show.
    """
    if fast_slope_pct is None or slow_slope_pct is None:
        return None
    m1, m2 = fast_slope_pct, slow_slope_pct
    denom = 1.0 + m1 * m2
    if abs(denom) < 1e-12:
        return 90.0
    return float(np.degrees(np.arctan((m1 - m2) / denom)))


GRADES = ["flat", "mild", "firm", "steep"]


def assign_grades(rows: list[dict]) -> None:
    """Grade each crossover's steepness against the others in the same scan.

    Fixed degree thresholds don't work here. Measured across the Nifty 100, SMA
    6/30 crossovers sit around 32 degrees while MACD 12/26/9 crossovers sit
    around 6 - the two indicators simply live on different scales, and any
    indicator added later will have a scale of its own. Grading against the
    scan's own distribution is self-calibrating, so a new strategy gets
    sensible grades without anyone hand-tuning a threshold for it.

    The raw angle is still reported and is comparable across scans and dates.
    """
    scored = [r for r in rows if r.get("angle") is not None]
    if not scored:
        for r in rows:
            r["angle_grade"], r["angle_percentile"] = "unknown", None
        return

    ordered = sorted(scored, key=lambda r: abs(r["angle"]))
    n = len(ordered)
    for i, row in enumerate(ordered):
        pct = 100.0 * i / max(1, n - 1) if n > 1 else 100.0
        row["angle_percentile"] = round(pct, 0)
        row["angle_grade"] = GRADES[min(3, int(pct // 25))]
    for r in rows:
        if r.get("angle") is None:
            r["angle_grade"], r["angle_percentile"] = "unknown", None


# ------------------------------------------------------------- detection --

WHIPSAW_THRESHOLD = 3


def detect_crossovers(
    fast: pd.DataFrame,
    slow: pd.DataFrame,
    closes: pd.DataFrame,
    basis: pd.DataFrame,
    lookback: int,
    direction: str = "both",
    slope_window: int = 4,
    exclude_whipsaw: bool = False,
    min_angle: float = 0.0,
) -> list[dict]:
    """
    fast/slow : the two lines to compare (date x symbol)
    closes    : closing prices, for reporting
    basis     : what to measure slope against. For moving averages that's the
                slow average itself; for MACD, which oscillates around zero
                and would make a percentage meaningless, it's the share price.
    """
    spread = fast - slow
    above = spread > 0
    comparable = spread.notna() & spread.shift(1).notna()

    bull_all = above & ~above.shift(1, fill_value=False) & comparable
    bear_all = ~above & above.shift(1, fill_value=False) & comparable

    window = closes.index[-lookback:] if lookback < len(closes) else closes.index
    bull_w, bear_w = bull_all.loc[window], bear_all.loc[window]

    last_day = closes.index[-1]
    idx_pos = {d: i for i, d in enumerate(closes.index)}
    rows: list[dict] = []

    for symbol in closes.columns:
        b_days = list(bull_w.index[bull_w[symbol].fillna(False)])
        s_days = list(bear_w.index[bear_w[symbol].fillna(False)])
        if direction == "bullish":
            s_days = []
        elif direction == "bearish":
            b_days = []
        if not b_days and not s_days:
            continue

        latest_bull = b_days[-1] if b_days else None
        latest_bear = s_days[-1] if s_days else None
        if latest_bear is None or (latest_bull is not None and latest_bull >= latest_bear):
            when, kind = latest_bull, "bullish"
        else:
            when, kind = latest_bear, "bearish"

        sign = 1.0 if kind == "bullish" else -1.0

        # Slopes measured over the run of sessions ending on the crossover day,
        # which is the movement that actually caused the cross.
        end = idx_pos[when] + 1
        start = max(0, end - slope_window)
        f_win = fast[symbol].to_numpy()[start:end]
        s_win = slow[symbol].to_numpy()[start:end]
        base_val = basis[symbol].to_numpy()[end - 1]

        f_slope = _slope_pct_per_day(f_win, base_val)
        s_slope = _slope_pct_per_day(s_win, base_val)
        angle = crossing_angle(f_slope, s_slope)
        signed_angle = None if angle is None else sign * angle

        if min_angle > 0 and (signed_angle is None or signed_angle < min_angle):
            continue

        crossings = len(b_days) + len(s_days)
        whipsaw = crossings >= WHIPSAW_THRESHOLD
        if exclude_whipsaw and whipsaw:
            continue

        f_now, s_now = fast.at[last_day, symbol], slow.at[last_day, symbol]
        base_now = basis.at[last_day, symbol]
        if pd.notna(f_now) and pd.notna(s_now) and pd.notna(base_now) and base_now:
            separation = sign * float((f_now - s_now) / abs(base_now) * 100.0)
        else:
            separation = None

        cross_close = closes.at[when, symbol]
        series = closes[symbol].dropna()
        last_px = float(series.iloc[-1]) if len(series) else None

        rows.append({
            "symbol": symbol,
            "crossover": kind,
            "crossover_date": when.date().isoformat(),
            "days_since": int((closes.index > when).sum()),
            "close": _num(cross_close),
            "last_close": _num(last_px),
            "fast_at_cross": _num(fast.at[when, symbol]),
            "slow_at_cross": _num(slow.at[when, symbol]),
            "fast_now": _num(f_now),
            "slow_now": _num(s_now),
            "angle": _num(signed_angle, 2),
            "fast_slope_pct": _num(f_slope, 3),
            "slow_slope_pct": _num(s_slope, 3),
            "separation_pct": _num(separation, 2),
            "move_since_pct": _num((last_px - cross_close) / cross_close * 100)
                              if cross_close and last_px else None,
            "crossings": crossings,
            "whipsaw": whipsaw,
            "_when": when,
        })

    # Most recent first, then steepest, then clean before choppy.
    rows.sort(key=lambda r: (r["_when"], not r["whipsaw"], r["angle"] or -999), reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
        row.pop("_when", None)
    assign_grades(rows)
    return rows


def _num(v, places: int = 2):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        return None
    return round(float(v), places)
