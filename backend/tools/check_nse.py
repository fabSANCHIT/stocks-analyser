"""
Does NSE answer this computer?

Everything else depends on this, so run it first:

    python -m tools.check_nse

A pass means you can collect data here. A failure names the actual cause -
which matters, because the underlying library reports a network block as
"no data found for index", and that sends people looking in the wrong place.
"""
import socket
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The two hosts this project reads. Both serve plain files; neither needs a key.
HOSTS = [
    ("niftyindices.com", "https://www.niftyindices.com/IndexConstituent/ind_nifty100list.csv",
     "the Nifty 100 membership list"),
    ("nsearchives.nseindia.com", "https://nsearchives.nseindia.com/",
     "the daily price archive"),
]

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def probe(url: str) -> tuple[bool, str]:
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return True, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        # A 403 is the signature of a blocked address; 404 just means that
        # exact path moved, which still proves the host is reachable.
        if exc.code == 404:
            return True, "HTTP 404 (host reachable)"
        return False, f"HTTP {exc.code} {exc.reason}"
    except urllib.error.URLError as exc:
        return False, f"{type(exc.reason).__name__ if exc.reason else 'URLError'}: {exc.reason}"
    except socket.timeout:
        return False, "timed out"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def advice():
    print("\nNSE did not answer this computer. The usual causes, in order:")
    print("  1. A VPN or proxy is switched on. Turn it off and run this again.")
    print("  2. You're on a work or college network that routes through a")
    print("     data centre. Try a home connection or a phone hotspot.")
    print("  3. You're on a cloud machine. NSE blocks those. Collect the data")
    print("     on a normal computer instead - that's what snapshots are for.")
    print("  4. Antivirus or a firewall is intercepting HTTPS. Allow Python.")


def main() -> int:
    print("Checking whether NSE will talk to this machine.\n")

    print("Step 1 of 3 - can this computer reach the servers at all?")
    reachable = True
    for host, url, what in HOSTS:
        ok, detail = probe(url)
        print(f"  {'OK    ' if ok else 'FAILED'}  {host:26} {detail}   ({what})")
        reachable = reachable and ok
    if not reachable:
        advice()
        return 1

    print("\nStep 2 of 3 - is the library installed and working?")
    try:
        from nselib import capital_market as cm, indices
    except ImportError:
        print("  FAILED  nselib isn't installed in this Python.")
        print("          Activate the environment, then: pip install -r requirements.txt")
        return 1
    try:
        members = indices.constituent_stock_list(
            index_category="BroadMarketIndices", index_name="Nifty 100"
        )
        print(f"  OK      Nifty 100 list: {len(members)} stocks.")
    except Exception as exc:
        print(f"  FAILED  {type(exc).__name__}: {exc}")
        print("\n  The servers responded in step 1, so this is probably NSE")
        print("  changing a file name. Try: pip install --upgrade nselib")
        return 1

    print("\nStep 3 of 3 - can it download a day of prices?")
    for back in range(1, 10):
        day = date.today() - timedelta(days=back)
        if day.weekday() >= 5:
            continue
        try:
            rows = cm.bhav_copy_with_delivery(trade_date=day.strftime("%d-%m-%Y"))
            print(f"  OK      {day}: {len(rows)} rows.\n")
            print("All three passed. You can collect data on this machine.")
            print("Next: run start.cmd, then press 'Download 150 sessions now'")
            print("on the Overview tab.")
            return 0
        except FileNotFoundError:
            print(f"  ...     {day}: nothing published (market holiday), trying earlier.")
        except Exception as exc:
            print(f"  FAILED  {day}: {type(exc).__name__}: {exc}")
            advice()
            return 1

    print("\n  FAILED  No price file found in the last 10 days.")
    print("  Either the market has been shut that long, or the archive moved.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
