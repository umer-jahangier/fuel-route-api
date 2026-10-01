import csv
import json
import re
import time
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

# csv has a few canadian stops, we only care about USA
CANADA = {"AB", "BC", "MB", "NB", "NS", "ON", "QC", "SK", "YT"}


def normalize(city):
    """csv spellings nominatim does not know: Mc Alpin, Saint George, Du Bois, Oneill..."""
    c = re.sub(r"\b(Mc|Mac) (\w)", r"\1\2", city, flags=re.I)
    c = re.sub(r"\bSaint\b", "St.", c)
    c = re.sub(r"^(Du|De|La) (\w+)$", r"\1\2", c)
    c = re.sub(r"^O([a-z]+)$", r"O'\1", c)
    c = re.sub(r"^Pueblo Of | National Park$", "", c)
    return c


def lookup(city, state):
    hits = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"city": city, "state": state, "country": "USA", "format": "json", "limit": 1},
        headers={"User-Agent": "fuel-route-api"},
        timeout=30,
    ).json()
    return [float(hits[0]["lat"]), float(hits[0]["lon"])] if hits else None


class Command(BaseCommand):
    requires_system_checks = []  # views need cities.json which we are about to make
    help = "One off: geocode every city/state in the csv into data/cities.json (nominatim, 1 req/sec so ~1 hour)"

    def handle(self, *args, **options):
        data = Path(settings.BASE_DIR) / "data"
        out = data / "cities.json"
        cities = json.loads(out.read_text()) if out.exists() else {}

        with open(data / "fuel-prices-for-be-assessment.csv") as f:
            keys = {f"{r['City'].strip()}|{r['State'].strip()}" for r in csv.DictReader(f)}
        todo = sorted(k for k in keys if cities.get(k) is None and k.split("|")[1] not in CANADA)

        for i, key in enumerate(todo, 1):
            city, state = key.split("|")
            t = time.time()
            try:
                cities[key] = lookup(city, state)
                if cities[key] is None and normalize(city) != city:
                    time.sleep(1)
                    cities[key] = lookup(normalize(city), state)
            except Exception as e:
                self.stderr.write(f"{key}: {e}")
            if i % 50 == 0:
                out.write_text(json.dumps(cities))
                self.stdout.write(f"{i}/{len(todo)}")
            time.sleep(max(0, 1 - (time.time() - t)))  # nominatim allows 1 req/sec

        out.write_text(json.dumps(cities))
        self.stdout.write(f"done, not found: {[k for k, v in cities.items() if v is None]}")
