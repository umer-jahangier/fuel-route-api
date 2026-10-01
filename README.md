# Fuel Route API

Django API that takes a start and finish location in the USA, finds the driving route and tells you
where to fuel up along the way so the trip costs as little as possible. No database, everything is
in memory.

Assumptions from the assignment: the vehicle does 10 mpg and has a 500 mile range (so a 50 gallon tank).
Fuel prices come from `data/fuel-prices-for-be-assessment.csv`.

## Setup

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py runserver
```

## API

```
GET /api/route/?start=Los Angeles, CA&finish=New York, NY
```

`start` and `finish` can be `City, ST`, any place name or ZIP, or `lat,lon`.

```json
{
  "start": {"name": "Los Angeles, CA", "lat": 34.05, "lon": -118.24},
  "finish": {"name": "New York, NY", "lat": 40.71, "lon": -74.0},
  "distance_miles": 2793.6,
  "duration_hours": 41.3,
  "total_gallons": 255.51,
  "total_fuel_cost": 779.48,
  "map_url": "http://localhost:8000/api/route/map/?start=Los+Angeles%2C+CA&finish=New+York%2C+NY",
  "fuel_stops": [
    {"name": "...", "address": "...", "city": "...", "state": "NV", "price": 3.459,
     "lat": 35.77, "lon": -115.32, "mile": 238.5, "gallons": 3.0, "cost": 10.38}
  ],
  "route": {"type": "LineString", "coordinates": [[-118.24, 34.05], ...]}
}
```

`route` is the full driving path as GeoJSON and `map_url` opens the map itself:

```
GET /api/route/map/?start=Los Angeles, CA&finish=New York, NY
```

That page draws the route on a street map (Leaflet + Esri tiles, no key needed) with a red marker on every fuel stop (click one for the
price and gallons). It reuses the cached plan, so it costs no extra routing calls.

Errors come back as `{"error": "..."}` saying what went wrong and what to do:
400 for bad input (missing params, unknown place, outside the USA, no road, a gap longer than 500 miles),
404 for any other path, 405 for anything but GET, 502 when Nominatim or OSRM is down.

## How it works

1. Start and finish are geocoded. `lat,lon` is used as is, `City, ST` is answered from our own city
   list, anything else goes to Nominatim.
2. One call to the public OSRM server gives the full route geometry, distance and time.
3. Stations within 10 miles of the route are picked out with numpy and tagged with their mile marker.
4. A greedy pass over those stations (plus the one closest to the start) picks where to stop and how
   much to buy. At each stop, if a cheaper station is reachable we buy just enough to get there,
   otherwise we fill up and drive to the cheapest station in range. This is the standard optimal
   solution for a fixed tank size.

A request makes at most 3 external calls, and just the one OSRM call for `City, ST` or coordinate
inputs. Results are cached for an hour so repeats make none. The in-process work is a few milliseconds.

## Fuel data

The CSV has no coordinates, only "I-44, EXIT 283" style addresses, so every city/state pair was
geocoded once with Nominatim and saved in `data/cities.json`. Stations sit at their city center, which
is why the 10 mile tolerance is loose. Spellings Nominatim does not know (Mc Alpin, Saint George,
Du Bois...) are normalized and retried, 5 tiny places it still cannot find are skipped, and so are the
Canadian stops. To rebuild the file (about an hour, Nominatim allows 1 request/sec):

```
python manage.py geocode_cities
```

The tank is assumed to be empty at the start, so the first stop (mile 0) is the listed station closest to
the start point and every gallon of the trip is paid for. Around Los Angeles that station can be far away
because the CSV has only 8 California stations.
