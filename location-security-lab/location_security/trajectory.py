from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

from .schemas import GeoPoint

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(a: GeoPoint, b: GeoPoint) -> float:
    lat1 = radians(a.latitude)
    lon1 = radians(a.longitude)
    lat2 = radians(b.latitude)
    lon2 = radians(b.longitude)

    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(h))


def elapsed_seconds(a: GeoPoint, b: GeoPoint) -> float:
    return abs(b.timestamp_ms - a.timestamp_ms) / 1000.0


def speed_mps(a: GeoPoint, b: GeoPoint) -> float | None:
    dt = elapsed_seconds(a, b)
    if dt <= 0:
        return None
    return haversine_m(a, b) / dt
