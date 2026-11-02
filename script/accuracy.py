#!/usr/bin/env python3
"""Measure how good the arrival estimate is, against the vehicles themselves.

Every poll the board of every served stop is computed, exactly as the
integration does. Every vehicle is also watched along its line: the moment it
passes a stop (its position along the trip crosses the stop's) is that stop's
real arrival, interpolated between the two fixes around it. Each earlier
prediction for that vehicle at that stop is then scored.

    TRANZY_API_KEY=... script/accuracy.py --agency 4 --minutes 90 --out samples.jsonl
    script/accuracy.py --report samples.jsonl

The report gives the error by how far ahead the prediction was made, separately
for direct rows and for the ones via the terminus, and the speed and the wait
at the terminus that would have fitted best.

One request per poll; 90 minutes at 30 s is 180 requests.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import statistics
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from board import STATIC, get, model  # noqa: E402

SPEED = 20.0
LAYOVER = timedelta(minutes=5)
HORIZON = timedelta(minutes=60)
MAX_AGE = timedelta(minutes=5)
SAMPLE_EVERY = timedelta(minutes=2)  # keep one prediction per vehicle/stop this often
MAX_JUMP_M = 3000  # a bigger jump between two fixes is a glitch, not a pass


def load_index(key: str, agency: str):
    cache = pathlib.Path.home() / ".cache/ha-tranzy" / agency
    cache.mkdir(parents=True, exist_ok=True)
    data = {}
    for name in STATIC:
        f = cache / f"{name}.json"
        if not f.exists() or time.time() - f.stat().st_mtime > 86400:
            f.write_text(json.dumps(get(name, key, agency)))
        data[name] = json.loads(f.read_text())
    return model.TransitIndex.build(**data)


def collect(args) -> None:
    key = os.environ["TRANZY_API_KEY"]
    idx = load_index(key, args.agency)
    stops = list(idx.trips_by_stop)
    out = open(args.out, "a", buffering=1)
    # (stop, vehicle) -> list of predictions not yet scored
    pending: dict[tuple[int, str], list[dict]] = defaultdict(list)
    last_kept: dict[tuple[int, str], datetime] = {}
    # vehicle -> (trip_id, along, timestamp) of the previous fix
    prev: dict[str, tuple[str, float, datetime]] = {}
    end = datetime.now(UTC) + timedelta(minutes=args.minutes)
    scored = 0
    while datetime.now(UTC) < end:
        t0 = time.monotonic()
        try:
            vehicles = get("vehicles", key, args.agency)
        except Exception as err:  # noqa: BLE001 — keep polling through hiccups
            print("fetch failed:", err, file=sys.stderr)
            time.sleep(args.interval)
            continue
        now = datetime.now(UTC)
        positions = idx.locate(vehicles, now, MAX_AGE)

        # 1. predictions
        for stop_id in stops:
            for a in idx.arrivals(stop_id, positions, now, SPEED, LAYOVER, HORIZON):
                k = (stop_id, a.vehicle)
                if k in last_kept and now - last_kept[k] < SAMPLE_EVERY:
                    continue
                last_kept[k] = now
                pending[k].append(
                    {"made": now, "pred": a.arrival, "dist": a.distance_m, "via": a.via_terminal, "route": a.route}
                )

        # 2. real passes
        for p in positions:
            before = prev.get(p.label)
            prev[p.label] = (p.trip_id, p.along, p.timestamp)
            if before is None or before[0] != p.trip_id or p.timestamp <= before[2]:
                continue
            a0, a1 = before[1], p.along
            if not (a0 < a1 <= a0 + MAX_JUMP_M):
                continue
            trip = idx.trips[p.trip_id]
            order = list(trip.stops)
            for stop_id, at in trip.stops.items():
                if stop_id == order[-1] or not (a0 < at <= a1):
                    continue
                frac = (at - a0) / (a1 - a0)
                actual = before[2] + (p.timestamp - before[2]) * frac
                for pr in pending.pop((stop_id, p.label), []):
                    if pr["made"] > actual:
                        continue
                    out.write(
                        json.dumps(
                            {
                                "stop": stop_id,
                                "vehicle": p.label,
                                "route": pr["route"],
                                "via": pr["via"],
                                "dist": pr["dist"],
                                "lead_min": round((actual - pr["made"]).total_seconds() / 60, 2),
                                "err_min": round((pr["pred"] - actual).total_seconds() / 60, 2),
                                "made": pr["made"].isoformat(),
                                "actual": actual.isoformat(),
                            }
                        )
                        + "\n"
                    )
                    scored += 1

        # 3. forget predictions that never came true (vehicle left service, etc.)
        stale = now - HORIZON - timedelta(minutes=10)
        for k in [k for k, v in pending.items() if v and v[-1]["made"] < stale]:
            del pending[k]
        print(f"{now:%H:%M:%S} vehicles {len(positions)} pending {sum(map(len, pending.values()))} scored {scored}", flush=True)
        time.sleep(max(0.0, args.interval - (time.monotonic() - t0)))


def report(path: str) -> None:
    rows = [json.loads(line) for line in open(path)]
    print(f"{len(rows)} scored predictions, {len({(r['stop'], r['vehicle'], r['actual']) for r in rows})} real arrivals\n")
    buckets = [(0, 2), (2, 5), (5, 10), (10, 20), (20, 40), (40, 60)]
    print("error = predicted - real, minutes (negative: the board said earlier than it came)")
    print(f"{'kind':7} {'ahead':>8} {'n':>6} {'median':>7} {'mean|e|':>8} {'p90|e|':>7} {'within 2':>9}")
    for via in (False, True):
        for lo, hi in buckets:
            errs = [r["err_min"] for r in rows if r["via"] == via and lo <= r["lead_min"] < hi]
            if len(errs) < 5:
                continue
            abs_e = sorted(abs(e) for e in errs)
            print(
                f"{'via' if via else 'direct':7} {f'{lo}-{hi}':>8} {len(errs):>6} {statistics.median(errs):>7.1f} "
                f"{statistics.mean(abs_e):>8.1f} {abs_e[int(len(abs_e) * 0.9)]:>7.1f} "
                f"{sum(e <= 2 for e in abs_e) / len(abs_e):>8.0%}"
            )
    # the speed that would have fitted: distance over the real travel time
    direct = [r for r in rows if not r["via"] and r["dist"] >= 1000 and r["lead_min"] >= 2]
    if direct:
        speeds = [r["dist"] / 1000 / (r["lead_min"] / 60) for r in direct]
        print(f"\nfitted speed (direct, ≥1 km): median {statistics.median(speeds):.1f} km/h over {len(speeds)}")
    via = [r for r in rows if r["via"]]
    if via:
        # the wait that would have fitted, at the fitted speed: real time minus driving time
        v = statistics.median(speeds) if direct else SPEED
        waits = [r["lead_min"] - r["dist"] / 1000 / v * 60 for r in via]
        print(f"fitted wait at the terminus (via, at that speed): median {statistics.median(waits):.1f} min over {len(waits)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agency", default="4")
    ap.add_argument("--minutes", type=float, default=90)
    ap.add_argument("--interval", type=float, default=30)
    ap.add_argument("--out", default="accuracy.jsonl")
    ap.add_argument("--report")
    a = ap.parse_args()
    if a.report:
        report(a.report)
    else:
        collect(a)


if __name__ == "__main__":
    main()
