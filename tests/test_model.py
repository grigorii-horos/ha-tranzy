"""Tests for the arrival model on a synthetic straight line.

    python3 -m unittest discover -s tests
"""

import importlib.util
import pathlib
import sys
import unittest
from datetime import UTC, datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("model", ROOT / "custom_components/tranzy/model.py")
model = importlib.util.module_from_spec(spec)
sys.modules["model"] = model
spec.loader.exec_module(model)

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
# 0.01° of latitude ≈ 1112 m; the line runs north along lon 28.8
LAT0, LON = 47.0, 28.8


def pt(i: int, frac: float) -> dict:
    return {"lat": LAT0 + frac * 0.01, "lon": LON, "i": i}


def build() -> "model.TransitIndex":
    routes = [{"route_id": 1, "route_short_name": "5", "route_type": 11, "route_color": "#123456"}]
    trips = [
        {"route_id": 1, "trip_id": "1_0", "direction_id": 0, "trip_headsign": "North", "shape_id": "1_0"},
        {"route_id": 1, "trip_id": "1_1", "direction_id": 1, "trip_headsign": "South", "shape_id": "1_1"},
    ]
    # stops at 0, 1/2 and 1 of the line, each a separate pole per direction
    stops = [
        {"stop_id": 10, "stop_name": "Șoseaua Sud", "stop_lat": LAT0, "stop_lon": LON},
        {"stop_id": 11, "stop_name": "Centru", "stop_lat": LAT0 + 0.005, "stop_lon": LON},
        {"stop_id": 12, "stop_name": "Nord", "stop_lat": LAT0 + 0.01, "stop_lon": LON},
        {"stop_id": 21, "stop_name": "Centru", "stop_lat": LAT0 + 0.005, "stop_lon": LON + 0.0001},
    ]
    stop_times = [
        {"trip_id": "1_0", "stop_id": 10, "stop_sequence": 0},
        {"trip_id": "1_0", "stop_id": 11, "stop_sequence": 1},
        {"trip_id": "1_0", "stop_id": 12, "stop_sequence": 2},
        {"trip_id": "1_1", "stop_id": 12, "stop_sequence": 0},
        {"trip_id": "1_1", "stop_id": 21, "stop_sequence": 1},
        {"trip_id": "1_1", "stop_id": 10, "stop_sequence": 2},
    ]
    shapes = []
    for n in range(11):
        shapes.append({"shape_id": "1_0", "shape_pt_lat": LAT0 + n * 0.001, "shape_pt_lon": LON, "shape_pt_sequence": n})
        shapes.append({"shape_id": "1_1", "shape_pt_lat": LAT0 + 0.01 - n * 0.001, "shape_pt_lon": LON, "shape_pt_sequence": n})
    return model.TransitIndex.build(routes, trips, stops, stop_times, shapes)


def vehicle(vid, trip, frac, age_s=0):
    ts = (NOW - timedelta(seconds=age_s)).isoformat().replace("+00:00", "Z")
    return {"id": vid, "label": f"V{vid}", "trip_id": trip, "latitude": LAT0 + frac * 0.01, "longitude": LON, "timestamp": ts}


def board(idx, stop_id, vehicles, speed=20.0, layover=5):
    pos = idx.locate(vehicles, NOW, timedelta(minutes=5))
    return idx.arrivals(stop_id, pos, NOW, speed, timedelta(minutes=layover), timedelta(minutes=60))


class ModelTest(unittest.TestCase):
    def setUp(self):
        self.idx = build()

    def test_stops_placed_along_line(self):
        trip = self.idx.trips["1_0"]
        self.assertAlmostEqual(trip.stops[11], trip.shape.length / 2, delta=5)
        self.assertAlmostEqual(trip.stops[12], trip.shape.length, delta=5)

    def test_direct_arrival_uses_distance_along_line(self):
        # vehicle at 1/4 of the line, stop at 1/2: ~278 m at 20 km/h ≈ 50 s
        arr = board(self.idx, 11, [vehicle(1, "1_0", 0.25)])
        self.assertEqual(len(arr), 1)
        a = arr[0]
        self.assertFalse(a.via_terminal)
        self.assertAlmostEqual(a.distance_m, 278, delta=5)
        self.assertEqual((a.route, a.kind, a.headsign), ("5", "trolleybus", "North"))

    def test_vehicle_past_the_stop_is_not_shown_on_its_trip(self):
        self.assertEqual(board(self.idx, 11, [vehicle(1, "1_0", 0.75)]), [])

    def test_opposite_direction_counts_via_terminus_with_layover(self):
        # southbound at 3/4 of its line → 278 m to its end, then 556 m north to the stop
        arr = board(self.idx, 11, [vehicle(1, "1_1", 0.25)])
        self.assertEqual(len(arr), 1)
        a = arr[0]
        self.assertTrue(a.via_terminal)
        self.assertAlmostEqual(a.distance_m, 278 + 556, delta=10)
        minutes = (a.arrival - NOW).total_seconds() / 60
        self.assertAlmostEqual(minutes, 5 + 834 / (20 / 3.6) / 60, delta=0.2)

    def test_stale_and_unknown_vehicles_are_dropped(self):
        vs = [vehicle(1, "1_0", 0.25, age_s=600), vehicle(2, None, 0.25), vehicle(3, "9_9", 0.25)]
        self.assertEqual(board(self.idx, 11, vs), [])

    def test_off_route_vehicle_is_dropped(self):
        v = vehicle(1, "1_0", 0.25)
        v["longitude"] = LON + 0.01  # ~760 m east of the line
        self.assertEqual(board(self.idx, 11, [v]), [])

    def test_feed_lag_is_accounted_for(self):
        fresh = board(self.idx, 11, [vehicle(1, "1_0", 0.0)])[0]
        lagged = board(self.idx, 11, [vehicle(1, "1_0", 0.0, age_s=120)])[0]
        self.assertAlmostEqual((fresh.arrival - lagged.arrival).total_seconds(), 120, delta=1)

    def test_sorted_and_one_row_per_vehicle(self):
        arr = board(self.idx, 11, [vehicle(1, "1_0", 0.4), vehicle(2, "1_0", 0.1)])
        self.assertEqual([a.vehicle for a in arr], ["V1", "V2"])

    def test_search_is_diacritic_insensitive_and_skips_unserved(self):
        found = self.idx.search_stops("soseaua")
        self.assertEqual([s for s, _ in found], [10])
        labels = dict(self.idx.search_stops("centru"))
        self.assertIn("5 → North", labels[11])
        self.assertIn("5 → South", labels[21])

    def test_stop_title_tells_twin_poles_apart(self):
        self.assertEqual(self.idx.stop_title(11), "Centru → North")
        self.assertEqual(self.idx.stop_title(21), "Centru → South")
        self.assertEqual(self.idx.stop_title(10), "Șoseaua Sud")

    def test_as_dict_minutes_never_negative(self):
        a = board(self.idx, 11, [vehicle(1, "1_0", 0.5, age_s=40)])[0]
        self.assertEqual(a.as_dict(NOW)["minutes"], 0)


if __name__ == "__main__":
    unittest.main()
