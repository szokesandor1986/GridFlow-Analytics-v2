#!/usr/bin/env python3
"""ENTSO-E adatgyűjtő a magyar határkeresztező villamosenergia-áramlás oldalhoz.

Lekéri (ENTSO-E Transparency Platform, RESTful API):
  - a HU és a szomszédos zónák közötti fizikai áramlást (MW), mindkét irányban,
  - a HU és a szomszédos zónák day-ahead árát (EUR/MWh),
és egy data.json fájlba írja, amit az index.html olvas.

A "mérnöki" adatkörök (menetrend, kapacitás, fogyasztás, termelés típusonként és blokkonként,
nap/szél előrejelzés, kiesések, rendszeregyensúly) egy külön engineer.json fájlba kerülnek,
amit a muszaki.html olvas. Ennek hibája nem akadályozza a data.json frissítését.

Futtatás:
    pip install "entsoe-py>=1.0.0" pandas
    export ENTSOE_TOKEN="a-te-tokened"
    python collector.py --out data.json

A token csak ebben a szkriptben él, a böngészőbe soha nem kerül.
Egy-egy határ vagy zóna hibája nem állítja le a futást: a hiba bekerül a data.json "errors" listájába.
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import numpy as np
import pandas as pd

HOME = "HU"
# kód -> magyar név, a határ fizikai áramlásához
NEIGHBOURS = {
    "AT": "Ausztria",
    "SK": "Szlovákia",
    "UA": "Ukrajna",
    "RO": "Románia",
    "RS": "Szerbia",
    "HR": "Horvátország",
    "SI": "Szlovénia",
}
PRICE_ZONES = [HOME] + list(NEIGHBOURS)
# Az európai pillanatkép és a hosszú távú összehasonlítás zónái. Ha egy zónára nincs day-ahead ár
# (pl. Szerbia), egyszerűen kimarad.
EUROPE_CORE = {
    "HU": "Magyarország", "AT": "Ausztria", "SK": "Szlovákia", "RO": "Románia", "HR": "Horvátország",
    "SI": "Szlovénia", "RS": "Szerbia", "CZ": "Csehország", "DE_LU": "Németország–Luxemburg",
    "PL": "Lengyelország", "BG": "Bulgária", "IT_NORD": "Észak-Olaszország", "FR": "Franciaország",
    "CH": "Svájc", "NL": "Hollandia", "BE": "Belgium", "ES": "Spanyolország", "GR": "Görögország", "PT": "Portugália",
}
# További ENTSO-E tagországok (a térkép teljes lefedéséhez). Ahol nincs közölt adat, a térképen szürke marad.
EUROPE_EXTRA = {
    "DK": "Dánia", "NO": "Norvégia", "SE": "Svédország", "FI": "Finnország", "EE": "Észtország", "LV": "Lettország",
    "LT": "Litvánia", "IE": "Írország", "BA": "Bosznia-Hercegovina", "ME": "Montenegró", "MK": "Észak-Macedónia",
    "AL": "Albánia", "XK": "Koszovó", "MD": "Moldova", "UA": "Ukrajna", "TR": "Törökország", "MT": "Málta",
    "CY": "Ciprus", "GE": "Grúzia", "GB": "Egyesült Királyság", "BY": "Belarusz", "IS": "Izland",
}
EUROPE_ZONES = {**EUROPE_CORE, **EUROPE_EXTRA}
# Az ENTSO-E térképén szereplő, de lekérdezhető adat nélküli országok (csak a térképen jelennek meg, névvel).
GEO_ONLY = {"RU": "Oroszország", "AM": "Örményország", "AZ": "Azerbajdzsán"}
# Ajánlati zónák (a zónatérképen az országok helyett ezek jelennek meg; az országos érték az összesített, fent).
SUBZONES = {
    "NO_1": "Norvégia NO1 (délkelet)", "NO_2": "Norvégia NO2 (délnyugat)", "NO_3": "Norvégia NO3 (közép)", "NO_4": "Norvégia NO4 (észak)", "NO_5": "Norvégia NO5 (nyugat)",
    "SE_1": "Svédország SE1 (észak)", "SE_2": "Svédország SE2", "SE_3": "Svédország SE3", "SE_4": "Svédország SE4 (dél)",
    "DK_1": "Dánia DK1 (nyugat)", "DK_2": "Dánia DK2 (kelet)",
    "IT_CNOR": "Olaszország – közép-észak", "IT_CSUD": "Olaszország – közép-dél", "IT_SUD": "Olaszország – dél",
    "IT_CALA": "Olaszország – Calabria", "IT_SICI": "Olaszország – Szicília", "IT_SARD": "Olaszország – Szardínia",
}
ALL_ZONES = {**EUROPE_ZONES, **SUBZONES}
# Ahol egy ország több azonosítón is szerepel, sorban próbáljuk, az első működőt használjuk.
ZONE_FIRST = {"UA": ["UA_IPS", "UA"]}
# Több ajánlati zónás országok: országszinten vonjuk össze (ár: átlag, fogyasztás/termelés/pozíció: összeg).
ZONE_GROUPS = {
    "DK": ["DK_1", "DK_2"], "NO": ["NO_1", "NO_2", "NO_3", "NO_4", "NO_5"], "SE": ["SE_1", "SE_2", "SE_3", "SE_4"],
    "IE": ["IE_SEM"],
}
# Határonkénti nap előtti NTC csak a nem-Core határokon van (a Core-határokon flow-based kapacitás-kiosztás van,
# ott nincs NTC, a lekérdezés felesleges és lassú). A magyar Core-határok: AT, SK, RO, HR, SI.
NTC_BORDERS = ("RS", "UA")


def with_retry(fn, tries=3, wait=4):
    """Átmeneti hálózati hibánál újrapróbál; 401/403-nál azonnal leáll értelmes üzenettel."""
    last = None
    for attempt in range(1, tries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (401, 403):
                sys.exit(f"HTTP {status}: érvénytelen token vagy nincs RESTful API jogosultság.")
            if exc.__class__.__name__ in NO_DATA:
                raise
            last = exc
            if attempt < tries:
                time.sleep(wait * attempt)
    raise last


NO_DATA = ("NoMatchingDataError", "InvalidBusinessParameterError", "InvalidPSRTypeError")


class GroupClient:
    """Becsomagolja az entsoe-py klienst: a ZONE_GROUPS országkódokra a tagzónákat külön kéri le, és összevonja.
    Ár és eltérési ár: átlag; fogyasztás, termelés, nettó pozíció, előrejelzések, áramlás: összeg. Ahol egy tagzónára nincs adat,
    a többi is elég; ha egyikre sincs, ugyanaz a hiba jön, mint egyetlen zónánál."""

    def __init__(self, base):
        self._b = base
        self._memo, self._lock = {}, __import__("threading").Lock()

    def __getattr__(self, name):
        fn = getattr(self._b, name)
        if not name.startswith("query_"):
            return fn

        def call(*a, **k):
            return self._call(name, fn, a, k)
        return call

    @staticmethod
    def _expand(code):
        return ZONE_GROUPS.get(code, [code]) if isinstance(code, str) else [code]

    def _one(self, name, fn, combo, rest, k):
        """Egy tényleges ENTSO-E hívás, memoizálva: az országos összevonás és a zónatérkép ugyanazt a tagzónát nem kéri le kétszer."""
        key = (name, combo, tuple(str(x) for x in rest), tuple(sorted((a, str(v)) for a, v in k.items())))
        with self._lock:
            hit = self._memo.get(key)
        if hit is not None:
            return hit
        try:
            res = fn(*combo, *rest, **k)
        except Exception:  # noqa: BLE001  (hibát nem tárolunk, az újrapróbálkozás friss lekérdezés legyen)
            raise
        with self._lock:
            self._memo[key] = res
        return res

    def _call(self, name, fn, a, k):
        special = lambda x: isinstance(x, str) and (x in ZONE_GROUPS or x in ZONE_FIRST)
        if not a or not any(special(x) for x in a[:2]):
            return self._one(name, fn, tuple(a[:2]) if name == "query_crossborder_flows" else tuple(a[:1]), a[2:] if name == "query_crossborder_flows" else a[1:], k)
        nz = 2 if name == "query_crossborder_flows" else 1
        rest = a[nz:]

        def alts(code):
            return ZONE_FIRST.get(code, ZONE_GROUPS.get(code, [code])) if isinstance(code, str) else [code]
        first_mode = [x for x in a[:nz] if isinstance(x, str) and x in ZONE_FIRST]
        if first_mode:
            err = None
            options = [(x, y) for x in alts(a[0]) for y in alts(a[1])] if nz == 2 else [(z,) for z in alts(a[0])]
            for combo in options:
                try:
                    res = self._one(name, fn, combo, rest, k)
                    if res is not None and len(res):
                        return res
                except Exception as e:  # noqa: BLE001
                    err = e
            if err:
                raise err
            raise ValueError("üres válasz")
        combos = [(x, y) for x in alts(a[0]) for y in alts(a[1])] if nz == 2 else [(z,) for z in alts(a[0])]
        parts, err = [], None
        for combo in combos:
            try:
                parts.append(self._one(name, fn, combo, rest, k))
            except Exception as e:     # egy tagzóna hiánya nem akadály
                err = e
        if not parts:
            raise err
        if len(parts) == 1:
            return parts[0]
        mean = name in ("query_day_ahead_prices", "query_imbalance_prices")
        if isinstance(parts[0], pd.Series) and mean:
            return pd.concat(parts, axis=1).mean(axis=1)
        if mean:
            return pd.concat(parts).groupby(level=0).mean()
        out = parts[0]
        for p in parts[1:]:
            out = out.add(p, fill_value=0)
        return out


class Batch:
    """Lekérdezések párhuzamosan. A futásidőt az ENTSO-E válaszideje adja, nem a számolás,
    ezért több kérés fut egyszerre (a limit 400 kérés/perc, mi összesen is csak ~100 kérést küldünk).
    A kérések beadási sorrendje a fontossági sorrend; a határidő után a még nem indult kérések kimaradnak."""

    def __init__(self, budget_s, workers=8, tries=2, wait=2):
        self.deadline = time.monotonic() + budget_s
        self.budget_s = budget_s
        self.ex = ThreadPoolExecutor(max_workers=workers)
        self.futs = {}
        self.tries, self.wait = tries, wait
        self.errors, self.missing, self.skipped = [], [], 0
        self.msgs, self.dur = {}, {}          # hibaüzenet és futásidő kulcsonként (a hibakereséshez)

    def _run(self, fn, key=None):
        if time.monotonic() > self.deadline:
            return "skip", None
        t0 = time.monotonic()
        try:
            v = with_retry(fn, tries=self.tries, wait=self.wait)
        except Exception as exc:  # noqa: BLE001
            name = exc.__class__.__name__
            self.dur[key] = time.monotonic() - t0
            if name not in NO_DATA:
                self.msgs[key] = " ".join(str(exc).split())[:140]
            return ("nodata" if name in NO_DATA else "err:" + name), None
        self.dur[key] = time.monotonic() - t0
        if v is None or (hasattr(v, "__len__") and len(v) == 0):
            return "nodata", None
        return "ok", v

    def add(self, key, fn):
        self.futs[key] = self.ex.submit(self._run, fn, key)

    def status(self, key):
        """"ok" | "nodata" | "skip" | "err" – a kérés végállapota (megvárja, míg lefut)."""
        st = self.futs[key].result()[0]
        return "err" if st.startswith("err:") else st

    def slowest(self, n=5):
        return sorted(((round(d), k) for k, d in self.dur.items()), reverse=True)[:n]

    def get(self, key):
        """Az eredmény (vagy None). A hiányt és a hibát feljegyzi. 401/403 esetén a SystemExit továbbmegy."""
        st, v = self.futs[key].result()
        if st == "ok":
            return v
        if st == "skip":
            self.skipped += 1
        elif st == "nodata":
            self.missing.append(key)
        else:
            msg = self.msgs.get(key)
            self.errors.append(f"{key}: {st[4:]}" + (f" ({msg})" if msg else ""))
        return None

    def close(self):
        self.ex.shutdown(wait=True)

    def notes(self):
        return [f"időkeret ({self.budget_s} s) lejárt, kihagyott lekérdezések: {self.skipped}"] if self.skipped else []


def to_list(series):
    """Pandas sorozat -> JSON-barát lista (NaN -> None), 2 tizedesre kerekítve."""
    return [None if pd.isna(v) else round(float(v), 2) for v in series]


def iso(index):
    return [t.strftime("%Y-%m-%dT%H:%M:%SZ") for t in index]


def hourly_mean(s):
    return s.tz_convert("UTC").resample("h").mean()


def collect(client, now=None, hours=48, budget_s=240, workers=8, price_days=60):
    now = now or pd.Timestamp.now(tz="UTC")
    start = (now - pd.Timedelta(hours=hours)).floor("h")
    end = now.ceil("h") + pd.Timedelta(hours=1)
    B = Batch(budget_s, workers=workers)

    # ---- kérések beadása (fontossági sorrendben), majd az eredmények összegyűjtése
    local_midnight = now.tz_convert("Europe/Budapest").normalize()
    p_start = local_midnight - pd.Timedelta(days=max(1, -(-hours // 24), price_days))      # az ársor legalább price_days napra nyúlik vissza (az árgrafikon hosszú ablakaihoz)
    p_end = local_midnight + pd.Timedelta(days=2)
    for code in NEIGHBOURS:
        for direction, a, b in (("import", code, HOME), ("export", HOME, code)):
            B.add(f"áramlás {code} {direction}", lambda a=a, b=b: client.query_crossborder_flows(a, b, start=start, end=end))
    for zone in PRICE_ZONES:
        B.add(f"ár {zone}", lambda zone=zone: client.query_day_ahead_prices(zone, start=p_start, end=p_end))

    # ---- fizikai áramlás
    imp, exp = {}, {}
    for code, name in NEIGHBOURS.items():
        for direction, store in (("import", imp), ("export", exp)):
            s_ = B.get(f"áramlás {code} {direction}")
            if s_ is not None:
                store[code] = hourly_mean(s_)

    idx = pd.date_range(start, end, freq="h", tz="UTC", inclusive="left")
    imp_df = pd.DataFrame(imp).reindex(idx)
    exp_df = pd.DataFrame(exp).reindex(idx)
    # Egy határ egy órában "jelen van", ha legalább az egyik irányra van érték
    # (a fizikai áramlást irányonként teszik közzé; a másik irány tipikusan 0 vagy nincs publikálva).
    cols = list(NEIGHBOURS)
    have_any = (imp_df.reindex(columns=cols).notna() | exp_df.reindex(columns=cols).notna())
    active = [c for c in cols if have_any[c].any()]

    # "teljes óra": minden aktív határnak van adata -> ezt használja a fő szám
    complete = have_any[active].all(axis=1) if active else pd.Series(False, index=idx)
    net = imp_df.sum(axis=1, skipna=True) - exp_df.sum(axis=1, skipna=True)
    net[~have_any.any(axis=1)] = float("nan")

    borders = []
    for code, name in NEIGHBOURS.items():
        i = imp_df[code] if code in imp_df.columns else pd.Series(float("nan"), index=idx)
        e = exp_df[code] if code in exp_df.columns else pd.Series(float("nan"), index=idx)
        have = have_any[code]
        last_ts = have[have].index.max() if have.any() else None
        borders.append(
            {
                "code": code,
                "name": name,
                "import_mw": to_list(i),
                "export_mw": to_list(e),
                "last_ts": None if last_ts is None else last_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )

    last_complete = complete[complete].index.max() if complete.any() else None

    # ---- day-ahead árak
    prices = {}
    for zone in PRICE_ZONES:
        s_ = B.get(f"ár {zone}")
        if s_ is not None:
            prices[zone] = s_.tz_convert("UTC")
    B.close()
    errors = B.errors + B.notes()

    price_block = {"ts": [], "zones": {}}
    if prices:
        pidx = pd.DatetimeIndex(sorted(set().union(*[set(s.index) for s in prices.values()])))
        price_block["ts"] = iso(pidx)
        for zone, s in prices.items():
            price_block["zones"][zone] = to_list(s.reindex(pidx))

    return {
        "generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "ENTSO-E Transparency Platform",
        "demo": False,
        "home": HOME,
        "hourly_ts": iso(idx),
        "net_import_mw": to_list(net),
        "complete": [bool(x) for x in complete],
        "last_complete_ts": None if last_complete is None else last_complete.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "borders": borders,
        "prices": price_block,
        "errors": errors,
    }


# ======================================================================================
#  MÉRNÖKI ADATKÖRÖK  (engineer.json)
# ======================================================================================

# ENTSO-E termelési típus -> csoport
GROUPS = {
    "nuclear": ["Nuclear"],
    "gas": ["Fossil Gas", "Fossil Coal-derived gas"],
    "coal": ["Fossil Brown coal/Lignite", "Fossil Hard coal", "Fossil Peat", "Fossil Oil shale"],
    "solar": ["Solar"],
    "wind": ["Wind Onshore", "Wind Offshore"],
    "bio": ["Biomass", "Waste"],
    "hydro": ["Hydro Run-of-river and poundage", "Hydro Water Reservoir", "Hydro Pumped Storage"],
    "other": ["Fossil Oil", "Geothermal", "Other renewable", "Other", "Marine"],
}
TYPE_TO_GROUP = {t: g for g, ts in GROUPS.items() for t in ts}

# Életciklus-alapú kibocsátási tényezők, gCO2eq/kWh (IPCC AR5 WG3, Annex III, mediánok).
# Az "egyéb" csoportnak nincs egységes IPCC-értéke: 700 g/kWh az óvatos (magas) közelítés,
# a hulladék a biomassza értékét kapja. Mindkettő becslés, az oldalon is így szerepel.
CO2_FACTORS = {"nuclear": 12, "gas": 490, "coal": 820, "solar": 48, "wind": 11, "bio": 230, "hydro": 24, "other": 700}
CO2_SOURCE = "IPCC AR5 WG3 Annex III, életciklus-mediánok (gCO2eq/kWh); egyéb: 700, becslés"


def hourly_list(obj, idx):
    """Series (vagy 1 oszlopos DataFrame) -> órás átlag az idx-re igazítva, JSON-lista."""
    if obj is None:
        return None
    if isinstance(obj, pd.DataFrame):
        obj = obj.iloc[:, 0]
    return to_list(hourly_mean(obj).reindex(idx))


def net_of(imp, exp, idx):
    """Két irány (import, export) órás sorozatából nettó: import - export (hiányzó irány = 0, ha a másik van)."""
    a = hourly_mean(imp).reindex(idx) if imp is not None else pd.Series(float("nan"), index=idx)
    b = hourly_mean(exp).reindex(idx) if exp is not None else pd.Series(float("nan"), index=idx)
    have = a.notna() | b.notna()
    n = a.fillna(0) - b.fillna(0)
    n[~have] = float("nan")
    return n


def physical_net_from_main(main, code, idx):
    """A data.json-ban már letöltött fizikai áramlásból nettó (import - export), az idx-re igazítva."""
    if not main:
        return None
    b = next((x for x in main["borders"] if x["code"] == code), None)
    if not b or not b.get("last_ts"):
        return None
    ts = pd.DatetimeIndex(pd.to_datetime(main["hourly_ts"], utc=True))
    i = pd.Series(b["import_mw"], index=ts, dtype="float64")
    e = pd.Series(b["export_mw"], index=ts, dtype="float64")
    have = i.notna() | e.notna()
    n = i.fillna(0) - e.fillna(0)
    n[~have] = float("nan")
    return n.reindex(idx)


def flatten_types(df):
    """Termelési DataFrame -> {típusnév: órás Series}; a 'fogyasztás' (szivattyúzás) oszlopokat kihagyja."""
    out = {}
    for c in df.columns:
        name, kind = (c[0], c[-1]) if isinstance(c, tuple) else (c, "Actual Aggregated")
        if "consumption" in str(kind).lower():
            continue
        s = hourly_mean(df[c])
        out[name] = out[name].add(s, fill_value=0) if name in out else s
    return out


def group_sum(by_type, idx):
    """{ENTSO-E típus: Series} -> {csoport: lista}; csak azok a csoportok, ahol van adat."""
    res = {}
    for g, types in GROUPS.items():
        parts = [by_type[t].reindex(idx) for t in types if t in by_type]
        if not parts:
            continue
        df = pd.concat(parts, axis=1)
        s = df.sum(axis=1, min_count=1)
        res[g] = to_list(s)
    # ismeretlen típus nem tűnhet el: az "egyéb"-hez adjuk
    known = set(TYPE_TO_GROUP)
    extra = [by_type[t].reindex(idx) for t in by_type if t not in known]
    if extra:
        s = pd.concat(extra, axis=1).sum(axis=1, min_count=1)
        if "other" in res:
            cur = pd.Series(res["other"], index=idx, dtype="float64")
            s = pd.concat([cur, s], axis=1).sum(axis=1, min_count=1)
        res["other"] = to_list(s)
    return res


# ---------------------------------------------------------------- 17.1.I: pénzügyi kiadások és bevételek a kiegyenlítésben
FIN_DIR = {"A01": "up", "A02": "down"}


def _xml_docs(content):
    """ZIP-ből vagy nyers XML-ből a dokumentumok szövege (az ENTSO-E mindkét formát adhatja)."""
    import io
    import zipfile
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            return [z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.lower().endswith(".xml")]
    return [content.decode("utf-8", "replace")]


def parse_financial_balance(content):
    """Az A87 dokumentum feldolgozása. Védekező: a pontok szerkezetét nem feltételezi szigorúan, hanem a levélelemek nevei
    alapján keresi az összeget (…amount), az irányt (…direction) és a pozíciót.
    Visszatér: (sorok, minta), a sor {month: 'YYYY-MM' (budapesti hónap), dir: 'up'|'down'|nyers kód, amount, currency},
    a minta a nyers szerkezet rövid leírása (a napló hibakereséséhez)."""
    import bs4
    rows, sample = [], None
    for text in _xml_docs(content):
        soup = bs4.BeautifulSoup(text, "html.parser")
        for ts in soup.find_all("timeseries"):
            leaf = lambda tag: {c.name: c.get_text(strip=True) for c in tag.find_all(True) if not c.find(True)}  # noqa: E731
            tl = {k: v for k, v in leaf(ts).items() if k not in ("position", "start", "end")}
            cur = next((v for k, v in tl.items() if "currency" in k), "")
            ts_dir = next((v for k, v in tl.items() if k.endswith("direction")), None)
            for period in ts.find_all("period"):
                res = (period.find("resolution").get_text(strip=True) if period.find("resolution") else "P1M")
                start = pd.Timestamp(period.find("start").get_text(strip=True))
                if start.tzinfo is None:
                    start = start.tz_localize("UTC")
                for pt in period.find_all("point"):
                    pl = leaf(pt)
                    pos = int(pl.get("position", "1").replace(",", "") or 1)
                    t0 = start + pd.DateOffset(months=pos - 1) if res.upper() == "P1M" else start
                    month = t0.tz_convert("Europe/Budapest").strftime("%Y-%m")
                    # Egy ponton belül több Financial_Price van (A01 = kiadás, A02 = bevétel): mindegyiket külön olvassuk,
                    # különben a szótár az utolsót tartaná meg, és a kiadás elveszne.
                    fps = pt.find_all("financial_price")
                    items = [leaf(fp) for fp in fps] if fps else [pl]
                    if sample is None:
                        sample = {"timeseries": sorted(tl), "point": sorted(pl), "resolution": res, "value_example": pl, "financial_prices_in_point": len(fps)}
                    for it in items:
                        amount = next((v for k, v in it.items() if k.endswith("amount") or k == "quantity"), None)
                        d = next((v for k, v in it.items() if k.endswith("direction")), ts_dir)
                        if amount is None:
                            continue
                        try:
                            val = float(amount.replace(",", ""))
                        except ValueError:
                            continue
                        rows.append({"month": month, "dir": FIN_DIR.get(d, str(d)), "amount": val, "currency": cur})
    return rows, sample


def query_financial_balance(client, zone, start, end):
    """17.1.I (documentType=A87, havi). A kliens saját metódusát használja, ha van (teszt); az entsoe-py 1.0.0-nak nincs ilyen,
    ezért a nyers kérést mi küldjük. Az API egy éves időtartam-korlátja miatt legfeljebb 12 hónapos darabokban kérünk."""
    fn = getattr(client, "query_financial_balance", None)
    if fn:
        return fn(zone, start, end)
    from entsoe.mappings import lookup_area
    area = lookup_area(zone)
    rows, sample, a = [], None, start
    while a < end:
        b = min(a + pd.DateOffset(months=12), end)
        r = client._base_request(params={"documentType": "A87", "controlArea_Domain": area.code}, start=a, end=b)
        rr, sm = parse_financial_balance(r.content)
        rows += rr
        sample = sample or sm
        a = b
    if not rows:
        raise_no_data()
    return rows, sample


def raise_no_data():
    class NoMatchingDataError(Exception):
        pass
    raise NoMatchingDataError


def finance_summary(res):
    """Sorok -> {currency, months, up, down}; ugyanarra a hónapra/irányra több érték esetén az utolsó marad."""
    if not res:
        return None
    rows, sample = res
    months = sorted({r["month"] for r in rows})
    out = {"currency": next((r["currency"] for r in rows if r["currency"]), ""), "months": months, "up": [], "down": []}
    for d in ("up", "down"):
        by = {r["month"]: r["amount"] for r in rows if r["dir"] == d}
        out[d] = [by.get(m) for m in months]
    other = sorted({r["dir"] for r in rows} - {"up", "down"})
    if other:
        out["other_directions"] = other
    out["raw_structure"] = sample
    return out


def bids_updown(df, idx):
    """12.3.E (aggregált szabályozási energia ajánlatok): (irány, mrid, 'Offered'|'Activated') oszlopokból irányonként összeg.
    Egy irányban több termékidősor (standard, egyedi, helyi…) lehet; a teljesítmények összeadódnak."""
    out = {}
    for d in ("Up", "Down"):
        for what in ("Activated", "Offered"):
            cols = [c for c in df.columns if isinstance(c, tuple) and c[0] == d and str(c[-1]) == what]
            if cols:
                s = df[cols].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=1)
                out[f"{d.lower()}_{what.lower()}"] = hourly_list(s, idx)
    return out


def price_updown(df, idx):
    """17.1.F (aktivált szabályozási energia ára): 'Up' / 'Down' oszlopok órás átlaga."""
    out = {}
    for d in ("Up", "Down"):
        if d in df.columns:
            out[d.lower()] = hourly_list(pd.to_numeric(df[d], errors="coerce"), idx)
    return out


def outage_rows(df, now, kind):
    """ENTSO-E kiesési dokumentumok -> tömör lista (legutóbbi változat, nem törölt, az ablakba eső)."""
    if df is None or not len(df):
        return []
    d = df.reset_index()
    if "mrid" in d and "revision" in d:
        d = d[d["revision"] == d.groupby("mrid")["revision"].transform("max")]
    if "docstatus" in d:
        d = d[~d["docstatus"].astype(str).str.lower().isin(["cancelled", "withdrawn"])]
    lo, hi = now - pd.Timedelta(days=7), now + pd.Timedelta(days=45)
    rows, seen = [], set()
    for _, r in d.iterrows():
        try:
            st, en = pd.to_datetime(r["start"], utc=True), pd.to_datetime(r["end"], utc=True)
        except Exception:  # noqa: BLE001
            continue
        if pd.isna(st) or pd.isna(en) or en < lo or st > hi:
            continue
        key = (str(r.get("mrid")), st, en)
        if key in seen:
            continue
        seen.add(key)
        bt = str(r.get("businesstype", ""))
        row = {
            "start": st.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": en.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "avail_mw": None if pd.isna(r.get("avail_qty")) else round(float(r["avail_qty"]), 1),
            "planned": "unplanned" not in bt.lower() and "forced" not in bt.lower(),
        }
        if kind == "gen":
            row["name"] = str(r.get("production_resource_name") or r.get("production_resource_psr_name") or "ismeretlen")
            row["type"] = str(r.get("plant_type") or "")
            row["group"] = TYPE_TO_GROUP.get(row["type"], "other")
            nom = r.get("nominal_power")
            row["nominal_mw"] = None if pd.isna(nom) else round(float(nom), 1)
        rows.append(row)
    rows.sort(key=lambda x: x["start"])
    return rows[:200]


def updown(df):
    """Szabályozási energia DataFrame -> (fel, le) Series; az oszlopnevekből ismeri fel az irányt."""
    up = dn = None
    for c in df.columns:
        n = " ".join(map(str, c)) if isinstance(c, tuple) else str(c)
        n = n.lower()
        if "up" in n and up is None:
            up = df[c]
        elif "down" in n and dn is None:
            dn = df[c]
    return up, dn


def parse_unit_capacity(df):
    """ENTSO-E 14.1.B (beépített teljesítmény termelőegységenként) -> [{name, type, group, mw, eic}].
    Az oszlopneveket tartalom alapján ismeri fel (a könyvtár verziói eltérő fejléceket adnak); ismeretlen szerkezetnél üres lista."""
    if df is None or not hasattr(df, "columns") or len(df) == 0:
        return []
    cols = {str(c).lower(): c for c in df.columns}
    pick = lambda *keys: next((cols[k] for k in cols if any(x in k for x in keys)), None)  # noqa: E731
    cn, ct, cc = pick("name"), pick("type"), pick("capacity", "installed", "mw")
    if cn is None or cc is None:
        return []
    out, seen = [], set()
    for idx, r in df.iterrows():
        name = str(r[cn]).strip()
        try:
            mw = float(r[cc])
        except (TypeError, ValueError):
            continue
        if not name or name.lower() == "nan" or pd.isna(mw) or mw <= 0:
            continue
        typ = str(r[ct]).strip() if ct is not None else ""
        key = (name, typ)
        if key in seen:
            continue
        seen.add(key)
        eic = idx if isinstance(idx, str) else ""
        out.append({"name": name, "type": typ, "group": TYPE_TO_GROUP.get(typ, "other"), "mw": round(mw, 1), "eic": eic})
    out.sort(key=lambda u: -u["mw"])
    return out[:120]


def collect_engineer(client, now=None, hours=48, main=None, budget_s=240, workers=8, plant_hours=72):
    now = now or pd.Timestamp.now(tz="UTC")
    start = (now - pd.Timedelta(hours=hours)).floor("h")
    local = now.tz_convert("Europe/Budapest").normalize()
    end = (local + pd.DateOffset(days=2)).tz_convert("UTC")      # holnap 24:00 (helyi idő): az előrejelzések miatt
    idx = pd.date_range(start, end, freq="h", tz="UTC", inclusive="left")
    B = Batch(budget_s, workers=workers)
    ow_start, ow_end = now.floor("D") - pd.Timedelta(days=7), now.floor("D") + pd.Timedelta(days=45)
    cap_start = pd.Timestamp(year=now.year - 1, month=1, day=1, tz="UTC")

    # ---- kérések beadása, FONTOSSÁGI SORRENDBEN (ha az időkeret kifogy, a végén lévők maradnak ki):
    # 1. fogyasztás, termelés, előrejelzés, rendszeregyensúly  2. határok menetrendje, kapacitása
    # 3. blokkszintű termelés  4. kiesések (a leglassabbak)
    B.add("fogyasztás tény", lambda: client.query_load(HOME, start=start, end=end))
    B.add("fogyasztás előrejelzés", lambda: client.query_load_forecast(HOME, start=start, end=end))
    B.add("termelés típusonként", lambda: client.query_generation(HOME, start=start, end=end, nett=True))
    B.add("nap/szél előrejelzés", lambda: client.query_wind_and_solar_forecast(HOME, start=start, end=end))
    B.add("eltérési ár", lambda: client.query_imbalance_prices(HOME, start=start, end=end))
    B.add("eltérési mennyiség", lambda: client.query_imbalance_volumes(HOME, start=start, end=end))
    # aFRR/mFRR: a régi 17.1.E közlést a GL EB 12.3.E aggregált ajánlatok váltja ki (A24), ezért az az elsődleges;
    # a régi lekérdezés tartalék marad arra az esetre, ha az új adatkörben nincs adat.
    for pt, tag in (("A51", "afrr"), ("A47", "mfrr")):
        B.add(f"aggregált ajánlatok {tag}", lambda pt=pt: client.query_aggregated_bids(HOME, pt, start=start, end=end))
    for bt, tag in (("A96", "afrr"), ("A97", "mfrr")):
        B.add(f"aktivált energia ára {tag}", lambda bt=bt: client.query_activated_balancing_energy_prices(HOME, start=start, end=end, process_type="A16", business_type=bt))
    fin_start = (now.tz_convert("Europe/Budapest").normalize().replace(day=1) - pd.DateOffset(months=23))
    B.add("pénzügyi mérleg (17.1.I)", lambda: query_financial_balance(client, HOME, fin_start, now.tz_convert("Europe/Budapest").normalize() + pd.Timedelta(days=1)))
    for bt, tag in (("A96", "afrr"), ("A97", "mfrr")):
        B.add(f"szabályozási energia {tag}", lambda bt=bt: client.query_activated_balancing_energy(HOME, start=start, end=end, business_type=bt))
    B.add("beépített teljesítmény", lambda: client.query_installed_generation_capacity(HOME, start=cap_start, end=now))
    for code in NEIGHBOURS:
        for da in (False, True):
            tag = " DA" if da else ""
            B.add(f"menetrend {code}→HU{tag}", lambda code=code, da=da: client.query_scheduled_exchanges(code, HOME, start=start, end=end, dayahead=da))
            B.add(f"menetrend HU→{code}{tag}", lambda code=code, da=da: client.query_scheduled_exchanges(HOME, code, start=start, end=end, dayahead=da))
    for code in NTC_BORDERS:
        B.add(f"NTC {code}→HU", lambda code=code: client.query_net_transfer_capacity_dayahead(code, HOME, start=start, end=end))
        B.add(f"NTC HU→{code}", lambda code=code: client.query_net_transfer_capacity_dayahead(HOME, code, start=start, end=end))
    plant_start = max(start, (now - pd.Timedelta(hours=plant_hours)).floor("h"))   # a leglassabb lekérdezés: rövidebb ablak
    B.add("blokkszintű termelés", lambda: client.query_generation_per_plant(HOME, start=plant_start, end=end))
    B.add("egységek beépített teljesítménye", lambda: client.query_installed_generation_capacity_per_unit(HOME, start=cap_start, end=now))
    B.add("termelő-kiesések", lambda: client.query_unavailability_of_generation_units(HOME, start=ow_start, end=ow_end))
    for code in NEIGHBOURS:
        for a_, b_ in ((code, HOME), (HOME, code)):
            B.add(f"hálózati kiesés {a_}→{b_}", lambda a_=a_, b_=b_: client.query_unavailability_transmission(a_, b_, start=ow_start, end=ow_end))
    A = lambda key, fn=None: B.get(key)  # noqa: E731  (az eredmények kiolvasása; a lekérdezés már fut)

    # ---- határonként: fizikai vs menetrendezett, kapacitás
    flows = {}
    for code in NEIGHBOURS:
        f = {"phys_net": None, "sched_net": None, "sched_da_net": None, "ntc_in": None, "ntc_out": None}
        phys = physical_net_from_main(main, code, idx)
        f["phys_net"] = None if phys is None else to_list(phys)
        for field, da in (("sched_net", False), ("sched_da_net", True)):
            i_ = A(f"menetrend {code}→HU{' DA' if da else ''}")
            e_ = A(f"menetrend HU→{code}{' DA' if da else ''}")
            if i_ is not None or e_ is not None:
                f[field] = to_list(net_of(i_, e_, idx))
        ci = A(f"NTC {code}→HU") if code in NTC_BORDERS else None
        co = A(f"NTC HU→{code}") if code in NTC_BORDERS else None
        f["ntc_in"] = hourly_list(ci, idx)
        f["ntc_out"] = hourly_list(co, idx)
        if any(v is not None for v in f.values()):
            flows[code] = f

    # ---- fogyasztás (tény + day-ahead előrejelzés)
    load = {"actual": hourly_list(A("fogyasztás tény", lambda: client.query_load(HOME, start=start, end=end)), idx),
            "forecast": hourly_list(A("fogyasztás előrejelzés", lambda: client.query_load_forecast(HOME, start=start, end=end)), idx)}

    # ---- termelés típusonként
    generation, by_type = {}, {}
    gdf = A("termelés típusonként", lambda: client.query_generation(HOME, start=start, end=end, nett=True))
    if gdf is not None:
        by_type = flatten_types(gdf)
        generation = group_sum(by_type, idx)

    # ---- nap / szél day-ahead előrejelzés
    sw = {"solar": None, "wind": None}
    fdf = A("nap/szél előrejelzés", lambda: client.query_wind_and_solar_forecast(HOME, start=start, end=end))
    if fdf is not None:
        ft = flatten_types(fdf)
        parts = {"solar": ["Solar"], "wind": ["Wind Onshore", "Wind Offshore"]}
        for k, names in parts.items():
            got = [ft[n].reindex(idx) for n in names if n in ft]
            if got:
                sw[k] = to_list(pd.concat(got, axis=1).sum(axis=1, min_count=1))

    # ---- beépített teljesítmény (a legutóbbi közölt év)
    installed = {}
    idf = A("beépített teljesítmény", lambda: client.query_installed_generation_capacity(HOME, start=pd.Timestamp(year=now.year - 1, month=1, day=1, tz="UTC"), end=now))
    if idf is not None:
        last = idf.dropna(how="all").iloc[-1]
        tmp = {}
        for c, v in last.items():
            name = c[0] if isinstance(c, tuple) else c
            if pd.notna(v):
                g = TYPE_TO_GROUP.get(name, "other")
                tmp[g] = tmp.get(g, 0.0) + float(v)
        installed = {k: round(v, 1) for k, v in tmp.items()}

    # ---- blokkszintű termelés
    units = []
    pdf = A("blokkszintű termelés", lambda: client.query_generation_per_plant(HOME, start=plant_start, end=end))
    if pdf is not None:
        for c in pdf.columns:
            name = c[0] if isinstance(c, tuple) else str(c)
            typ = next((x for x in c[1:] if x in TYPE_TO_GROUP), "") if isinstance(c, tuple) else ""
            kind = c[-1] if isinstance(c, tuple) else ""
            if "consumption" in str(kind).lower():
                continue
            lst = hourly_list(pdf[c], idx)
            if lst and any(v is not None for v in lst):
                units.append({"name": str(name), "type": str(typ), "group": TYPE_TO_GROUP.get(str(typ), "other"), "mw": lst})
        units.sort(key=lambda u: -max(v for v in u["mw"] if v is not None))
        units = units[:40]

    # ---- egységek beépített teljesítménye (az erőművi térkép terhelési százalékához és egységlistájához)
    unit_capacity = parse_unit_capacity(A("egységek beépített teljesítménye"))

    # ---- kiesések
    ow_start, ow_end = now.floor("D") - pd.Timedelta(days=7), now.floor("D") + pd.Timedelta(days=45)
    outages_gen = outage_rows(A("termelő-kiesések", lambda: client.query_unavailability_of_generation_units(HOME, start=ow_start, end=ow_end)), now, "gen")
    outages_tx = []
    for code in NEIGHBOURS:
        for a, b in ((code, HOME), (HOME, code)):
            rows = outage_rows(A(f"hálózati kiesés {a}→{b}", lambda a=a, b=b: client.query_unavailability_transmission(a, b, start=ow_start, end=ow_end)), now, "tx")
            for r in rows:
                r["border"], r["from"], r["to"] = code, a, b
            outages_tx += rows
    outages_tx.sort(key=lambda x: x["start"])

    # ---- rendszeregyensúly
    imbalance = {"long": None, "short": None, "volume": None}
    ip = A("eltérési ár", lambda: client.query_imbalance_prices(HOME, start=start, end=end))
    if ip is not None:
        cols = {str(c).lower(): c for c in ip.columns}
        lc = next((v for k, v in cols.items() if "long" in k), None)
        sc = next((v for k, v in cols.items() if "short" in k), None)
        imbalance["long"] = hourly_list(ip[lc], idx) if lc is not None else None
        imbalance["short"] = hourly_list(ip[sc], idx) if sc is not None else None
        if lc is None and sc is None:
            imbalance["long"] = hourly_list(ip.iloc[:, 0], idx)
    iv = A("eltérési mennyiség", lambda: client.query_imbalance_volumes(HOME, start=start, end=end))
    if iv is not None:
        imbalance["volume"] = hourly_list(iv.iloc[:, 0] if isinstance(iv, pd.DataFrame) else iv, idx)
    balancing = {}
    for pt, tag in (("A51", "afrr"), ("A47", "mfrr")):
        got = A(f"aggregált ajánlatok {tag}")
        if got is not None:
            for k, v in bids_updown(got, idx).items():          # up_activated, down_offered, ...
                d, what = k.split("_")
                balancing[f"{tag}_{d}" if what == "activated" else f"{tag}_{d}_offered"] = v
        legacy = A(f"szabályozási energia {tag}")                # régi 17.1.E: csak ha az új nem adott semmit
        if legacy is not None and f"{tag}_up" not in balancing and f"{tag}_down" not in balancing:
            up, dn = updown(legacy)
            balancing[f"{tag}_up"] = None if up is None else hourly_list(up, idx)
            balancing[f"{tag}_down"] = None if dn is None else hourly_list(dn, idx)
        pr = A(f"aktivált energia ára {tag}")
        if pr is not None:
            for d, v in price_updown(pr, idx).items():
                balancing[f"{tag}_price_{d}"] = v
    finance = finance_summary(A("pénzügyi mérleg (17.1.I)"))

    B.close()
    errors = B.errors + B.notes()
    have = lambda v: bool(v) and (not isinstance(v, dict) or any(x is not None for x in v.values()))  # noqa: E731
    modules = {
        "flows": bool(flows),
        "sched": any(f.get("sched_net") is not None for f in flows.values()),
        "ntc": any(f.get("ntc_in") is not None or f.get("ntc_out") is not None for f in flows.values()),
        "load": have(load),
        "generation": bool(generation),
        "solar_wind_forecast": have(sw),
        "units": bool(units),
        "unit_capacity": bool(unit_capacity),
        "outages_gen": bool(outages_gen),
        "outages_tx": bool(outages_tx),
        "imbalance": have(imbalance),
        "balancing": have(balancing),
        "finance": bool(finance),
    }
    return {
        "generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "ENTSO-E Transparency Platform",
        "demo": False,
        "hourly_ts": iso(idx),
        "flows": flows,
        "load": load,
        "generation": generation,
        "solar_wind_forecast": sw,
        "installed_mw": installed,
        "co2": {"factors": CO2_FACTORS, "source": CO2_SOURCE},
        "units": units,
        "unit_capacity": unit_capacity,
        "outages_gen": outages_gen,
        "outages_tx": outages_tx,
        "imbalance": imbalance,
        "balancing": balancing,
        "finance": finance,
        "modules": modules,
        "errors": errors,
        "missing": B.missing,
    }


# Szomszédos zónapárok az európai áramlási térképhez (a nettó áramlás a -> b irányban pozitív).
EUROPE_PAIRS = [
    ("HU", "AT"), ("HU", "SK"), ("HU", "RO"), ("HU", "HR"), ("HU", "SI"), ("HU", "RS"),
    ("AT", "DE_LU"), ("AT", "CZ"), ("AT", "SI"), ("AT", "CH"), ("AT", "IT_NORD"),
    ("SK", "CZ"), ("SK", "PL"), ("RO", "BG"), ("RO", "RS"), ("HR", "SI"), ("HR", "RS"), ("SI", "IT_NORD"),
    ("RS", "BG"), ("BG", "GR"), ("CZ", "DE_LU"), ("CZ", "PL"), ("DE_LU", "PL"), ("DE_LU", "FR"),
    ("DE_LU", "NL"), ("DE_LU", "BE"), ("DE_LU", "CH"), ("FR", "BE"), ("ES", "PT"), ("FR", "CH"), ("FR", "ES"),
    ("FR", "IT_NORD"), ("CH", "IT_NORD"), ("NL", "BE"),
    # Skandinávia, Balti-államok, kelet és Balkán
    ("DK", "DE_LU"), ("DK", "SE"), ("DK", "NO"), ("DK", "NL"), ("SE", "NO"), ("SE", "FI"), ("NO", "FI"), ("NO", "NL"),
    ("SE", "DE_LU"), ("SE", "PL"), ("SE", "LT"), ("FI", "EE"), ("EE", "LV"), ("LV", "LT"), ("LT", "PL"), ("NO", "DE_LU"),
    ("HU", "UA"), ("SK", "UA"), ("PL", "UA"), ("RO", "UA"), ("RO", "MD"), ("UA", "MD"),
    ("BG", "TR"), ("GR", "TR"), ("GR", "AL"), ("GR", "MK"), ("BG", "MK"), ("RS", "MK"), ("RS", "ME"), ("RS", "BA"),
    ("HR", "BA"), ("BA", "ME"), ("ME", "AL"), ("AL", "XK"), ("RS", "XK"), ("MK", "XK"), ("ME", "XK"), ("IT_NORD", "ME"), ("IE", "FR"),
    ("GB", "FR"), ("GB", "NL"), ("GB", "BE"), ("GB", "NO"), ("GB", "DK"), ("GB", "IE"), ("BY", "PL"), ("BY", "LT"), ("BY", "UA"), ("TR", "GE"),
]


def collect_europe(client, now=None, budget_s=120, workers=8):
    """Az európai zónák day-ahead ára az utolsó napokra (europe.json). Hibája nem érinti a többi fájlt."""
    now = now or pd.Timestamp.now(tz="UTC")
    local = now.tz_convert("Europe/Budapest").normalize()
    p_start, p_end = local - pd.Timedelta(days=2), local + pd.Timedelta(days=2)
    B = Batch(budget_s, workers=workers)
    for z in ALL_ZONES:
        B.add(f"ár {z}", lambda z=z: client.query_day_ahead_prices(z, start=p_start, end=p_end))
    f_start, f_end = now.floor("h") - pd.Timedelta(hours=47), now.floor("h") + pd.Timedelta(hours=1)
    for a, b in EUROPE_PAIRS:        # fizikai áramlás mindkét irányban; a nettó a két irány különbsége
        B.add(f"áramlás {a}->{b}", lambda a=a, b=b: client.query_crossborder_flows(a, b, start=f_start, end=f_end))
        B.add(f"áramlás {b}->{a}", lambda a=a, b=b: client.query_crossborder_flows(b, a, start=f_start, end=f_end))
    series = {}
    for z in ALL_ZONES:
        s = B.get(f"ár {z}")
        if s is not None:
            series[z] = hourly_mean(s.tz_convert("UTC"))
    f_idx = pd.date_range(f_start, f_end, freq="h", tz="UTC", inclusive="left")
    pairs = []
    for a, b in EUROPE_PAIRS:
        ab, ba = B.get(f"áramlás {a}->{b}"), B.get(f"áramlás {b}->{a}")
        if ab is None and ba is None:
            continue
        x = hourly_mean(ab.tz_convert("UTC")).reindex(f_idx) if ab is not None else pd.Series(np.nan, index=f_idx)
        y = hourly_mean(ba.tz_convert("UTC")).reindex(f_idx) if ba is not None else pd.Series(np.nan, index=f_idx)
        net = x.fillna(0) - y.fillna(0)
        net[x.isna() & y.isna()] = np.nan
        pairs.append({"a": a, "b": b, "mw": to_list(net)})
    B.close()
    out = {"generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "source": "ENTSO-E Transparency Platform", "demo": False,
           "names": {**ALL_ZONES, **GEO_ONLY}, "ts": [], "zones": {}, "flow_ts": iso(f_idx), "flows": pairs,
           "errors": B.errors + B.notes(), "missing": B.missing}
    if series:
        idx = pd.DatetimeIndex(sorted(set().union(*[set(s.index) for s in series.values()])))
        out["ts"] = iso(idx)
        out["zones"] = {z: to_list(s.reindex(idx)) for z, s in series.items()}
    return out


def _corr(a, b):
    """Két azonos indexű Series Pearson-korrelációja (csak a közös, érvényes pontokon); nincs elég adat -> None."""
    d = pd.concat([a, b], axis=1).dropna()
    if len(d) < 12 or d.iloc[:, 0].std() == 0 or d.iloc[:, 1].std() == 0:
        return None
    return float(d.iloc[:, 0].corr(d.iloc[:, 1]))


def _adjacency():
    """Szomszédsági gráf az entsoe-py NEIGHBOURS táblájából, szimmetrizálva (hiányzó zónákhoz is: UA, BY, TR, ...)."""
    try:
        from entsoe.mappings import NEIGHBOURS as NB
    except Exception:  # noqa: BLE001
        return {}
    adj = {}
    for k, vs in NB.items():
        for v in vs:
            adj.setdefault(k, set()).add(v)
            adj.setdefault(v, set()).add(k)
    return adj


def _members(z, adj):
    """Egy ország / csoport tagzónái a határáramlás-összegzéshez."""
    if z in ZONE_GROUPS:
        return list(ZONE_GROUPS[z])
    if z in ZONE_FIRST:
        have = [x for x in ZONE_FIRST[z] if x in adj]
        return have[:1] or [z]
    return [z]


def collect_countries(client, now=None, hours=168, budget_s=240, workers=8, zones=None):
    """Más országok (zónák) óránkénti adatai a mérnöki oldal országválasztójához (countries.json):
    fogyasztás (tény, előrejelzés), termelés típusonként, nap/szél előrejelzés, nettó import (day-ahead nettó pozíció),
    eltérési ár. A magyar adat az engineer.json-ban van, ide nem kerül.

    Nettó import (import = pozitív): a zóna összes határán mért fizikai áramlás (12.1.G) különbsége (bejövő - kimenő).
    A day-ahead nettó pozíciót (12.1.E) már nem használjuk: az entsoe-py a sorozat abszolút értékét adja vissza
    (előjel nélkül), ezért az irány nem megbízható, ráadásul menetrend, nem fizikai mérés.
    """
    now = now or pd.Timestamp.now(tz="UTC")
    zones = [z for z in (zones or ALL_ZONES) if z != HOME]
    start = (now - pd.Timedelta(hours=hours)).floor("h")
    local = now.tz_convert("Europe/Budapest").normalize()
    end = (local + pd.DateOffset(days=2)).tz_convert("UTC")
    idx = pd.date_range(start, end, freq="h", tz="UTC", inclusive="left")
    B = Batch(budget_s, workers=workers)
    # fontossági sorrend: először mindenhol a fogyasztás és a termelés, aztán a többi
    for z in zones:
        B.add(f"fogyasztás {z}", lambda z=z: client.query_load(z, start=start, end=end))
        B.add(f"termelés {z}", lambda z=z: client.query_generation(z, start=start, end=end, nett=True))
    adj = _adjacency()
    members = {z: _members(z, adj) for z in zones}
    pairs, borders = [], {}                      # irányított (a, b) párok és zónánként a külső határok listája
    seen = set()
    for z in zones:
        bl = []
        for m in members[z]:
            for n in sorted(adj.get(m, ())):
                if n in members[z]:
                    continue
                bl.append((m, n))
                for pr in ((n, m), (m, n)):
                    if pr not in seen:
                        seen.add(pr); pairs.append(pr)
        borders[z] = bl
    f_start, f_end = start, min(end, (now + pd.Timedelta(hours=2)).ceil("h"))
    for a, b in pairs:
        B.add(f"határáramlás {a}->{b}", lambda a=a, b=b: client.query_crossborder_flows(a, b, start=f_start, end=f_end))
    for z in zones:
        B.add(f"fogyasztás előrejelzés {z}", lambda z=z: client.query_load_forecast(z, start=start, end=end))
    for z in zones:
        B.add(f"nap/szél előrejelzés {z}", lambda z=z: client.query_wind_and_solar_forecast(z, start=start, end=end))
        B.add(f"eltérési ár {z}", lambda z=z: client.query_imbalance_prices(z, start=start, end=end))

    out_z, corr_log = {}, {}
    for z in zones:
        rec = {}
        la = B.get(f"fogyasztás {z}")
        lf = B.get(f"fogyasztás előrejelzés {z}")
        if la is not None or lf is not None:
            rec["load"] = {"actual": hourly_list(la, idx), "forecast": hourly_list(lf, idx)}
        gdf = B.get(f"termelés {z}")
        gen_total = None
        if gdf is not None:
            by_type = flatten_types(gdf)
            rec["generation"] = group_sum(by_type, idx)
            parts = [pd.Series(v, index=idx, dtype="float64") for v in rec["generation"].values()]
            if parts:
                gen_total = pd.concat(parts, axis=1).sum(axis=1, min_count=len(parts))
        fdf = B.get(f"nap/szél előrejelzés {z}")
        if fdf is not None:
            ft = flatten_types(fdf)
            sw = {}
            for k, names in {"solar": ["Solar"], "wind": ["Wind Onshore", "Wind Offshore"]}.items():
                got = [ft[n].reindex(idx) for n in names if n in ft]
                sw[k] = to_list(pd.concat(got, axis=1).sum(axis=1, min_count=1)) if got else None
            if any(v is not None for v in sw.values()):
                rec["solar_wind_forecast"] = sw
        comps, have_b = [], 0
        for m, n in borders.get(z, []):
            fin, fout = B.get(f"határáramlás {n}->{m}"), B.get(f"határáramlás {m}->{n}")
            if fin is None and fout is None:
                continue
            have_b += 1
            if fin is not None:
                comps.append(hourly_mean(fin.iloc[:, 0] if isinstance(fin, pd.DataFrame) else fin).reindex(idx))
            if fout is not None:
                comps.append(-hourly_mean(fout.iloc[:, 0] if isinstance(fout, pd.DataFrame) else fout).reindex(idx))
        if comps:
            df = pd.concat(comps, axis=1)
            nb_total = max(1, len(borders.get(z, [])))
            # egy órát csak akkor fogadunk el, ha a határok legalább 70 %-áról van mérés (különben a mérleg torz lenne)
            ok = df.notna().sum(axis=1) >= max(1.0, 0.7 * len(comps))
            net = df.sum(axis=1, min_count=1).where(ok)
            if rec.get("load", {}).get("actual") is not None and gen_total is not None:
                resid = pd.Series(rec["load"]["actual"], index=idx, dtype="float64") - gen_total
                c = _corr(net, resid)
                corr_log[z] = None if c is None else round(c, 2)
            rec["net_import_mw"] = to_list(net)
            rec["net_borders"] = [have_b, nb_total]
        ip = B.get(f"eltérési ár {z}")
        if ip is not None:
            cols = {str(c).lower(): c for c in ip.columns}
            lc = next((v for k, v in cols.items() if "long" in k), None)
            sc = next((v for k, v in cols.items() if "short" in k), None)
            imb = {"long": hourly_list(ip[lc], idx) if lc is not None else None,
                   "short": hourly_list(ip[sc], idx) if sc is not None else None}
            if lc is None and sc is None:
                imb["long"] = hourly_list(ip.iloc[:, 0], idx)
            rec["imbalance"] = imb
        if rec:
            out_z[z] = rec
    B.close()
    return {
        "generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "ENTSO-E Transparency Platform",
        "demo": False,
        "hourly_ts": iso(idx),
        "names": {z: ALL_ZONES[z] for z in zones},
        "zones": out_z,
        "co2": {"factors": CO2_FACTORS, "source": CO2_SOURCE},
        "netpos_corr": corr_log,
        "errors": B.errors + B.notes(),
        "missing": B.missing,
    }


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default="data.json")
    p.add_argument("--engineer-out", default=None, help="alapértelmezés: engineer.json a --out mellett")
    p.add_argument("--skip-engineer", action="store_true", help="a mérnöki adatkörök kihagyása")
    p.add_argument("--hours", type=int, default=168, help="ennyi órára visszamenőleg kéri az adatokat (az oldalak időablaka ebből választ)")
    p.add_argument("--countries-budget", type=int, default=420, help="az országadatok időkerete másodpercben")
    p.add_argument("--skip-countries", action="store_true", help="az országválasztó adatainak (countries.json) kihagyása")
    p.add_argument("--workers", type=int, default=12, help="egyszerre ennyi ENTSO-E kérés fut")
    p.add_argument("--budget", type=int, default=240, help="a fő és a mérnöki rész időkerete külön-külön, másodpercben")
    args = p.parse_args()

    token = os.environ.get("ENTSOE_TOKEN", "").strip()
    if not token:
        sys.exit("Hiányzik az ENTSOE_TOKEN környezeti változó.")

    from entsoe import EntsoePandasClient

    # retry_delay: az alapértelmezett 60 s várakozás egy hibás kérés után percekre megállítaná a futást;
    # timeout: egy elakadt kérés ne tartson fel mindent.
    client = GroupClient(EntsoePandasClient(api_key=token, retry_count=2, retry_delay=5, timeout=45))
    data = collect(client, hours=args.hours, budget_s=args.budget, workers=args.workers)
    if not any(b["last_ts"] for b in data["borders"]):
        sys.exit("Egyik határra sem érkezett áramlási adat; a data.json nem íródik felül.")

    write_json(args.out, data)
    ok = [b["code"] for b in data["borders"] if b["last_ts"]]
    print(f"Kész: {args.out} | határok adattal: {ok} | hibák: {len(data['errors'])}")
    for e in data["errors"]:
        print("  -", e)

    eu_out = os.path.join(os.path.dirname(os.path.abspath(args.out)), "europe.json")
    try:
        eu = collect_europe(client, budget_s=min(args.budget, 240), workers=args.workers)
        if eu["zones"]:
            write_json(eu_out, eu)
            print(f"Kész: {eu_out} | zónák: {sorted(eu['zones'])} | hibák: {len(eu['errors'])}")
        else:
            print("FIGYELEM: az európai árakra semmi sem érkezett; az europe.json nem íródik felül.")
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        print(f"FIGYELEM: az európai árak gyűjtése meghiúsult ({exc.__class__.__name__}); az europe.json nem íródik felül.")

    if args.skip_engineer:
        return
    eng_out = args.engineer_out or os.path.join(os.path.dirname(os.path.abspath(args.out)), "engineer.json")
    try:
        eng = collect_engineer(client, hours=args.hours, main=data, budget_s=args.budget, workers=args.workers)
    except (Exception, SystemExit) as exc:  # a mérnöki rész hibája nem borítja a fő oldalt
        print(f"FIGYELEM: a mérnöki adatgyűjtés meghiúsult ({exc.__class__.__name__}: {exc}); az engineer.json nem íródik felül.")
        return
    if not any(eng["modules"].values()):
        print("FIGYELEM: a mérnöki adatkörökre semmi sem érkezett; az engineer.json nem íródik felül.")
        return
    write_json(eng_out, eng)
    got = [k for k, v in eng["modules"].items() if v]
    lack = [k for k, v in eng["modules"].items() if not v]
    print(f"Kész: {eng_out} | van adat: {got} | nincs: {lack} | hibák: {len(eng['errors'])}")
    for e in eng["errors"]:
        print("  -", e)
    fin = eng.get("finance")
    print("17.1.I pénzügyi mérleg:", "nincs adat" if not fin else f"{len(fin['months'])} hónap ({fin['months'][0]}–{fin['months'][-1]}), pénznem: {fin['currency']}, irányok: up/down{(' + ' + str(fin['other_directions'])) if fin.get('other_directions') else ''}")
    if fin:
        print("  nyers szerkezet:", json.dumps(fin.get("raw_structure"), ensure_ascii=False)[:400])
    print("aFRR/mFRR/szabályozás adatai:", sorted(k for k, v in (eng.get("balancing") or {}).items() if v) or "nincs")

    if args.skip_countries:
        return
    cn_out = os.path.join(os.path.dirname(os.path.abspath(args.out)), "countries.json")
    try:
        cn = collect_countries(client, hours=args.hours, budget_s=args.countries_budget, workers=args.workers)
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        print(f"FIGYELEM: az országadatok gyűjtése meghiúsult ({exc.__class__.__name__}: {exc}); a countries.json nem íródik felül.")
        return
    if not cn["zones"]:
        print("FIGYELEM: az országadatokra semmi sem érkezett; a countries.json nem íródik felül.")
        return
    write_json(cn_out, cn)
    print(f"Kész: {cn_out} | zónák: {sorted(cn['zones'])} | nettó import: fizikai határáramlásból | korreláció (fogyasztás-termelés ↔ nettó import): {cn['netpos_corr']} | hibák: {len(cn['errors'])}")
    for e in cn["errors"][:30]:
        print("  -", e)


if __name__ == "__main__":
    main()
