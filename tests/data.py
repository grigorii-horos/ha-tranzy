"""A tiny synthetic agency: one trolleybus route along a 1.1 km straight line.

Stops 10 (south end), 11/21 (the middle, one pole each side), 12 (north end).
"""

from datetime import UTC, datetime, timedelta

LAT0, LON = 47.0, 28.8

AGENCIES = [
    {"agency_id": 4, "agency_name": "RTEC&PUA Chisinau"},
    {"agency_id": 2, "agency_name": "CTP Cluj"},
]
ROUTES = [{"route_id": 1, "route_short_name": "5", "route_type": 11, "route_color": "#123456"}]
TRIPS = [
    {"route_id": 1, "trip_id": "1_0", "direction_id": 0, "trip_headsign": "North", "shape_id": "1_0"},
    {"route_id": 1, "trip_id": "1_1", "direction_id": 1, "trip_headsign": "South", "shape_id": "1_1"},
]
STOPS = [
    {"stop_id": 10, "stop_name": "Șoseaua Sud", "stop_lat": LAT0, "stop_lon": LON, "stop_code": ""},
    {"stop_id": 11, "stop_name": "Centru", "stop_lat": LAT0 + 0.005, "stop_lon": LON, "stop_code": ""},
    {"stop_id": 12, "stop_name": "Nord", "stop_lat": LAT0 + 0.01, "stop_lon": LON, "stop_code": ""},
    {"stop_id": 21, "stop_name": "Centru", "stop_lat": LAT0 + 0.005, "stop_lon": LON + 0.0001, "stop_code": ""},
]
STOP_TIMES = [
    {"trip_id": "1_0", "stop_id": 10, "stop_sequence": 0},
    {"trip_id": "1_0", "stop_id": 11, "stop_sequence": 1},
    {"trip_id": "1_0", "stop_id": 12, "stop_sequence": 2},
    {"trip_id": "1_1", "stop_id": 12, "stop_sequence": 0},
    {"trip_id": "1_1", "stop_id": 21, "stop_sequence": 1},
    {"trip_id": "1_1", "stop_id": 10, "stop_sequence": 2},
]
SHAPES = [
    pt
    for n in range(11)
    for pt in (
        {"shape_id": "1_0", "shape_pt_lat": LAT0 + n * 0.001, "shape_pt_lon": LON, "shape_pt_sequence": n},
        {"shape_id": "1_1", "shape_pt_lat": LAT0 + 0.01 - n * 0.001, "shape_pt_lon": LON, "shape_pt_sequence": n},
    )
]


def vehicle(vid: int, trip: str | None, frac: float, age_s: float = 0) -> dict:
    """A vehicle `frac` of the way up the line, its fix `age_s` seconds old."""
    ts = (datetime.now(UTC) - timedelta(seconds=age_s)).isoformat().replace("+00:00", "Z")
    return {
        "id": vid,
        "label": f"V{vid}",
        "trip_id": trip,
        "latitude": LAT0 + frac * 0.01,
        "longitude": LON,
        "timestamp": ts,
    }


def static() -> dict[str, list]:
    return {
        "agency": AGENCIES,
        "routes": ROUTES,
        "trips": TRIPS,
        "stops": STOPS,
        "stop_times": STOP_TIMES,
        "shapes": SHAPES,
    }
