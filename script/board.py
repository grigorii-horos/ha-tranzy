#!/usr/bin/env python3
"""Print the live board of a stop from the command line, without Home Assistant.

    TRANZY_API_KEY=... script/board.py --agency 4 gara
    TRANZY_API_KEY=... script/board.py --agency 4 --stop 802

Static data is cached in ~/.cache/ha-tranzy/<agency>/ for a day.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import sys
import time
import urllib.request
from datetime import UTC, datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("model", ROOT / "custom_components/tranzy/model.py")
model = importlib.util.module_from_spec(spec)
sys.modules["model"] = model
spec.loader.exec_module(model)

API = "https://api.tranzy.ai/v1/opendata"
STATIC = ["routes", "trips", "stops", "stop_times", "shapes"]


def get(path: str, key: str, agency: str) -> list:
    req = urllib.request.Request(f"{API}/{path}", headers={"X-API-KEY": key, "X-Agency-Id": agency})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?", help="part of a stop name")
    ap.add_argument("--agency", default="4")
    ap.add_argument("--stop", type=int, action="append", default=[])
    ap.add_argument("--speed", type=float, default=20.0)
    ap.add_argument("--layover", type=float, default=5.0)
    ap.add_argument("--rows", type=int, default=8)
    a = ap.parse_args()
    key = os.environ["TRANZY_API_KEY"]

    cache = pathlib.Path.home() / ".cache/ha-tranzy" / a.agency
    cache.mkdir(parents=True, exist_ok=True)
    data = {}
    for name in STATIC:
        f = cache / f"{name}.json"
        if not f.exists() or time.time() - f.stat().st_mtime > 86400:
            f.write_text(json.dumps(get(name, key, a.agency)))
        data[name] = json.loads(f.read_text())

    t0 = time.perf_counter()
    idx = model.TransitIndex.build(**data)
    print(f"index: {len(idx.trips)} trips, {len(idx.trips_by_stop)} served stops, {time.perf_counter() - t0:.2f}s")

    stops = list(a.stop)
    if a.query:
        for stop_id, label in idx.search_stops(a.query):
            print(f"  {stop_id:>5}  {label}")
            stops.append(stop_id)
    vehicles = get("vehicles", key, a.agency)
    now = datetime.now(UTC)
    t0 = time.perf_counter()
    pos = idx.locate(vehicles, now, timedelta(minutes=5))
    print(f"vehicles: {len(vehicles)} total, {len(pos)} placed, {time.perf_counter() - t0:.2f}s")
    for stop_id in stops[:4]:
        stop = idx.stops[stop_id]
        print(f"\n== {stop.name} ({stop_id})")
        arr = idx.arrivals(stop_id, pos, now, a.speed, timedelta(minutes=a.layover), timedelta(minutes=60))
        for x in arr[: a.rows]:
            d = x.as_dict(now)
            via = " (via terminus)" if x.via_terminal else ""
            print(f"  {x.kind[:5]:5} {x.route:>4}  {x.headsign[:34]:34} {d['minutes']:>3} min  {x.distance_m:>6} m{via}")
        if not arr:
            print("  no vehicles on the way")


if __name__ == "__main__":
    main()
