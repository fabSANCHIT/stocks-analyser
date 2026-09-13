"""
Save the index membership list so the hosted app has a fallback.

The app fetches this list live from niftyindices.com. That usually works, but
if the site refuses your host the app needs a copy bundled with the code.
Membership changes about twice a year, so committing one costs nothing.

    python -m tools.build_universe
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, universe  # noqa: E402


def main():
    print(f"Fetching {config.UNIVERSE_INDEX_NAME} constituents...\n")
    try:
        payload = universe.load(force=True)
    except universe.UniverseUnavailable as exc:
        print(f"Failed: {exc}")
        raise SystemExit(1)

    out = config.UNIVERSE_FILE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))

    print(f"Wrote {out}")
    print(f"  {len(payload['members'])} stocks in {payload['index']}")
    print(f"  first few: {', '.join(m['symbol'] for m in payload['members'][:6])}")
    print("\nNext: commit data/universe.json so the hosted app can use it.")


if __name__ == "__main__":
    main()
