# NSE Scanner

A Nifty 100 crossover scanner built on NSE India's public end-of-day archives.
No broker account, no API key, no login, no subscription.

Two strategies ship with it — MACD 12/26/9 and SMA 6/30 — and adding a third
means writing one Python class.

---

## What you need

- Python 3.9 or newer
- Node.js 18 or newer
- An Indian internet connection (see *Known limits*)

## Run it on Windows

Install these two first, if you haven't:

- **Python** from python.org — on the first screen, tick **Add Python to PATH**.
  This is easy to miss and everything fails without it.
- **Node.js** from nodejs.org — take the LTS version, default options.

Then, in the project folder:

1. Double-click **`setup.bat`**. Installs everything. Once only, takes a few minutes.
2. Double-click **`start.bat`**. Two black windows open — leave both running —
   and your browser opens to the dashboard.

To stop, close the two black windows.

Prices come from Yahoo Finance by default, which needs no setup and works from
anywhere. If you'd rather use NSE's own archive locally, run `check-nse.bat`
first to confirm NSE answers your connection, then set `DATA_PROVIDER=nse` in
`backend/app/config.py`.

### Or from inside VS Code

Open the project folder, then **Terminal → Run Build Task** (`Ctrl+Shift+B`).
That starts the backend and frontend together in two panels. Open
http://localhost:5173 yourself.

`.vscode/launch.json` is set up too, so **F5** runs the backend with
breakpoints working.

### If something goes wrong

**`py is not recognized`** — Python isn't on PATH. Reinstall it and tick *Add
Python to PATH*, or use the full path to python.exe.

**`npm is not recognized`** — Node.js isn't installed, or you need to reopen
the terminal after installing it.

**`running scripts is disabled on this system`** — only affects PowerShell. The
`.bat` files avoid it entirely; use those. To fix PowerShell anyway, run this
once in a PowerShell window:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

**Port 8000 already in use** — something else is on that port. Change it in
`start.bat` and in `frontend/vite.config.js` so they match.

### On macOS or Linux

```bash
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && uvicorn app.main:app --reload --port 8000
# in a second terminal
cd frontend && npm install && npm run dev
```

---

## The tabs

**Overview** — how the last session closed: advance/decline breadth, top
gainers and losers, most traded by value, plus what price data you hold on disk.

**Signals** — the scanner. Pick a strategy, set its inputs, press *Generate
signals*. Ranked with the most recent crossover first.

Every press checks NSE for sessions published since your last scan and
downloads only what's missing, so the data refreshes itself. The line above the
table tells you what happened — *Prices to 12 Sep · 1 new session pulled from
NSE*, or *already up to date*. Sessions you already have are never refetched,
which is why a refresh normally takes under a second.

NSE publishes each day's file after the close, usually early evening IST. Press
Generate before that and you'll get yesterday's close; press it again later and
today's appears.

**Stock** — click any ticker to see its price with both averages, a MACD panel
below, and every crossover marked with its angle.

---

## Crossover strength: the angle

Each signal reports the angle in degrees between the two lines where they
crossed. Steeper means the lines were separating faster, which is a more
decisive signal than a shallow drift across.

Two things that took care to get right:

**The angle has to be scale-free.** A raw slope in rupees-per-day would rank
stocks by share price rather than by momentum — a ₹2,800 stock and a ₹95 stock
making identical percentage moves produce wildly different raw slopes. So each
line's slope is measured as *percent of price per day* before the angle is
taken. Verified: the same price path scaled 30× returns an identical angle.

**Grades are relative, not absolute.** Measured across the Nifty 100, SMA 6/30
crossovers average about 32° while MACD 12/26/9 crossovers average about 6°.
The two indicators simply live on different scales, and any indicator you add
later will have a scale of its own. So *flat / mild / firm / steep* are
quartiles of the current scan rather than fixed thresholds — a new strategy
gets sensible grades with no threshold tuning. The raw degrees are always shown
and stay comparable across scans and dates.

Beside the angle, two other columns matter:

| Column | What it means |
|---|---|
| Gap now | How far apart the lines are **today**, signed so positive always means the signal is still working |
| Since | Price move since the crossover |
| choppy | This stock crossed 3+ times in the window |

That *choppy* flag earns its place. Two lines sitting on top of each other cross
constantly, and since they always have a crossover "today" they would otherwise
dominate a date-sorted ranking. Tick **Hide choppy stocks** to drop them, or set
**Min angle** above zero.

---

## Adding a strategy

One class in `backend/app/strategies.py`, then add it to `REGISTRY`. That's it —
the frontend builds its input form and results table from what the backend
declares, so no React changes.

```python
class RsiCrossover(Strategy):
    def __init__(self):
        super().__init__(
            id="rsi_cross", label="RSI 14", tagline="RSI crosses its average",
            explainer="...",
            params=[Param("period", "RSI period", 14, "int", 2, 100), *_SHARED_PARAMS],
            columns=[*_COMMON_HEAD, Column("close", "Close", "money"), *_COMMON_TAIL],
        )

    def min_history(self, p):
        return p["period"] * 3 + p["lookback_days"] + 5

    def run(self, closes, p):
        fast, slow = ...            # your two lines
        return ind.detect_crossovers(fast, slow, closes, basis=closes,
                                     lookback=p["lookback_days"],
                                     direction=p["direction"],
                                     exclude_whipsaw=p["exclude_whipsaw"],
                                     min_angle=p["min_angle"])
```

