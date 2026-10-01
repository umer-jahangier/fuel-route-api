import re
from functools import lru_cache

import numpy as np
import polyline
import requests

from .stations import CITIES, COORDS, STATIONS

RANGE = 500  # miles on a full tank
MPG = 10
TANK = RANGE / MPG  # gallons
MAX_OFF_ROUTE = 10  # miles, station coords are city centers so be a bit loose
EARTH = 3958.8  # miles


class ServiceDown(Exception):
    pass


def fetch(service, url, **params):
    try:
        r = requests.get(url, params=params, headers={"User-Agent": "fuel-route-api"}, timeout=20)
        if r.status_code == 429 or r.status_code >= 500:
            r.raise_for_status()
        return r.json()  # osrm answers 400 + json for "no route", handled by the caller
    except requests.RequestException as e:
        raise ServiceDown(f"{service} did not answer ({e.__class__.__name__}), try again in a moment")


@lru_cache(maxsize=1000)
def geocode(place):
    """'lat,lon' is used directly, 'City, ST' comes from our own list, anything else asks nominatim (USA only)"""
    pair = re.fullmatch(r"\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*", place)
    if pair:
        lat, lon = float(pair[1]), float(pair[2])
        if not (24 <= lat <= 50 and -125 <= lon <= -66):
            raise ValueError(f"'{place}' is outside the USA, coordinates must be within the continental USA")
        return {"name": place, "lat": lat, "lon": lon}
    if "," in place and not re.search("[a-zA-Z]", place):
        raise ValueError(f"'{place}' looks like coordinates but must be exactly 'lat,lon'")
    key = re.sub(r"\s*,\s*", "|", place.strip().lower())
    if key in CITIES:
        return {"name": place, "lat": CITIES[key][0], "lon": CITIES[key][1]}
    hits = fetch("geocoding service (nominatim)", "https://nominatim.openstreetmap.org/search",
                 q=place, countrycodes="us", format="json", limit=1)
    if not hits:
        raise ValueError(f"could not find '{place}' in the USA, use a city and state like 'Denver, CO' or 'lat,lon'")
    return {"name": hits[0]["display_name"], "lat": float(hits[0]["lat"]), "lon": float(hits[0]["lon"])}


def get_route(start, finish):
    """one call to OSRM, returns [(lat, lon), ...], miles, hours. polyline is ~7x smaller than geojson"""
    r = fetch(
        "routing service (osrm)",
        f"https://router.project-osrm.org/route/v1/driving/{start['lon']},{start['lat']};{finish['lon']},{finish['lat']}",
        overview="full", geometries="polyline",
    )
    if r.get("code") != "Ok":
        raise ValueError(f"no drivable route from '{start['name']}' to '{finish['name']}', both must be reachable by road")
    route = r["routes"][0]
    return polyline.decode(route["geometry"]), route["distance"] / 1609.344, route["duration"] / 3600


def distance(a, b):
    """haversine in miles, a and b are [..., (lat, lon)] arrays in degrees, broadcasts"""
    a, b = np.radians(a), np.radians(b)
    dlat, dlon = b[..., 0] - a[..., 0], b[..., 1] - a[..., 1]
    h = np.sin(dlat / 2) ** 2 + np.cos(a[..., 0]) * np.cos(b[..., 0]) * np.sin(dlon / 2) ** 2
    return 2 * EARTH * np.arcsin(np.sqrt(h))


def nearest(point):
    """closest station to a point, this is where you fill up before leaving"""
    i = distance(np.array([point["lat"], point["lon"]]), COORDS).argmin()
    return {**STATIONS[i], "mile": 0.0}


def stations_near(route, max_off=MAX_OFF_ROUTE):
    """stations within max_off miles of the route, tagged with their mile marker, sorted by it.
    route is [(lat, lon), ...]. done in chunks so the distance matrix stays small."""
    route = np.asarray(route, dtype=float)
    miles = np.concatenate([[0], np.cumsum(distance(route[:-1], route[1:]))])
    pad = max_off / 45  # degrees, generous on purpose
    found = {}
    for i in range(0, len(route), 500):
        chunk = route[i:i + 500]
        lo, hi = chunk.min(0) - pad, chunk.max(0) + pad
        idx = np.where(((COORDS >= lo) & (COORDS <= hi)).all(1))[0]
        if not len(idx):
            continue
        d = distance(COORDS[idx, None], chunk[None])  # stations x points
        best = d.argmin(1)
        for s, j, off in zip(idx, best, d[np.arange(len(idx)), best]):
            # padded boxes of neighbouring chunks overlap, keep the closest match
            if off <= max_off and (s not in found or off < found[s][0]):
                found[s] = (off, miles[i + j])
    near = [{**STATIONS[s], "mile": round(float(mile), 1)} for s, (off, mile) in found.items()]
    return sorted(near, key=lambda s: s["mile"])


def plan_stops(stations, total_miles):
    """classic gas station greedy, optimal for a fixed tank: if a cheaper station is in range buy just
    enough to reach it, otherwise fill up and go to the cheapest one in range. tank is empty at the first one."""
    stations = stations + [{"price": 0, "mile": total_miles}]  # destination as a free station, so we never over buy
    stops, fuel, i = [], 0.0, 0
    while stations[i]["price"] > 0:
        here = stations[i]
        ahead = [j for j in range(i + 1, len(stations)) if stations[j]["mile"] - here["mile"] <= RANGE]
        if not ahead:
            nxt = stations[i + 1]
            raise ValueError(
                f"no fuel station for {nxt['mile'] - here['mile']:.0f} miles after {here['city']}, {here['state']} "
                f"(mile {here['mile']}), more than the {RANGE} mile range"
            )
        cheaper = [j for j in ahead if stations[j]["price"] < here["price"]]
        j = cheaper[0] if cheaper else min(ahead, key=lambda k: stations[k]["price"])
        need = (stations[j]["mile"] - here["mile"]) / MPG
        buy = max(need - fuel, 0) if cheaper else TANK - fuel
        if buy > 0:
            stops.append({**here, "gallons": round(buy, 2), "cost": round(buy * here["price"], 2)})
        fuel += buy - need
        i = j
    return stops


def plan(start, finish):
    start, finish = geocode(start), geocode(finish)
    coords, total_miles, hours = get_route(start, finish)
    first = nearest(start)  # tank is empty at the start
    near = [first] + [s for s in stations_near(coords) if s["id"] != first["id"]]
    stops = plan_stops(near, total_miles)
    return {
        "start": start,
        "finish": finish,
        "distance_miles": round(total_miles, 1),
        "duration_hours": round(hours, 1),
        "fuel_stops": stops,
        "total_gallons": round(sum(s["gallons"] for s in stops), 2),
        "total_fuel_cost": round(sum(s["cost"] for s in stops), 2),
        "route": {"type": "LineString", "coordinates": [[lon, lat] for lat, lon in coords]},  # geojson is lon,lat
    }
