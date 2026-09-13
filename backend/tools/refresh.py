"""
Download any NSE sessions missing from the local cache.

The dashboard does this automatically each time you press Generate, so you
rarely need this. It's handy for the very first run, when there is a lot to
fetch and you'd rather watch progress in a terminal than a spinner.

    python -m tools.refresh --days 200
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, nse  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Refresh the local NSE price cache.")
    ap.add_argument("--days", type=int, default=200, help="trading sessions to hold")
    args = ap.parse_args()

    before = nse.cache_stats()
    print(f"Cache: {config.CACHE_DIR}")
    print(f"Holding {before['cached_days']} sessions ({before['size_mb']} MB)\n")
    print(f"Checking NSE for anything missing in the last {args.days} sessions.")
    print("The first run downloads a lot and can take a few minutes.\n")

    try:
        panel = nse.load_panel(trading_days_needed=args.days)
    except nse.NSEUnavailable as exc:
        print(f"Failed: {exc}\n")
        print("If NSE refused the connection you are probably on a VPN or a")
        print("cloud IP range. Try a normal home or office connection.")
        raise SystemExit(1)

    after = nse.cache_stats()
    print(f"Latest session: {panel.latest_session}")
    print(f"Downloaded {panel.downloaded} new, reused {panel.from_cache} cached.")
    print(f"Cache now holds {after['cached_days']} sessions ({after['size_mb']} MB).")
    if panel.failed:
        print(f"\n{len(panel.failed)} day(s) could not be fetched:")
        for msg in panel.failed[:5]:
            print(f"  {msg}")


if __name__ == "__main__":
    main()