`detect_crossovers` handles ranking, angles, grading and whipsaw detection, so
a new strategy only has to produce its fast and slow lines.

One thing to get right: the `basis` argument is what percentage slopes are
measured against. For moving averages, which track price, pass the slow average.
For an oscillator like MACD that swings around zero, pass `closes` — a
percentage of a number near zero would blow up exactly where the crossover is.

---

## Where prices come from

Two providers ship with the app. `DATA_PROVIDER` in `backend/app/config.py`
picks between them.

**`yahoo` (default).** Yahoo Finance, via `yfinance`, using `.NS` tickers.
Yahoo answers cloud hosts, so this is what makes a hosted deployment able to
refresh on demand. Prices come back **split and dividend adjusted**, which
removes the false crossovers that raw NSE prices produce around an ex-date — a
real accuracy gain, not just a convenience.

**`nse`.** NSE's own daily archive. More authoritative, and the only one that
carries delivery volumes, but NSE refuses data-centre IPs so it only works from
your own machine.

Requests are batched 40 tickers at a time and held in memory for 10 minutes, so
pressing Generate twice costs one fetch rather than two.

### The honest risk with Yahoo

Yahoo rate-limits by IP, and cloud hosts share IPs between many customers. A
`429 Too Many Requests` is a normal event there, not an exception — it's widely
reported on Streamlit Cloud and similar platforms, and Vercel is the same shape
of problem.

The app is built to absorb this: chunked requests, exponential backoff with
jitter, an in-memory cache, and a snapshot fallback so a rate-limited scan
serves slightly older prices with a clear label instead of an error page.

It should be fine for personal use, where you press Generate a few times a day.
I can't promise it never trips. If it does, waiting a minute almost always
clears it, and the fallback below removes the problem entirely.

---

## Hosting on Vercel

This gives you a URL you can open from any device, with the Refresh button
pulling live prices on demand.

**1. Save the membership list.** Double-click `build-universe.bat`. Writes
`data/universe.json`, about 5 KB.

The app fetches this list live too, but niftyindices.com may refuse a cloud
host the way nseindia.com does. Membership changes roughly twice a year, so a
committed copy is cheap insurance. This is the only step that needs your own
machine — prices themselves come from Yahoo at runtime.

**2. Push to GitHub**, `data/universe.json` included.

**3. Import the repo at vercel.com/new.** Change no build settings;
`vercel.json` specifies them. Deploy.

That's it. Open the URL on your phone, press **Refresh prices**, and it pulls
the latest close.

### What to expect

**Cold starts.** The first request after idle takes a few seconds — pandas and
numpy are large imports. Normal.

**Bundle size.** The Python function comes to roughly 175 MB against Vercel's
250 MB limit. Comfortable, but not unlimited: if you add heavy packages later
and the deploy fails on size, that's why. `nselib` is already excluded from the
root `requirements.txt` for this reason.

**Function timeout** is set to 60 seconds in `vercel.json`. A scan of 100 stocks
takes a few seconds once Yahoo responds.

### Optional safety net

If Yahoo rate-limits you at a bad moment, a committed snapshot gives the app
something to fall back on rather than erroring. Run `build-snapshot.bat` and
commit `data/snapshot.json.gz`. Purely optional — the app works without it, and
it only ever gets used when the live fetch fails.

### If you later want NSE's own data hosted

You can't fetch it from Vercel. The route is `build-snapshot.bat` locally, then
push, as described above — the same snapshot mechanism, used as the primary
source instead of a fallback. Set `NSE_SNAPSHOT_ONLY=1` in the Vercel
environment to force it. Data then refreshes when you rebuild, not on button
press.

---

## Customising it

**Colours, spacing, fonts** — the top block of `frontend/src/styles.css`. Every
value used anywhere is declared there. Green and red are reserved strictly for
direction; the brass accent handles everything else.

**Adding a tab** — a row in the `TABS` array in `frontend/src/App.jsx` plus the
component. Nothing else to wire.

**Which index to scan** — `UNIVERSE_INDEX_NAME` in `backend/app/config.py`.
Nifty 50, Nifty 500, Nifty Midcap 150 and others work unchanged.

**Download politeness** — `MAX_WORKERS` in the same file. Four is safe; raising
it makes NSE more likely to throttle you.

---

## Known limits

**End-of-day only.** NSE's public archives publish after the close, usually
early evening IST. For daily crossovers that is exactly right — a daily signal
is not confirmed until the close. Intraday bars need a paid feed.

**Yahoo rate-limits shared IPs.** On a cloud host a `429` can happen. The app
retries with backoff and falls back to a snapshot if you've committed one. See
*The honest risk with Yahoo*.

**Yahoo's NSE data occasionally has gaps or bad ticks.** It's a free, unofficial
feed. If a signal looks wrong, check the Stock tab chart before acting on it.

**NSE blocks data-centre IPs.** Collection works from home or office and often
fails from cloud hosts and VPNs. This is the single biggest constraint on the
project, and the reason snapshots exist.

**Adjustment depends on the provider.** Yahoo prices are split and dividend
adjusted, so ex-dates are handled. The `nse` provider serves raw prices, where a
split shows as a large fake gap that can register as a false crossover.

**MACD needs a long warm-up.** An exponential average takes roughly three times
its span to settle, so MACD scans load noticeably more history than SMA scans.
This is handled automatically; it is why a MACD scan reports more sessions
loaded.

**Nothing here is advice.** A crossover is a starting point for research, not a
reason to trade.
