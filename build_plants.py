"""Magyar erőművi nyilvántartás (plants.json) építése nyílt, hivatkozható adatbázisokból.

Források (mindkettő CC BY 4.0, a hivatkozás kötelező, a térkép és a Módszertan tartalmazza):
  - WRI Global Power Plant Database (GPPD): hőerőművek, atomerőmű, nagyobb naperőművek (Magyarország: country = HUN).
    https://github.com/wri/global-power-plant-database
  - JRC Hydropower database (energy-modelling-toolkit/hydro-power-database): vízerőművek (country_code = HU).
    https://github.com/energy-modelling-toolkit/hydro-power-database

Elv: csak az forrásban szereplő erőmű, koordináta és beépített teljesítmény kerül be; nem találunk ki erőművet, koordinátát
vagy üzemállapotot. A két adatbázis régebbi állapotot tükröz, ezért a térkép „nyílt adatbázis szerinti, tájékoztató” címkét kap.
A „match” mezők az ENTSO-E egységnevek (ékezet nélkül, kisbetűvel) felismeréséhez kellenek: ha egy egység neve tartalmazza
a szócsonkot, ahhoz az erőműhöz tartozik. Több erőműre illeszkedő egységet nem párosítunk (kétértelmű).

Futtatás:  python build_plants.py [--gppd fájl.csv] [--jrc fájl.csv] [--out plants.json]
Fájl nélkül a forrásokat a GitHubról tölti le (a gyűjtő workflow hálózata ezt engedi).
"""
import argparse
import csv
import hashlib
import io
import json
import sys
import urllib.request
from datetime import datetime, timezone

GPPD_URL = "https://raw.githubusercontent.com/wri/global-power-plant-database/master/output_database/global_power_plant_database.csv"
JRC_URL = "https://raw.githubusercontent.com/energy-modelling-toolkit/hydro-power-database/master/data/jrc-hydro-power-plant-database.csv"

FUEL = {"Nuclear": "nuclear", "Gas": "gas", "Coal": "coal", "Oil": "other", "Solar": "solar", "Wind": "wind", "Hydro": "hydro",
        "Biomass": "other", "Waste": "other", "Geothermal": "other"}

