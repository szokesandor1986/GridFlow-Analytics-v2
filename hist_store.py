"""A hosszú távú adattár (hist/) közös függvényei: elrendezés, katalógus, partíciók írása és olvasása.

Elrendezés (a data ágon és a közzétett oldalon is ugyanez):
  hist/manifest.json                      a tár indexe: zónák, kategóriák, lefedettség, fájlonkénti hash
  hist/catalog.json                       sorozatleírások: mértékegység, aggregálás, forrás, minőség, CO2-tényezők
  hist/h/{ZONA}/{ÉV}/{kategória}.json     óránkénti partíció (UTC rács; az év a budapesti naptári év)
  hist/q/{ZONA}/{ÉV}/{kategória}.json     negyedórás partíció (csak ahol kértük)
  hist/{d,w,m,y}/{ZONA}/{kategória}.json  napi / heti (ISO) / havi / éves összesítés (helyi, budapesti idő szerint)

Alapelvek: az idő mindig UTC-ben, szabályos rácson van tárolva; a hiányzó érték null, soha nem nulla;
a fájlok tartalma determinisztikus (nincs benne írási időbélyeg), így az érintetlen fájl nem változik.
"""
import hashlib
import json
import os

import numpy as np
import pandas as pd

SCHEMA = 1
BUD = "Europe/Budapest"
PRELIM_DAYS = 90        # ennél frissebb adatot "előzetesnek" jelölünk (konvenció, az ENTSO-E nem jelöli a véglegességet)
MIN_COV = 0.7           # egy időszak összesítése csak legalább ekkora lefedettségnél érvényes
TIERS = ("d", "w", "m", "y")

# kulcs: ENTSO-E zónakód (ajánlati zóna); az "country" csak megjelenítési csoport (a zóna nem azonos az országgal)
ZONES = {
    "HU": {"name": "Magyarország", "country": "HU"},
    "AT": {"name": "Ausztria", "country": "AT"},
    "SK": {"name": "Szlovákia", "country": "SK"},
    "RO": {"name": "Románia", "country": "RO"},
    "RS": {"name": "Szerbia", "country": "RS"},
    "HR": {"name": "Horvátország", "country": "HR"},
    "SI": {"name": "Szlovénia", "country": "SI"},
    "UA": {"name": "Ukrajna", "country": "UA", "note": "az ENTSO-E-n a közlés 2022 óta hiányos"},
    "DE_LU": {"name": "Németország–Luxemburg", "country": "DE", "note": "közös ajánlati zóna, nem azonos Németországgal"},
    "CZ": {"name": "Csehország", "country": "CZ"},
}
BORDERS = ("AT", "SK", "UA", "RO", "RS", "HR", "SI")        # a magyar határok (a fizikai áramlás kategóriához)

GEN_LABELS = {"nuclear": "Atomerőmű", "gas": "Földgáz", "coal": "Szén", "solar": "Napenergia", "wind": "Szél",
              "bio": "Biomassza és hulladék", "hydro": "Víz", "other": "Egyéb"}
BORDER_LABELS = {"AT": "Ausztria", "SK": "Szlovákia", "UA": "Ukrajna", "RO": "Románia", "RS": "Szerbia", "HR": "Horvátország", "SI": "Szlovénia"}

