Snapshot files live here.

Build one from the repo root:

    cd backend && python -m tools.build_snapshot

That writes `snapshot.json.gz` into this folder. Commit it — the hosted
deployment reads it and never contacts NSE.