# Megjelenített név (a forrásnév magyaros, de azonos tartalmú alakja) és az ENTSO-E egységnév-felismerés szócsonkjai.
# A szócsonk csak akkor szerepel, ha a településnév vagy az erőműnév egyértelmű; hiányzó bejegyzés = nincs párosítás.
CURATED = {
    "WRI1020246": ("Paksi Atomerőmű", ["paks"]),
    "WRI1020248": ("Mátrai Erőmű", ["matra"]),
    "WRI1020247": ("Tiszai Erőmű", ["tiszai", "tiszaujvaros"]),
    "WRI1020249": ("Dunamenti Erőmű", ["dunamenti", "szazhalombatta"]),
    "WRI1020250": ("Gönyűi Erőmű", ["gonyu"]),
    "WRI1020251": ("Csepel Erőmű (Alpiq)", ["csepel"]),
    "WRI1020252": ("Oroszlányi Erőmű", ["oroszlany"]),
    "WRI1020253": ("Kelenföldi Erőmű", ["kelenfold"]),
    "WRI1020254": ("Lőrinci Gázturbinás Erőmű", ["lorinci"]),
    "WRI1020259": ("Kispesti Erőmű", ["kispest"]),
    "WRI1020262": ("Debreceni Kombinált Ciklusú Erőmű", ["debrecen"]),
    "WRI1075836": ("Bakonyi Erőmű", ["bakony", "ajka"]),
    "WRI1020270": ("GREENERGY szabályozási központ", ["greenergy"]),
    "WKS0072600": ("Dunai naperőmű", []),
    "WKS0073291": ("Paksi naperőmű", []),
    "WKS0073281": ("Bükkábrányi naperőmű", []),
    "WKS0066591": ("Visontai naperőmű", []),
    "WKS0066370": ("Pécsi naperőmű", []),
    "H1188": ("Kiskörei Vízerőmű", ["kiskore"]),
    "H2138": ("Kesznyeteni Vízerőmű", ["kesznyeten"]),
    "H3403": ("Tiszalöki Vízerőmű", ["tiszalok"]),
    "H3404": ("Ikervári Vízerőmű", ["ikervar"]),
}
FUEL_HU = {"nuclear": "Atomerőmű", "gas": "Gázerőmű", "coal": "Szénerőmű", "solar": "Naperőmű", "wind": "Szélerőmű", "hydro": "Vízerőmű", "other": "Egyéb (olaj, biomassza stb.)"}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "GridFlow-Analytics-plants/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build(gppd_bytes, jrc_bytes):
    plants = []
    for r in csv.DictReader(io.StringIO(gppd_bytes.decode("utf-8"))):
        if r["country"] != "HUN":
            continue
        pid = r["gppd_idnr"]
        fuel = FUEL.get(r["primary_fuel"])
        lat, lon, mw = num(r["latitude"]), num(r["longitude"]), num(r["capacity_mw"])
        if fuel is None or lat is None or lon is None or mw is None or pid not in CURATED:
            print("KIHAGYVA (GPPD):", pid, r["name"], "- nincs a szerkesztett listában vagy hiányzik az adat", file=sys.stderr)
            continue
        disp, match = CURATED[pid]
        plants.append({
            "id": pid, "name": disp, "name_src": r["name"], "fuel": fuel, "fuel_src": r["primary_fuel"],
            "capacity_mw": mw, "lat": lat, "lon": lon, "match": match,
            "commissioned": int(float(r["commissioning_year"])) if num(r["commissioning_year"]) else None,
            "owner": r["owner"] or None,
            "src": {"db": "WRI Global Power Plant Database", "id": pid, "capacity_basis": r["source"] or None,
                    "geo_basis": r["geolocation_source"] or None, "capacity_year": int(float(r["year_of_capacity_data"])) if num(r["year_of_capacity_data"]) else None},
        })
    for r in csv.DictReader(io.StringIO(jrc_bytes.decode("utf-8"))):
        if r["country_code"] != "HU":
            continue
        pid = r["id"]
        lat, lon, mw = num(r["lat"]), num(r["lon"]), num(r["installed_capacity_MW"])
        if pid not in CURATED or lat is None or lon is None or mw is None:
            print("KIHAGYVA (JRC):", pid, r["name"][:40], file=sys.stderr)
            continue
        disp, match = CURATED[pid]
        plants.append({
            "id": "JRC-" + pid, "name": disp, "name_src": r["name"].split(" hungary ")[0].strip(), "fuel": "hydro", "fuel_src": "Hydro (" + r["type"] + ")",
            "capacity_mw": mw, "lat": lat, "lon": lon, "match": match, "commissioned": None, "owner": None,
            "src": {"db": "JRC Hydropower database", "id": pid, "capacity_basis": "JRC", "geo_basis": "JRC", "capacity_year": None},
        })
    plants.sort(key=lambda p: -p["capacity_mw"])
    return plants


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gppd")
    ap.add_argument("--jrc")
    ap.add_argument("--out", default="plants.json")
    a = ap.parse_args()
    g = open(a.gppd, "rb").read() if a.gppd else fetch(GPPD_URL)
    j = open(a.jrc, "rb").read() if a.jrc else fetch(JRC_URL)
    plants = build(g, j)
    out = {
        "schema": 1,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "Nyílt adatbázisokból épített, nem teljes és nem naprakész erőművi nyilvántartás: a beépített teljesítmény tájékoztató; "
                "tényleges termelést csak ENTSO-E egységszintű adatból jelenít meg a térkép.",
        "sources": [
            {"name": "WRI Global Power Plant Database", "license": "CC BY 4.0", "url": "https://github.com/wri/global-power-plant-database",
             "file": GPPD_URL, "sha256": hashlib.sha256(g).hexdigest()},
            {"name": "JRC Hydropower database", "license": "CC BY 4.0", "url": "https://github.com/energy-modelling-toolkit/hydro-power-database",
             "file": JRC_URL, "sha256": hashlib.sha256(j).hexdigest()},
        ],
        "fuels": FUEL_HU,
        "plants": plants,
    }
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("plants.json: %d erőmű, %.0f MW" % (len(plants), sum(p["capacity_mw"] for p in plants)))


if __name__ == "__main__":
    main()