# Minőségi osztály: published = az ENTSO-E közlése (90 nap után "végleges", előtte "előzetes"), calculated = a GridFlow számolta,
# estimated = becslést is tartalmaz. A "hiányzó" a null érték.
CATS = {
    "generation": {"label": "Termelés típusonként", "unit": "MW", "agg": "mean", "src": "ENTSO-E 16.1.B&C (nettó termelés)", "kind": "published", "series": GEN_LABELS},
    "load": {"label": "Fogyasztás (tény)", "unit": "MW", "agg": "mean", "src": "ENTSO-E 6.1.A", "kind": "published", "series": {"load": "Fogyasztás"}},
    "load_forecast": {"label": "Fogyasztás (day-ahead előrejelzés)", "unit": "MW", "agg": "mean", "src": "ENTSO-E 6.1.B", "kind": "published", "series": {"load_forecast": "Előrejelzés"}},
    "price_da": {"label": "Day-ahead ár", "unit": "€/MWh", "agg": "time_mean", "src": "ENTSO-E 12.1.D", "kind": "published", "series": {"price": "Day-ahead ár"}},
    "flow_physical": {"label": "Fizikai határkeresztező áramlás (nettó, + = import Magyarországra)", "unit": "MW", "agg": "mean", "src": "ENTSO-E 12.1.G",
                      "kind": "published", "series": BORDER_LABELS, "zones": ["HU"]},
    "flow_scheduled": {"label": "Menetrendezett kereskedelmi csere (nettó, + = import Magyarországra)", "unit": "MW", "agg": "mean", "src": "ENTSO-E 12.1.F",
                       "kind": "published", "series": BORDER_LABELS, "zones": ["HU"]},
    "net_import": {"label": "Nettó import (a fizikai áramlásokból)", "unit": "MW", "agg": "mean", "src": "saját számítás az ENTSO-E 12.1.G adataiból", "kind": "calculated",
                   "series": {"net": "Nettó import"}, "zones": ["HU"]},
    "residual": {"label": "Maradék terhelés (fogyasztás − nap − szél)", "unit": "MW", "agg": "mean", "src": "saját számítás az ENTSO-E 6.1.A és 16.1.B&C adataiból", "kind": "calculated",
                 "series": {"residual": "Maradék terhelés"}},
    "co2": {"label": "Termelés-alapú CO₂-intenzitás", "unit": "g/kWh", "agg": "gen_weighted", "src": "saját számítás: ENTSO-E 16.1.B&C × IPCC AR5 életciklus-tényezők", "kind": "estimated",
            "series": {"intensity": "CO₂-intenzitás"}},
    "ramp": {"label": "Napi rámpa-mutatók (maradék terhelés)", "unit": "MW", "agg": "daily_metric", "src": "saját számítás", "kind": "calculated",
             "series": {"res_mid_min": "Déli (9–16 h) minimum", "ramp_eve": "Legnagyobb esti (15–21 h) óránkénti emelkedés"}, "tiers": ["d", "w", "m", "y"]},
}
BASE_CATS = ("generation", "load", "load_forecast", "price_da", "flow_physical", "flow_scheduled")
DERIVED_CATS = ("net_import", "residual", "co2", "ramp")
ROLL_CATS = tuple(CATS)             # az összesítők a katalógus összes kategóriájára készülnek


def cat_zones(cat):
    return CATS[cat].get("zones") or list(ZONES)


# ------------------------------------------------------------------ rács
def year_bounds(year):
    """A budapesti naptári év UTC határai [kezdet, vég)."""
    s = pd.Timestamp(f"{year}-01-01", tz=BUD).tz_convert("UTC")
    e = pd.Timestamp(f"{year + 1}-01-01", tz=BUD).tz_convert("UTC")
    return s, e


def year_grid(year, step=3600):
    s, e = year_bounds(year)
    return pd.date_range(s, e, freq=f"{step}s", inclusive="left")


def to_hourly_utc(obj):
    """Series/DataFrame (bármely időzóna, bármely felbontás) -> órás átlag, UTC index."""
    if obj is None:
        return None
    if isinstance(obj, pd.Series):
        obj = obj.to_frame("v")
    out = obj.copy()
    out.index = pd.DatetimeIndex(out.index).tz_convert("UTC")
    return out.resample("h").mean()


def to_quarter_utc(obj):
    """Negyedórás rácsra: ahol a forrás natívan óránkénti volt, ott az órás érték a négy negyedórára ismétlődik (nem interpolálunk);
    a natív negyedórás szakasz érintetlen. Visszaadja a rácsot és az első natív negyedórás időpontot (vagy None)."""
    if obj is None:
        return None, None
    if isinstance(obj, pd.Series):
        obj = obj.to_frame("v")
    o = obj.copy()
    o.index = pd.DatetimeIndex(o.index).tz_convert("UTC")
    o = o[~o.index.duplicated()].sort_index()
    nxt = o.index.to_series().shift(-1) - o.index.to_series()
    hourly = (nxt == pd.Timedelta(hours=1)).to_numpy()
    parts = [o]
    for k in (1, 2, 3):
        x = o[hourly].copy()
        x.index = x.index + pd.Timedelta(minutes=15 * k)
        parts.append(x)
    q = pd.concat(parts).sort_index()
    q = q[~q.index.duplicated(keep="first")]
    step = o.index.to_series().diff()
    nat = step[step <= pd.Timedelta(minutes=15)]
    return q, (nat.index[0] if len(nat) else None)


