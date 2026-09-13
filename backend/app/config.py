"""All tunable settings live here. Change these, not the code below them."""
from pathlib import Path
import os

# True on Vercel and most other serverless hosts, where the only writable
# directory is /tmp and it does not survive between requests.
SERVERLESS = bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))

# Where daily price files are stored. Delete this folder to force a full refetch.
_default_cache = Path("/tmp/nse-cache") if SERVERLESS else Path.home() / ".nse_dashboard_cache"
CACHE_DIR = Path(os.getenv("NSE_CACHE_DIR", _default_cache))

# A prebuilt snapshot of closing prices, used only as a last resort when the
# live provider cannot be reached. See app/snapshot.py.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_snap = Path(os.getenv("NSE_SNAPSHOT", "data/snapshot.json.gz"))
# A relative path is resolved against the repo root, not the working directory,
# because serverless hosts run from somewhere unpredictable.
SNAPSHOT_PATH = _snap if _snap.is_absolute() else (_REPO_ROOT / _snap)

# Serverless hosts can't collect from NSE, so never let them try.
SNAPSHOT_ONLY = os.getenv("NSE_SNAPSHOT_ONLY", "0") == "1"
BHAV_DIR = CACHE_DIR / "bhav"
META_DIR = CACHE_DIR / "meta"

# How many NSE files to download at once. Keep this low and polite.
# NSE will throttle you if you hammer it. 4 is a safe default.
MAX_WORKERS = int(os.getenv("NSE_MAX_WORKERS", "4"))

# Retries per file before giving up on that day.
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.5

# NSE publishes each day's file after the close, usually early evening IST.
# So "no file yet" for a recent date means "not published yet", while for an
# old date it means a holiday. We only treat a missing file as permanent once
# it is this many days old; anything newer is re-checked.
NODATA_LOCK_DAYS = int(os.getenv("NSE_NODATA_LOCK_DAYS", "6"))

# How long to wait before asking again about a recent date that had no file.
# This is what makes pressing Generate later in the evening pick up today's
# session instead of serving yesterday's forever.
NODATA_RECHECK_MINUTES = int(os.getenv("NSE_NODATA_RECHECK_MINUTES", "15"))

# --------------------------------------------------------------------------
# Where prices come from.
#   yahoo  - Yahoo Finance. Works from cloud hosts, prices are split and
#            dividend adjusted. Needed for any hosted deployment.
#   nse    - NSE's own daily archive. More authoritative and gives delivery
#            data, but NSE blocks data-centre IPs so it only works locally.
# --------------------------------------------------------------------------
DATA_PROVIDER = os.getenv("DATA_PROVIDER", "yahoo").strip().lower()

# Yahoo tuning. Chunking and backoff exist because Yahoo rate-limits shared
# cloud IP addresses, which is exactly what a serverless host gives you.
YAHOO_CHUNK_SIZE = int(os.getenv("YAHOO_CHUNK_SIZE", "40"))
YAHOO_CHUNK_PAUSE_SECONDS = float(os.getenv("YAHOO_CHUNK_PAUSE", "0.4"))
YAHOO_MAX_RETRIES = int(os.getenv("YAHOO_MAX_RETRIES", "3"))
YAHOO_BACKOFF_SECONDS = float(os.getenv("YAHOO_BACKOFF", "1.2"))
YAHOO_TIMEOUT_SECONDS = int(os.getenv("YAHOO_TIMEOUT", "25"))
# How long a download is reused. A warm serverless instance answers repeat
# scans from memory, so pressing Generate twice costs one fetch, not two.
YAHOO_CACHE_MINUTES = int(os.getenv("YAHOO_CACHE_MINUTES", "10"))

# Which index the scanner runs on.
UNIVERSE_INDEX_CATEGORY = "BroadMarketIndices"
UNIVERSE_INDEX_NAME = "Nifty 100"

# Constituent lists change rarely. Refetch after this many days.
UNIVERSE_TTL_DAYS = 7

# Fallback membership list, used when the index CSV can't be reached. Generate
# it locally with tools/build_universe.py and commit it.
UNIVERSE_FILE = _REPO_ROOT / "data" / "universe.json"

# Only scan normal rolling-settlement equity. Excludes bonds, ETFs, SME.
EQUITY_SERIES = {"EQ", "BE"}

# Frontend dev server origins allowed to call this API.
# Refreshing a hosted deployment. The server can't reach NSE itself, so it asks
# GitHub Actions to rebuild the snapshot on a runner instead. Set both of these
# in your Vercel project settings to enable the Refresh button when hosted.

CORS_ORIGINS = [o for o in os.getenv(
    "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",") if o]

for _d in (BHAV_DIR, META_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # read-only filesystem; snapshot mode doesn't need these
