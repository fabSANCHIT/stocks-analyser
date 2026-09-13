"""
Build the price snapshot the hosted version serves.

Run this on a machine NSE will actually answer - your own laptop:

    cd backend
    python -m tools.build_snapshot

Then commit data/snapshot.json.gz and redeploy. Re-run it after each close to
refresh. Everything the hosted app shows comes from this one file.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, snapshot  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Build an NSE price snapshot.")
    ap.add_argument("--days", type=int, default=300, help="trading sessions to include")
    ap.add_argument("--max-stocks", type=int, default=150, help="index members to include")
    ap.add_argument("--out", type=Path, default=config.SNAPSHOT_PATH)
    args = ap.parse_args()

    print(f"Collecting {args.days} sessions for up to {args.max_stocks} stocks.")
    print("The first run downloads a lot from NSE and can take a few minutes.\n")

    try:
        path = snapshot.write(args.out, days=args.days, max_stocks=args.max_stocks)
    except Exception as exc:
        print(f"Failed: {exc}\n")
        print("If NSE refused the connection, you are probably on a cloud or VPN")
        print("IP range. Run this from a normal home or office connection.")
        raise SystemExit(1)

    payload = snapshot.load(path)
    size_kb = path.stat().st_size / 1024
    print(f"Wrote {path}  ({size_kb:.0f} KB)")
    print(f"  {len(payload['symbols'])} stocks")
    print(f"  {len(payload['dates'])} sessions, {payload['dates'][0]} to {payload['dates'][-1]}")
    print("\nNext: git add data/snapshot.json.gz && git commit && git push")


if __name__ == "__main__":
    main()