# ------------------------------------------------------------------ fájlok
def rnd(v):
    """Tömör, determinisztikus szám: egész, ha egész; 100 felett egészre, alatta 1 tizedesre kerekítve (MW); None, ha nincs érték."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    v = float(v)
    r = round(v) if abs(v) >= 100 else round(v, 1)
    return int(r) if r == int(r) else r


def rnd1(v):
    """Összesítés átlaga: mindig 1 tizedes (a részletes partíciónál durvább a kerekítés, ott a 100 feletti érték egész)."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    r = round(float(v), 1)
    return int(r) if r == int(r) else r


def rnd2(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    r = round(float(v), 2)
    return int(r) if r == int(r) else r


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def write_if_changed(path, obj):
    """Csak akkor ír, ha a tartalom megváltozott (a git és a böngésző gyorsítótár is ezt használja). Igaz, ha írt."""
    data = dumps(obj)
    try:
        with open(path, "rb") as f:
            if f.read() == data:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return True


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def part_path(root, zone, year, cat, step=3600):
    return os.path.join(root, "q" if step == 900 else "h", zone, str(year), cat + ".json")


def tier_path(root, tier, zone, cat):
    return os.path.join(root, tier, zone, cat + ".json")


def load_partition(root, zone, year, cat, step=3600):
    """Egy partíció DataFrame-ként (UTC rács, a hiány NaN), vagy None."""
    j = read_json(part_path(root, zone, year, cat, step))
    if not j:
        return None
    idx = pd.date_range(pd.Timestamp(j["t0"], unit="s", tz="UTC"), periods=j["n"], freq=f"{j['step']}s")
    df = pd.DataFrame({k: np.array(v, dtype=float) for k, v in j["series"].items()}, index=idx)     # a null NaN-ná alakul
    df.attrs["native15_from"] = j.get("native15_from")
    return df


def save_partition(root, zone, year, cat, df, step=3600, native15_from=None, replace=False):
    """Egy zóna-év-kategória partíció mentése. A meglévő értékeket csak az új, nem hiányzó értékek írják felül
    (az ENTSO-E nem töröl, a rövid kiesés nem lyukasztja ki a már megvolt adatot). A származtatott kategóriák replace=True-val
    teljesen felülíródnak (az alapadatból újraszámolt érték a mérvadó). Igaz, ha a fájl változott."""
    if df is None or df.empty or not df.notna().any().any():
        return False
    grid = year_grid(year, step)
    new = df.reindex(grid)
    new = new.loc[:, new.notna().any()]
    old = None if replace else load_partition(root, zone, year, cat, step)
    if old is not None:
        new = new.combine_first(old.reindex(grid))
        if old.attrs.get("native15_from") and not native15_from:
            native15_from = old.attrs["native15_from"]
    meta = CATS[cat]
    rf = rnd2 if meta["unit"] == "€/MWh" else rnd
    obj = {"schema": SCHEMA, "zone": zone, "cat": cat, "year": year, "t0": int(grid[0].timestamp()), "step": step, "n": len(grid),
           "unit": meta["unit"], "agg": meta["agg"], "source": meta["src"], "quality": meta["kind"],
           "series": {c: [rf(v) for v in new[c].to_numpy()] for c in new.columns}}
    if native15_from is not None:
        obj["native15_from"] = int(pd.Timestamp(native15_from).timestamp())
    return write_if_changed(part_path(root, zone, year, cat, step), obj)


def partition_years(root, zone, cat):
    out = []
    d = os.path.join(root, "h", zone)
    if os.path.isdir(d):
        for y in sorted(os.listdir(d)):
            if y.isdigit() and os.path.exists(part_path(root, zone, int(y), cat)):
                out.append(int(y))
    return out


def load_all(root, zone, cat, years=None):
    """Egy zóna egy kategóriájának összes (vagy a megadott) éve egyetlen óránkénti DataFrame-ben."""
    frames = []
    for y in (years if years is not None else partition_years(root, zone, cat)):
        df = load_partition(root, zone, y, cat)
        if df is not None:
            frames.append(df)
    if not frames:
        return None
    out = pd.concat(frames).sort_index()
    return out[~out.index.duplicated(keep="last")]


def file_hash(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()[:10]
