"""
Compress the raw Unusual Whales snapshot tree into a compact, queryable flow series.

The sweep writes ~5 MB JSON per symbol per cycle (~18 GB and growing) — real
institutional options flow, but unusable in that form and a migration anchor. This
walks the tree and distils each snapshot to one directional-flow record via
UWFlowSignalEngine, writing per-symbol jsonl under app/data/uw_flow/.

Idempotent (dedups by timestamp), so it is safe to re-run to catch up new snapshots.
Once the compact series is trusted, the raw blobs can be pruned — 18 GB -> ~1 MB.

    python backfill_uw_flow.py
"""
import glob
import json
import os

from app.services.uw_flow_signal_engine import UWFlowSignalEngine


def main():
    eng = UWFlowSignalEngine()
    files = glob.glob("app/data/runtime/institutional_signal_snapshots/*/*/*.json")
    ok = skipped = 0
    for fp in files:
        try:
            with open(fp) as f:
                snap = json.load(f)
        except Exception:
            skipped += 1
            continue
        if eng.record(snap):
            ok += 1
        else:
            skipped += 1

    raw_gb = sum(os.path.getsize(f) for f in files) / 1e9
    comp_mb = sum(os.path.getsize(f) for f in glob.glob("app/data/uw_flow/*.jsonl")) / 1e6
    print(f"snapshots: {len(files)} | flow records: {ok} | skipped: {skipped}")
    print(f"raw {raw_gb:.1f} GB -> compact {comp_mb:.2f} MB")


if __name__ == "__main__":
    main()
