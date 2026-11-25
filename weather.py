#!/usr/bin/env python3
"""Időjárási adatok az Időjárás oldalhoz (idojaras.html). Kimenet: weather.json.

Forrás: Open-Meteo Forecast API (https://open-meteo.com/), kulcs nélkül, óránkénti idősorok:
  hőmérséklet (2 m), szélsebesség (120 m, m/s), globális sugárzás (W/m², az előző óra átlaga),
  felhőzet (%), csapadék (mm/óra).
Az elmúlt `past_days` nap (az Open-Meteo "past_days" funkciója: a modellek legutóbbi elemzései) és az előrejelzés
együtt, UTC idővel. Egy kéréssel az összes hely lekérhető.

Licenc: az adat CC BY 4.0, forrásmegjelölés: Open-Meteo.com (az oldalon szerepel). Az ingyenes API csak
NEM KERESKEDELMI célra használható: üzleti felhasználáshoz az Open-Meteo előfizetése kell.

Futtatás:  python weather.py --out weather.json
Hiba esetén a meglévő weather.json változatlan marad (a futás nem akasztja meg a közzétételt).
"""
import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone

API = "https://api.open-meteo.com/v1/forecast"
VARS = {
    "temperature_2m": "°C",
    "wind_speed_120m": "m/s",
    "shortwave_radiation": "W/m²",
    "cloud_cover": "%",
    "precipitation": "mm",
}
# (azonosító, név, ország, csoport, szélesség, hosszúság). "hu": a magyar átlagba számít, "nb": szomszéd.
PLACES = [
    ("BUD", "Budapest", "HU", "hu", 47.50, 19.04),
    ("GYR", "Győr", "HU", "hu", 47.68, 17.63),
    ("PEC", "Pécs", "HU", "hu", 46.07, 18.23),
    ("SZE", "Szeged", "HU", "hu", 46.25, 20.15),
    ("DEB", "Debrecen", "HU", "hu", 47.53, 21.63),
    ("MIS", "Miskolc", "HU", "hu", 48.10, 20.78),
    ("VIE", "Bécs", "AT", "nb", 48.21, 16.37),
    ("BTS", "Pozsony", "SK", "nb", 48.15, 17.11),
    ("BUH", "Bukarest", "RO", "nb", 44.43, 26.10),
    ("ZAG", "Zágráb", "HR", "nb", 45.81, 15.98),
    ("LJU", "Ljubljana", "SI", "nb", 46.06, 14.51),
    ("BEG", "Belgrád", "RS", "nb", 44.79, 20.45),
]


class Http:
    """get(url, params) -> kiértékelt JSON; hibára kivétel."""

    def get(self, url, params=None, timeout=60):
        import requests
        r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": "GridFlow-Analytics (nem kereskedelmi)"})
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
        return r.json()


def _num(v, nd=1):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else round(f, nd)


def _iso(t):
    """Unix-másodperc vagy ISO-szöveg -> 'YYYY-MM-DDTHH:00:00Z' (UTC)."""
    if isinstance(t, (int, float)):
        return datetime.fromtimestamp(int(t), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    d = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(http, places=PLACES, past_days=3, forecast_days=5):
    params = {
        "latitude": ",".join(f"{p[4]:.2f}" for p in places),
        "longitude": ",".join(f"{p[5]:.2f}" for p in places),
        "hourly": ",".join(VARS),
        "past_days": past_days,
        "forecast_days": forecast_days,
        "timezone": "UTC",
        "timeformat": "unixtime",
        "wind_speed_unit": "ms",
    }
    js = http.get(API, params)
    if isinstance(js, dict) and js.get("error"):
        raise RuntimeError(str(js.get("reason", "ismeretlen hiba")))
    items = js if isinstance(js, list) else [js]
    if len(items) != len(places):
        raise RuntimeError(f"{len(places)} helyből {len(items)} válasz érkezett")
    return items


def build(items, places=PLACES, now=None):
    now = now or datetime.now(timezone.utc)
    ts = [_iso(t) for t in items[0]["hourly"]["time"]]
    out_places, errors = [], []
    for p, it in zip(places, items):
        h = it.get("hourly") or {}
        tt = [_iso(t) for t in h.get("time", [])]
        if tt != ts:
            errors.append(f"{p[1]}: eltérő időrács, kihagyva")
            continue
        hourly = {}
        for k in VARS:
            arr = h.get(k)
            if arr is None:
                errors.append(f"{p[1]}: hiányzó változó: {k}")
                continue
            hourly[k] = [_num(v, 2 if k == "precipitation" else 1) for v in arr]
        out_places.append({"id": p[0], "name": p[1], "country": p[2], "group": p[3], "lat": p[4], "lon": p[5], "hourly": hourly})
    # a magyar átlag: az azonos súlyú magyar helyek egyszerű átlaga óránként (a hiányzó értéket kihagyjuk)
    hu = {}
    for k in VARS:
        cols = [pl["hourly"][k] for pl in out_places if pl["group"] == "hu" and k in pl["hourly"]]
        row = []
        for i in range(len(ts)):
            vals = [c[i] for c in cols if c[i] is not None]
            row.append(round(sum(vals) / len(vals), 2 if k == "precipitation" else 1) if vals else None)
        hu[k] = row
    return {
        "generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Open-Meteo.com",
        "license": "CC BY 4.0 (nem kereskedelmi használat)",
        "demo": False,
        "ts": ts,
        "vars": {k: {"unit": u} for k, u in VARS.items()},
        "places": out_places,
        "hu": hu,
        "errors": errors,
    }


def collect(http, now=None, past_days=3, forecast_days=5):
    return build(fetch(http, PLACES, past_days, forecast_days), PLACES, now)


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="weather.json")
    ap.add_argument("--past-days", type=int, default=3)
    ap.add_argument("--forecast-days", type=int, default=5)
    a = ap.parse_args()
    try:
        data = collect(Http(), past_days=a.past_days, forecast_days=a.forecast_days)
    except Exception as e:  # noqa: BLE001
        print(f"Időjárás: a lekérés nem sikerült ({e}); a meglévő fájl változatlan.", file=sys.stderr)
        return 0
    write_json(a.out, data)
    print(f"Időjárás: {len(data['places'])} hely, {len(data['ts'])} óra, hibák: {data['errors']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
