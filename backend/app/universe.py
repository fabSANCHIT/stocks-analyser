"""
Index membership.

Kept separate from the price providers and free of any nselib dependency, so a
hosted deployment can load the constituent list without shipping the NSE
archive reader at all.

Three sources are tried in order: a recent cached copy, the official NIFTY
Indices CSV, then a file bundled with the repository. The bundled file matters
because niftyindices.com may refuse a cloud host just as nseindia.com does, and
membership only changes a couple of times a year - so committing it once costs
nothing and removes a runtime dependency.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from . import config

log = logging.getLogger("universe")

CSV_URLS = {
    "Nifty 50": "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv",
    "Nifty 100": "https://www.niftyindices.com/IndexConstituent/ind_nifty100list.csv",
    "Nifty 200": "https://www.niftyindices.com/IndexConstituent/ind_nifty200list.csv",
    "Nifty 500": "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    "Nifty Next 50": "https://www.niftyindices.com/IndexConstituent/ind_niftynext50list.csv",
    "Nifty Midcap 150": "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv",
}

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

_CACHE_FILE = config.META_DIR / "universe.json"


class UniverseUnavailable(RuntimeError):
    pass


def _parse_csv(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    members = []
    for row in reader:
        clean = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        symbol = clean.get("symbol", "").upper()
        if not symbol:
            continue
        members.append({
            "symbol": symbol,
            "company": clean.get("company name") or clean.get("company") or symbol,
            "industry": clean.get("industry") or clean.get("sector") or "",
        })
    return members


def _fetch_live(index_name: str) -> list[dict]:
    url = CSV_URLS.get(index_name)
    if not url:
        raise UniverseUnavailable(
            f"No constituent CSV known for '{index_name}'. "
            f"Known: {', '.join(CSV_URLS)}"
        )
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8-sig", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        raise UniverseUnavailable(f"Could not reach the index list: {exc}") from exc

    members = _parse_csv(body)
    if not members:
        raise UniverseUnavailable("The index CSV downloaded but contained no symbols.")
    return members


def _read(path) -> dict | None:
    try:
        payload = json.loads(path.read_text())
        return payload if payload.get("members") else None
    except Exception:
        return None


def load(force: bool = False) -> dict:
    index_name = config.UNIVERSE_INDEX_NAME

    if not force:
        cached = _read(_CACHE_FILE)
        if cached and cached.get("index") == index_name:
            try:
                age = datetime.now() - datetime.fromisoformat(cached["fetched"])
                if age < timedelta(days=config.UNIVERSE_TTL_DAYS):
                    return cached
            except Exception:
                pass

    try:
        members = _fetch_live(index_name)
        payload = {
            "index": index_name,
            "fetched": datetime.now().isoformat(timespec="seconds"),
            "source": "niftyindices.com",
            "members": members,
        }
        try:
            _CACHE_FILE.write_text(json.dumps(payload, indent=2))
        except OSError:
            pass  # read-only filesystem; the in-request copy is enough
        return payload
    except UniverseUnavailable as exc:
        log.warning("Live index list unavailable: %s", exc)

    for path, label in ((_CACHE_FILE, "stale cache"), (config.UNIVERSE_FILE, "bundled file")):
        found = _read(path)
        if found:
            log.info("Using index list from %s", label)
            return {**found, "source": f"{found.get('source', 'file')} ({label})"}

    raise UniverseUnavailable(
        f"Could not load the {index_name} membership list. The official CSV was "
        f"unreachable and no bundled copy was found at {config.UNIVERSE_FILE}. "
        f"Run 'python -m tools.build_universe' on a machine that can reach "
        f"niftyindices.com, then commit data/universe.json."
    )
