"""Transit model: static GTFS index and arrival estimates.

Pure Python, no Home Assistant imports, so it can be tested and run on its own.

The Tranzy open-data feed has no arrival times: `stop_times` carries only the
order of stops, `shapes` carries no distances. Arrivals are therefore estimated
here: a vehicle is placed on the line of its trip, the distance along that line
to the stop is measured, and that distance is driven at an average speed. A
vehicle running the opposite direction of the same route is counted too: it
reaches the terminus, waits there, and comes back along the stop's trip.
"""

from __future__ import annotations

import math
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

EARTH_R = 6_371_000.0

ROUTE_TYPES = {0: "tram", 3: "bus", 11: "trolleybus"}

# A stop this close behind the vehicle still counts as ahead: GPS jitter and
# a vehicle standing at the stop must not make it vanish from the board.
BEHIND_TOLERANCE_M = 30.0
# An arrival this far in the past is still shown (as "now"): the feed lags.
PAST_TOLERANCE = timedelta(seconds=60)


def normalize(text: str) -> str:
    """Lower-case, strip diacritics and quotes: `Bariera Sculeni` ~ `bariera sculeni`."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.casefold().replace("”", "").replace("“", "").replace('"', "").split())


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(slots=True)
class Shape:
    """A polyline in local metres with the cumulative distance at each point."""

    xs: list[float]
    ys: list[float]
    cum: list[float]

    @property
    def length(self) -> float:
        return self.cum[-1] if self.cum else 0.0

    def project(self, x: float, y: float, lo: float = 0.0) -> tuple[float, float]:
        """Return (distance along the line, distance off the line) of the closest point.

        Only the part of the line from `lo` metres on is searched: stops of a
        trip are placed in order, so a loop cannot pull a later stop back.
        """
        best_along, best_off = lo, math.inf
        for i in range(len(self.xs) - 1):
            if self.cum[i + 1] < lo:
                continue
            x1, y1, x2, y2 = self.xs[i], self.ys[i], self.xs[i + 1], self.ys[i + 1]
            dx, dy = x2 - x1, y2 - y1
            seg2 = dx * dx + dy * dy
            t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / seg2))
            px, py = x1 + t * dx, y1 + t * dy
            off = math.hypot(x - px, y - py)
            if off < best_off:
                along = self.cum[i] + t * (self.cum[i + 1] - self.cum[i])
                best_along, best_off = max(along, lo), off
        return best_along, best_off


@dataclass(slots=True)
class Trip:
    trip_id: str
    route_id: int
    direction_id: int | None
    headsign: str
    shape: Shape
    # stop_id -> distance along the shape, in stop order
    stops: dict[int, float] = field(default_factory=dict)


@dataclass(slots=True)
class Route:
    route_id: int
    short_name: str
    long_name: str
    color: str | None
    kind: str


@dataclass(slots=True)
class Stop:
    stop_id: int
    name: str
    code: str | None
    lat: float
    lon: float


@dataclass(slots=True)
class VehiclePosition:
    vehicle_id: str
    label: str
    trip_id: str
    along: float
    timestamp: datetime


@dataclass(slots=True)
class Arrival:
    route: str
    kind: str
    color: str | None
    headsign: str
    arrival: datetime
    vehicle: str
    distance_m: int
    via_terminal: bool

    def as_dict(self, now: datetime) -> dict[str, Any]:
        return {
            "route": self.route,
            "type": self.kind,
            "color": self.color,
            "headsign": self.headsign,
            "arrival": self.arrival.isoformat(),
            "minutes": max(0, int((self.arrival - now).total_seconds() // 60)),
            "vehicle": self.vehicle,
            "distance_m": self.distance_m,
            "via_terminal": self.via_terminal,
        }


class TransitIndex:
    """Everything static about one agency, prepared for arrival estimates."""

    def __init__(self) -> None:
        self.lat0 = 0.0
        self.routes: dict[int, Route] = {}
        self.stops: dict[int, Stop] = {}
        self.trips: dict[str, Trip] = {}
        self.trips_by_stop: dict[int, list[str]] = defaultdict(list)
        # trip_id -> trips of the same route running the other way
        self.opposite: dict[str, list[str]] = {}

    def _xy(self, lat: float, lon: float) -> tuple[float, float]:
        k = math.cos(math.radians(self.lat0))
        return math.radians(lon) * EARTH_R * k, math.radians(lat) * EARTH_R

    @classmethod
    def build(
        cls,
        routes: list[dict],
        trips: list[dict],
        stops: list[dict],
        stop_times: list[dict],
        shapes: list[dict],
    ) -> TransitIndex:
        idx = cls()
        if stops:
            idx.lat0 = sum(s["stop_lat"] for s in stops) / len(stops)

        for r in routes:
            idx.routes[r["route_id"]] = Route(
                route_id=r["route_id"],
                short_name=str(r.get("route_short_name") or r["route_id"]),
                long_name=r.get("route_long_name") or "",
                color=r.get("route_color") or None,
                kind=ROUTE_TYPES.get(r.get("route_type"), "other"),
            )
        for s in stops:
            idx.stops[s["stop_id"]] = Stop(
                stop_id=s["stop_id"],
                name=(s.get("stop_name") or str(s["stop_id"])).strip(),
                code=s.get("stop_code") or None,
                lat=s["stop_lat"],
                lon=s["stop_lon"],
            )

        points: dict[str, list[dict]] = defaultdict(list)
        for p in shapes:
            points[str(p["shape_id"])].append(p)
        built: dict[str, Shape] = {}
        for shape_id, pts in points.items():
            pts.sort(key=lambda p: p["shape_pt_sequence"])
            xs, ys, cum = [], [], []
            for p in pts:
                x, y = idx._xy(p["shape_pt_lat"], p["shape_pt_lon"])
                cum.append(cum[-1] + math.hypot(x - xs[-1], y - ys[-1]) if xs else 0.0)
                xs.append(x)
                ys.append(y)
            built[shape_id] = Shape(xs, ys, cum)

        times: dict[str, list[dict]] = defaultdict(list)
        for st in stop_times:
            times[st["trip_id"]].append(st)

        for t in trips:
            shape = built.get(str(t.get("shape_id")))
            if shape is None or len(shape.xs) < 2 or t["route_id"] not in idx.routes:
                continue
            trip = Trip(
                trip_id=t["trip_id"],
                route_id=t["route_id"],
                direction_id=t.get("direction_id"),
                headsign=(t.get("trip_headsign") or "").strip(),
                shape=shape,
            )
            lo = 0.0
            for st in sorted(times.get(trip.trip_id, []), key=lambda s: s["stop_sequence"]):
                stop = idx.stops.get(st["stop_id"])
                if stop is None:
                    continue
                along, _ = shape.project(*idx._xy(stop.lat, stop.lon), lo=lo)
                trip.stops[stop.stop_id] = along
                lo = along
            if not trip.stops:
                continue
            idx.trips[trip.trip_id] = trip
            for stop_id in trip.stops:
                idx.trips_by_stop[stop_id].append(trip.trip_id)

        by_route: dict[int, list[Trip]] = defaultdict(list)
        for trip in idx.trips.values():
            by_route[trip.route_id].append(trip)
        for trip in idx.trips.values():
            idx.opposite[trip.trip_id] = [
                o.trip_id
                for o in by_route[trip.route_id]
                if o.trip_id != trip.trip_id and o.direction_id != trip.direction_id
            ]
        return idx

    # ---- stop search -------------------------------------------------------

    def describe_stop(self, stop_id: int, limit: int = 4) -> str:
        """`5 → Parcul de Troleibuze nr. 2, 8 → str. Grenoble, …` for one pole."""
        seen: list[str] = []
        for trip_id in self.trips_by_stop.get(stop_id, []):
            trip = self.trips[trip_id]
            route = self.routes[trip.route_id]
            last = list(trip.stops)[-1]
            target = trip.headsign if last != stop_id else f"{trip.headsign} (terminus)"
            item = f"{route.short_name} → {target}"
            if item not in seen:
                seen.append(item)
        seen.sort(key=_route_sort_key)
        more = f", +{len(seen) - limit}" if len(seen) > limit else ""
        return ", ".join(seen[:limit]) + more

    def stop_title(self, stop_id: int) -> str:
        """The stop's name; `name → where most routes go` when another pole shares it."""
        stop = self.stops[stop_id]
        twins = [
            s for s in self.stops.values()
            if s.stop_id != stop_id and s.stop_id in self.trips_by_stop and normalize(s.name) == normalize(stop.name)
        ]
        if not twins:
            return stop.name
        heads: dict[str, int] = defaultdict(int)
        for trip_id in self.trips_by_stop.get(stop_id, []):
            trip = self.trips[trip_id]
            if list(trip.stops)[-1] != stop_id:
                heads[trip.headsign] += 1
        if not heads:
            return f"{stop.name} (terminus)"
        top = max(heads.items(), key=lambda kv: (kv[1], kv[0]))[0]
        return f"{stop.name} → {top}"

    def search_stops(self, query: str, limit: int = 40) -> list[tuple[int, str]]:
        """Served stops whose name contains `query`, as (stop_id, label)."""
        q = normalize(query)
        found = [
            stop
            for stop_id, stop in self.stops.items()
            if stop_id in self.trips_by_stop and q in normalize(stop.name)
        ]
        found.sort(key=lambda s: (normalize(s.name) != q, s.name, s.stop_id))
        return [(s.stop_id, f"{s.name} · {self.describe_stop(s.stop_id)}") for s in found[:limit]]

    # ---- live --------------------------------------------------------------

    def locate(
        self,
        vehicles: list[dict],
        now: datetime,
        max_age: timedelta,
        off_route_m: float = 200.0,
    ) -> list[VehiclePosition]:
        """Place every fresh vehicle that runs a known trip on that trip's line."""
        out: list[VehiclePosition] = []
        for v in vehicles:
            trip = self.trips.get(v.get("trip_id") or "")
            if trip is None or v.get("latitude") is None or not v.get("timestamp"):
                continue
            ts = parse_ts(v["timestamp"])
            if now - ts > max_age:
                continue
            along, off = trip.shape.project(*self._xy(v["latitude"], v["longitude"]))
            if off > off_route_m:
                continue
            out.append(
                VehiclePosition(
                    vehicle_id=str(v.get("id")),
                    label=str(v.get("label") or v.get("id")),
                    trip_id=trip.trip_id,
                    along=along,
                    timestamp=ts,
                )
            )
        return out

    def arrivals(
        self,
        stop_id: int,
        positions: list[VehiclePosition],
        now: datetime,
        speed_kmh: float,
        layover: timedelta,
        horizon: timedelta,
    ) -> list[Arrival]:
        """Estimated arrivals at one stop, nearest first, one per vehicle."""
        speed = max(speed_kmh, 1.0) / 3.6
        on_trip: dict[str, list[VehiclePosition]] = defaultdict(list)
        for p in positions:
            on_trip[p.trip_id].append(p)

        best: dict[str, Arrival] = {}

        def offer(p: VehiclePosition, trip: Trip, distance: float, via: bool) -> None:
            route = self.routes[trip.route_id]
            travel = timedelta(seconds=distance / speed) + (layover if via else timedelta())
            at = p.timestamp + travel
            if at < now - PAST_TOLERANCE or at > now + horizon:
                return
            current = best.get(p.vehicle_id)
            if current is not None and current.arrival <= at:
                return
            best[p.vehicle_id] = Arrival(
                route=route.short_name,
                kind=route.kind,
                color=route.color,
                headsign=trip.headsign,
                arrival=at,
                vehicle=p.label,
                distance_m=int(distance),
                via_terminal=via,
            )

        for trip_id in self.trips_by_stop.get(stop_id, []):
            trip = self.trips[trip_id]
            at_stop = trip.stops[stop_id]
            for p in on_trip.get(trip_id, []):
                if p.along <= at_stop + BEHIND_TOLERANCE_M:
                    offer(p, trip, max(0.0, at_stop - p.along), via=False)
            for other_id in self.opposite.get(trip_id, []):
                other = self.trips[other_id]
                for p in on_trip.get(other_id, []):
                    offer(p, trip, max(0.0, other.shape.length - p.along) + at_stop, via=True)

        return sorted(best.values(), key=lambda a: a.arrival)


def _route_sort_key(item: str) -> tuple[int, str]:
    head = item.split(" ", 1)[0]
    digits = "".join(c for c in head if c.isdigit())
    return (int(digits) if digits else 10_000, item)
