"""
The strategy registry.

To add an indicator, write a class with the same four pieces as the two below
and add it to REGISTRY at the bottom. The frontend builds its input form and
its results table from `params` and `columns`, so no React needs touching.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd

from . import indicators as ind


@dataclass
class Param:
    """One input box. Becomes a form field in the browser."""
    key: str
    label: str
    default: int | float | bool | str
    kind: str = "int"          # int | float | bool | choice
    min: float | None = None
    max: float | None = None
    hint: str = ""
    choices: list[dict] | None = None


@dataclass
class Column:
    """One results column. Becomes a table header in the browser."""
    key: str
    label: str
    kind: str = "text"         # text | money | percent | number | date | tag | angle
    hint: str = ""


@dataclass
class Strategy:
    id: str
    label: str
    tagline: str
    explainer: str
    params: list[Param] = field(default_factory=list)
    columns: list[Column] = field(default_factory=list)

    def min_history(self, p: dict) -> int:
        raise NotImplementedError

    def run(self, closes: pd.DataFrame, p: dict) -> list[dict]:
        raise NotImplementedError

    def spec(self) -> dict:
        d = asdict(self)
        d.pop("params"), d.pop("columns")
        d["params"] = [asdict(x) for x in self.params]
        d["columns"] = [asdict(x) for x in self.columns]
        return d


# Columns every crossover strategy shares.
_COMMON_HEAD = [
    Column("rank", "#", "number"),
    Column("symbol", "Ticker", "text"),
    Column("company", "Company", "text"),
    Column("crossover", "Crossover", "tag"),
    Column("crossover_date", "Date", "date"),
]
_COMMON_TAIL = [
    Column("angle", "Angle", "angle", "Degrees between the two lines at the crossover"),
    Column("separation_pct", "Gap now", "percent", "How far apart they are today"),
    Column("move_since_pct", "Since", "percent", "Price move since the crossover"),
]

_SHARED_PARAMS = [
    Param("lookback_days", "Lookback Days", 30, "int", 1, 250, "how far back to search"),
    Param("max_stocks", "Max Stocks", 100, "int", 1, 500, "top N of the index"),
    Param("direction", "Direction", "both", "choice", choices=[
        {"value": "both", "label": "Both"},
        {"value": "bullish", "label": "Bullish only"},
        {"value": "bearish", "label": "Bearish only"},
    ]),
    Param("min_angle", "Min angle", 0, "float", 0, 45, "0 shows everything"),
    Param("exclude_whipsaw", "Hide choppy stocks", False, "bool"),
]


# --------------------------------------------------------------------------

class SmaCrossover(Strategy):
    def __init__(self):
        super().__init__(
            id="sma_crossover",
            label="SMA crossover",
            tagline="Short average cuts through long average",
            explainer=(
                "The classic trend-following signal. A crossover happens on the day "
                "the short simple average closes through the long one. Slow to fire "
                "and prone to false starts in a sideways market, which is what the "
                "angle and choppy flags are there to expose."
            ),
            params=[
                Param("short_window", "Short SMA", 6, "int", 2, 200, "days"),
                Param("long_window", "Long SMA", 30, "int", 3, 400, "days"),
                *_SHARED_PARAMS,
            ],
            columns=[
                *_COMMON_HEAD,
                Column("close", "Close", "money", "Closing price on the crossover day"),
                Column("fast_at_cross", "Short SMA", "money"),
                Column("slow_at_cross", "Long SMA", "money"),
                *_COMMON_TAIL,
            ],
        )

    def validate(self, p: dict):
        if p["short_window"] >= p["long_window"]:
            raise ValueError("Short SMA must be smaller than long SMA.")

    def min_history(self, p: dict) -> int:
        return p["long_window"] + p["lookback_days"] + 5

    def run(self, closes: pd.DataFrame, p: dict) -> list[dict]:
        self.validate(p)
        need = p["long_window"] + 2
        if len(closes) < need:
            raise ValueError(
                f"Need at least {need} sessions for a {p['long_window']}-day average. "
                f"Only {len(closes)} are loaded."
            )
        fast = ind.sma(closes, p["short_window"])
        slow = ind.sma(closes, p["long_window"])
        return ind.detect_crossovers(
            fast=fast, slow=slow, closes=closes,
            basis=slow,  # percentage slope measured against the average itself
            lookback=p["lookback_days"], direction=p["direction"],
            exclude_whipsaw=p["exclude_whipsaw"], min_angle=p["min_angle"],
        )


class MacdCrossover(Strategy):
    def __init__(self):
        super().__init__(
            id="macd_crossover",
            label="MACD crossover",
            tagline="MACD line cuts through its signal line",
            explainer=(
                "MACD is the gap between a 12-day and a 26-day exponential average, "
                "smoothed again over 9 days to give the signal line. Because both "
                "inputs are exponential it reacts faster than an SMA pair and fires "
                "earlier in a turn. Whether the cross happened above or below the "
                "zero line matters: below zero is a bounce inside a downtrend, above "
                "zero is a continuation of an uptrend."
            ),
            params=[
                Param("fast_span", "Fast EMA", 12, "int", 2, 200, "days"),
                Param("slow_span", "Slow EMA", 26, "int", 3, 400, "days"),
                Param("signal_span", "Signal EMA", 9, "int", 2, 100, "days"),
                *_SHARED_PARAMS,
            ],
            columns=[
                *_COMMON_HEAD,
                Column("close", "Close", "money"),
                Column("fast_at_cross", "MACD", "number", "MACD line on the crossover day"),
                Column("slow_at_cross", "Signal", "number"),
                Column("zero_side", "Zero line", "text", "Was the cross above or below zero"),
                *_COMMON_TAIL,
            ],
        )

    def validate(self, p: dict):
        if p["fast_span"] >= p["slow_span"]:
            raise ValueError("Fast EMA must be smaller than slow EMA.")

    def min_history(self, p: dict) -> int:
        # An EMA needs a long warm-up before it settles. Three times the slow
        # span is the usual rule of thumb.
        return p["slow_span"] * 3 + p["signal_span"] + p["lookback_days"] + 5

    def run(self, closes: pd.DataFrame, p: dict) -> list[dict]:
        self.validate(p)
        need = p["slow_span"] + p["signal_span"] + 2
        if len(closes) < need:
            raise ValueError(
                f"Need at least {need} sessions for MACD "
                f"({p['fast_span']},{p['slow_span']},{p['signal_span']}). "
                f"Only {len(closes)} are loaded."
            )
        macd, signal, hist = ind.macd_lines(
            closes, p["fast_span"], p["slow_span"], p["signal_span"]
        )
        rows = ind.detect_crossovers(
            fast=macd, slow=signal, closes=closes,
            # MACD oscillates around zero, so a percentage of MACD itself would
            # blow up near the crossover. Measure against the share price.
            basis=closes,
            lookback=p["lookback_days"], direction=p["direction"],
            exclude_whipsaw=p["exclude_whipsaw"], min_angle=p["min_angle"],
        )
        for r in rows:
            v = r.get("fast_at_cross")
            r["zero_side"] = "—" if v is None else ("above" if v > 0 else "below")
            r["histogram"] = ind._num(hist.at[pd.Timestamp(r["crossover_date"]), r["symbol"]], 3) \
                if pd.Timestamp(r["crossover_date"]) in hist.index else None
        return rows


REGISTRY: dict[str, Strategy] = {
    s.id: s for s in (SmaCrossover(), MacdCrossover())
}

DEFAULT_STRATEGY = "macd_crossover"


def get(strategy_id: str) -> Strategy:
    if strategy_id not in REGISTRY:
        raise KeyError(
            f"Unknown strategy '{strategy_id}'. Available: {', '.join(REGISTRY)}"
        )
    return REGISTRY[strategy_id]


def defaults_for(strategy_id: str) -> dict:
    return {p.key: p.default for p in get(strategy_id).params}
