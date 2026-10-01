import csv
import json
from pathlib import Path

import numpy as np
from django.conf import settings

DATA = Path(settings.BASE_DIR) / "data"


def load():
    cities = json.loads((DATA / "cities.json").read_text())
    seen, stations = set(), []
    with open(DATA / "fuel-prices-for-be-assessment.csv") as f:
        for r in csv.DictReader(f):
            key = f"{r['City'].strip()}|{r['State'].strip()}"
            # csv has duplicate ids and a few canadian stops we never geocoded
            if r["OPIS Truckstop ID"] in seen or not cities.get(key):
                continue
            seen.add(r["OPIS Truckstop ID"])
            stations.append({
                "id": int(r["OPIS Truckstop ID"]),
                "name": r["Truckstop Name"].strip(),
                "address": r["Address"].strip(),
                "city": r["City"].strip(),
                "state": r["State"].strip(),
                "price": float(r["Retail Price"]),
                "lat": cities[key][0],
                "lon": cities[key][1],
            })
    lookup = {k.lower(): v for k, v in cities.items() if v}  # "denver|co" -> [lat, lon]
    return stations, np.array([[s["lat"], s["lon"]] for s in stations]), lookup


# loaded once per process, ~6.6k stations
STATIONS, COORDS, CITIES = load()
