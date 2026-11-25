#!/usr/bin/env python3
"""Földgáz-adatgyűjtő az Európa és trendek oldal földgáz-szekcióihoz (europa.html). Kimenet: gas.json.

Három forrás, egymástól függetlenül (az egyik hibája nem viszi el a másikat):

1. GIE AGSI+ (https://agsi.gie.eu/api): a tárolók töltöttsége, a tárolt mennyiség (TWh), a munkagáz-kapacitás,
   a betáplálás/kivétel (GWh/nap) és ezek kapacitása. Magyarország, az EU összesen és a szomszédos/fontos országok.
   Ingyenes személyes kulcs kell hozzá (https://agsi.gie.eu regisztráció), környezeti változó: GIE_API_KEY,
   a kulcs a `x-key` fejlécben megy. Korlát: 60 hívás/perc, ezért a hívások között ~1,1 s szünet van,
   és ha már van gas.json, csak az utolsó napok töltődnek újra.
2. GIE ALSI (https://alsi.gie.eu/api): az LNG-terminálok napi készlete (GWh), kiadása a gázrendszerbe (send-out, GWh/nap),
   a névleges maximális készlet (DTMI) és referencia-kiadás (DTRS). EU összesen, országonként és terminálonként.
   Ugyanaz a GIE_API_KEY és ugyanaz az `x-key` fejléc, mint az AGSI+-nál; ha az ALSI nem elérhető, a többi rész ettől még megvan.
3. ENTSOG Transparency Platform (https://transparency.entsog.eu/api/v1): a magyar határpontok fizikai gázáramlása
   (indikátor: "Physical Flow", napi, kWh/nap -> GWh/nap). Kulcs nem kell. A határpontokat futáskor maga
   deríti fel az /interconnections végpontról (a magyar üzemeltető oldalán), nincs bedrótozott kulcslista.

Futtatás:
    export GIE_API_KEY="a-te-kulcsod"
    python gas.py --out gas.json

A kulcs csak a környezeti változóban él, a böngészőbe nem kerül.
"""
import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

AGSI_BASE = "https://agsi.gie.eu/api"
ALSI_BASE = "https://alsi.gie.eu/api"
ENTSOG_BASE = "https://transparency.entsog.eu/api/v1"

COUNTRY_NAMES = {
    "HU": "Magyarország", "AT": "Ausztria", "SK": "Szlovákia", "RO": "Románia", "HR": "Horvátország",
    "CZ": "Csehország", "DE": "Németország", "IT": "Olaszország", "PL": "Lengyelország", "BG": "Bulgária",
    "NL": "Hollandia", "FR": "Franciaország", "UA": "Ukrajna", "RS": "Szerbia", "SI": "Szlovénia",
    "EU": "EU összesen",
    "ES": "Spanyolország", "BE": "Belgium", "PT": "Portugália", "GR": "Görögország", "LT": "Litvánia", "FI": "Finnország",
    "SE": "Svédország", "GB": "Egyesült Királyság", "MT": "Málta", "EE": "Észtország", "CY": "Ciprus", "TR": "Törökország",
    "LV": "Lettország", "IE": "Írország", "DK": "Dánia", "NO": "Norvégia",
}
# sorrend = fontossági sorrend (a legfontosabbak először)
AGSI_COUNTRIES = ["HU", "AT", "SK", "RO", "HR", "UA", "DE", "IT", "CZ", "PL", "BG", "NL", "FR"]
FULL_FIELDS = ("full", "gis", "wgv", "inj", "wdr", "injCap", "wdrCap", "trend")   # HU és EU
LITE_FIELDS = ("full", "gis", "wgv")                                               # a többi ország
AGSI_KEYS = {"full": "full", "gis": "gasInStorage", "wgv": "workingGasVolume", "inj": "injection",
             "wdr": "withdrawal", "injCap": "injectionCapacity", "wdrCap": "withdrawalCapacity", "trend": "trend"}
DEC = {"full": 1, "gis": 3, "wgv": 3, "inj": 1, "wdr": 1, "injCap": 1, "wdrCap": 1, "trend": 3}
# LNG (ALSI): ha az EU-összesítő nem árulja el az országokat, ezekkel próbálkozunk; a GB nem EU-tag, de lehet adata
LNG_FALLBACK = ["ES", "FR", "IT", "NL", "BE", "PL", "DE", "GR", "PT", "LT", "HR", "FI", "SE", "MT", "GB"]
LNG_EXTRA = ["GB"]
LNG_FIELDS = ("inv", "send", "dtmi", "dtrs")      # készlet GWh, kiadás GWh/nap, max. készlet GWh, referencia-kiadás GWh/nap
LNG_FAC_DAYS = 400                                # a terminálonkénti napi sorozat hossza
DEFAULT_FROM = "2021-10-01"      # a 2021/22-es gázév kezdete


# ------------------------------------------------------------------ HTTP
class Http:
    """Vékony réteg a requests fölött, hogy a tesztben kitalált klienssel lehessen helyettesíteni.
    get(url, params, headers) -> kiértékelt JSON; hibára kivételt dob (status_code attribútummal)."""

    def get(self, url, params=None, headers=None, timeout=60):
        import requests
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        if r.status_code >= 400:
            err = RuntimeError(f"HTTP {r.status_code}")
            err.status_code = r.status_code
            raise err
        return r.json()


class Throttle:
    """Legalább `gap` másodperc két hívás indítása között (AGSI+: 60 hívás/perc)."""

    def __init__(self, gap=1.1):
        self.gap, self.last, self.lock = gap, 0.0, threading.Lock()

    def wait(self):
        with self.lock:
            d = self.last + self.gap - time.monotonic()
            if d > 0:
                time.sleep(d)
            self.last = time.monotonic()


def num(v):
    """AGSI+: a számok idézőjeles szövegek, a hiányt "-" vagy null jelzi."""
    if v is None:
        return None
    try:
        return float(str(v).strip().replace(",", "."))
    except ValueError:
        return None


def status_of(exc):
    return getattr(exc, "status_code", None)


# ------------------------------------------------------------------ AGSI+
def agsi_fetch(http, key, throttle, params, deadline, errors, label, base=AGSI_BASE, tag="AGSI", fatal=True):
    """Az összes oldal egy lekérdezéshez (AGSI+ és ALSI egyaránt). Visszaadja a rekordok listáját (vagy üreset).
    fatal=False: hibás kulcsnál nem állítja le a futást, csak jelzi (az ALSI-nál, hogy a tározói rész megmaradjon)."""
    rows, page = [], 1
    while True:
        if time.monotonic() > deadline:
            errors.append(f"{tag} {label}: időkeret lejárt")
            break
        p = dict(params, page=page, size=300)
        data = None
        for attempt in (1, 2):
            throttle.wait()
            try:
                data = http.get(base, params=p, headers={"x-key": key})
                break
            except Exception as exc:  # noqa: BLE001
                st = status_of(exc)
                if st in (401, 403):
                    if fatal:
                        sys.exit(f"{tag} HTTP {st}: érvénytelen vagy hiányzó GIE_API_KEY.")
                    errors.append(f"{tag} {label}: HTTP {st} (a kulcs nem érvényes erre a platformra)")
                    return rows
                if st == 429 and attempt == 1:
                    time.sleep(61)         # a limit túllépése 60 másodperces blokkot ad
                    continue
                if attempt == 1:
                    time.sleep(3)
                    continue
                errors.append(f"{tag} {label}: {exc.__class__.__name__} {exc}")
        if data is None:
            break
        rows += data.get("data") or []
        last = int(data.get("last_page") or 1)
        if page >= last:
            break
        page += 1
    return rows


def parse_rows(rows, fields):
    out = {}
    for r in rows:
        d = str(r.get("gasDayStart") or "")[:10]
        if len(d) != 10:
            continue
        out[d] = {f: num(r.get(AGSI_KEYS[f])) for f in fields}
        out[d]["status"] = r.get("status")
    return out


def flatten_children(rec, depth=0):
    """A legutóbbi országos rekord gyermekei (társaságok, esetleg telephelyek) laposan."""
    res = []
    for ch in rec.get("children") or []:
        res.append({
            "name": ch.get("name"), "code": ch.get("code"), "level": depth,
            "full": num(ch.get("full")), "gis": num(ch.get("gasInStorage")), "wgv": num(ch.get("workingGasVolume")),
            "inj": num(ch.get("injection")), "wdr": num(ch.get("withdrawal")),
            "injCap": num(ch.get("injectionCapacity")), "wdrCap": num(ch.get("withdrawalCapacity")),
            "status": ch.get("status"),
        })
        if depth < 1:
            res += flatten_children(ch, depth + 1)
    return res


def collect_agsi(http, key, existing=None, from_date=DEFAULT_FROM, today=None, budget_s=420, throttle=None):
    today = today or date.today()
    throttle = throttle or Throttle()
    deadline = time.monotonic() + budget_s
    errors = []
    old = (existing or {}).get("series") or {}
    old_dates = (existing or {}).get("dates") or []
    # inkrementális: ha a régi adat lefedi a kezdetet, csak az utolsó ~14 napot kérjük újra
    inc_from = None
    if old_dates and old_dates[0] <= from_date:
        inc_from = (datetime.strptime(old_dates[-1], "%Y-%m-%d").date() - timedelta(days=14)).isoformat()
    start = inc_from or from_date

    per = {}                     # kód -> {dátum: értékek}
    facilities, hu_latest, upd = [], None, None
    for code in ["EU"] + AGSI_COUNTRIES:
        fields = FULL_FIELDS if code in ("HU", "EU") else LITE_FIELDS
        params = {"type": "eu"} if code == "EU" else {"country": code}
        params.update({"from": start, "to": today.isoformat()})
        rows = agsi_fetch(http, key, throttle, params, deadline, errors, code)
        if not rows:
            continue
        per[code] = parse_rows(rows, fields)
        if code == "HU":
            newest = max(rows, key=lambda r: str(r.get("gasDayStart")))
            facilities = flatten_children(newest)
            hu_latest = str(newest.get("gasDayStart"))[:10]
            upd = newest.get("updatedAt")

    if not per.get("HU"):
        return None, errors
    # régi + új összefésülése (az új felülír)
    merged = {}
    for code, fields in [(c, FULL_FIELDS if c in ("HU", "EU") else LITE_FIELDS) for c in ["EU"] + AGSI_COUNTRIES]:
        m = {}
        if code in old and old_dates:
            for i, d in enumerate(old_dates):
                if d >= from_date:
                    m[d] = {f: (old[code].get(f) or [None] * len(old_dates))[i] for f in fields}
        if code in per:
            m.update(per[code])
        if m:
            merged[code] = m
    dates = sorted({d for m in merged.values() for d in m if d >= from_date})
    series = {}
    for code, m in merged.items():
        fields = FULL_FIELDS if code in ("HU", "EU") else LITE_FIELDS
        series[code] = {f: [None if m.get(d, {}).get(f) is None else round(m[d][f], DEC[f]) for d in dates] for f in fields}
    return {
        "dates": dates, "series": series,
        "names": {c: COUNTRY_NAMES.get(c, c) for c in series},
        "hu_last_day": hu_latest, "hu_updated": upd,
        "facilities": facilities,
    }, errors


# ------------------------------------------------------------------ ALSI (LNG)
def lng_pair(v):
    """Az ALSI mennyiségei {"lng": 10^3 m3 LNG, "gwh": GWh} párok; ha csak szám jön, GWh-nak vesszük."""
    if isinstance(v, dict):
        return num(v.get("lng")), num(v.get("gwh"))
    return None, num(v)


def lng_vals(rec):
    """Egy ALSI rekord (ország vagy terminál) mérőszámai. inv/dtmi: GWh, send/dtrs: GWh/nap."""
    inv_l, inv_g = lng_pair(rec.get("inventory"))
    dt_l, dt_g = lng_pair(rec.get("dtmi"))
    return {"inv": inv_g, "send": num(rec.get("sendOut")), "dtmi": dt_g, "dtrs": num(rec.get("dtrs")),
            "invLng": inv_l, "dtmiLng": dt_l}


def lng_leaves(rec):
    """A rekord alatti terminálok (a levélcsomópontok), a vállalatuk nevével. EU -> ország -> vállalat -> terminál."""
    res = []

    def walk(node, company):
        kids = node.get("children") or []
        if not kids:
            res.append((node, company))
            return
        for ch in kids:
            walk(ch, node.get("name") if node is not rec else company)
    for ch in rec.get("children") or []:
        walk(ch, None)
    return res


def collect_alsi(http, key, existing=None, from_date=DEFAULT_FROM, today=None, budget_s=420, throttle=None):
    """Visszaad: (lng szótár vagy None, hibák). Inkrementális, mint az AGSI+: csak az utolsó ~14 nap töltődik újra."""
    today = today or date.today()
    throttle = throttle or Throttle()
    deadline = time.monotonic() + budget_s
    errors = []
    old = existing or {}
    old_dates = old.get("dates") or []
    inc_from = None
    if old_dates and old_dates[0] <= from_date:
        inc_from = (datetime.strptime(old_dates[-1], "%Y-%m-%d").date() - timedelta(days=14)).isoformat()
    start = inc_from or from_date
    fac_cut = (today - timedelta(days=LNG_FAC_DAYS)).isoformat()
    fac_start = max(start, fac_cut)

    def fetch(label, params):
        return agsi_fetch(http, key, throttle, params, deadline, errors, label, base=ALSI_BASE, tag="ALSI", fatal=False)

    per = {}                       # kód -> {dátum: {mező: érték}}
    fac = {}                       # terminál-kulcs -> {meta, days:{dátum: (inv, send)}, latest}
    names = {}
    last_day, upd = None, None

    # 1) EU összesen (+ az országok felderítése a legutóbbi rekord gyermekeiből)
    rows = fetch("EU", {"type": "eu", "from": start, "to": today.isoformat()})
    if not rows:
        return None, errors
    per["EU"] = {str(r.get("gasDayStart"))[:10]: lng_vals(r) for r in rows if len(str(r.get("gasDayStart") or "")) >= 10}
    newest = max(rows, key=lambda r: str(r.get("gasDayStart")))
    last_day, upd = str(newest.get("gasDayStart"))[:10], newest.get("updatedAt")
    found = []
    for ch in newest.get("children") or []:
        c = str(ch.get("code") or "").upper()
        if len(c) == 2 and c.isalpha():
            found.append(c)
            names[c] = ch.get("name")
    countries = [c for c in found if c != "EU"] or list(LNG_FALLBACK)
    for c in LNG_EXTRA:
        if c not in countries:
            countries.append(c)

    # 2) országonként: napi sorozat + a terminálok napi értékei (ugyanabból a válaszból)
    for code in countries:
        rows = fetch(code, {"country": code, "from": start, "to": today.isoformat()})
        if not rows:
            continue
        per[code] = {}
        for r in rows:
            d = str(r.get("gasDayStart") or "")[:10]
            if len(d) != 10:
                continue
            per[code][d] = lng_vals(r)
            for node, company in lng_leaves(r):
                key_ = node.get("code") or f"{code}:{node.get('name')}"
                f = fac.setdefault(key_, {"meta": {}, "days": {}, "latest": None})
                v = lng_vals(node)
                if d >= fac_start:
                    f["days"][d] = (v["inv"], v["send"])
                if f["latest"] is None or d >= f["latest"][0]:
                    f["latest"] = (d, v, node.get("status"))
                    f["meta"] = {"name": node.get("name"), "code": node.get("code"), "company": company, "country": code,
                                 "type": node.get("type"), "lat": num(node.get("latitude")), "lon": num(node.get("longitude"))}
    if len(per) < 2:
        errors.append("ALSI: az országos sorozatok nem érkeztek meg")
        return None, errors

    # 3) régi + új összefésülése (az új felülír)
    old_series = old.get("series") or {}
    merged = {}
    for code, m_new in per.items():
        m = {}
        if code in old_series and old_dates:
            for i, d in enumerate(old_dates):
                if d >= from_date:
                    m[d] = {f_: (old_series[code].get(f_) or [None] * len(old_dates))[i] for f_ in LNG_FIELDS}
        m.update({d: {f_: v.get(f_) for f_ in LNG_FIELDS} for d, v in m_new.items()})
        merged[code] = m
    for code, sr in old_series.items():             # ami most nem jött meg, az régi értékekkel megmarad
        if code not in merged and old_dates:
            merged[code] = {d: {f_: (sr.get(f_) or [None] * len(old_dates))[i] for f_ in LNG_FIELDS}
                            for i, d in enumerate(old_dates) if d >= from_date}
    dates = sorted({d for m in merged.values() for d in m if d >= from_date})
    series = {code: {f_: [None if m.get(d, {}).get(f_) is None else round(m[d][f_], 1) for d in dates] for f_ in LNG_FIELDS}
              for code, m in merged.items() if m}

    # terminálok: a legutóbbi pillanatkép + a napi sorozat az utolsó LNG_FAC_DAYS napra
    old_fd = old.get("fac_dates") or []
    old_fac = {(x.get("code") or f"{x.get('country')}:{x.get('name')}"): x for x in (old.get("fac") or [])}
    fac_dates = sorted({d for d in dates if d >= fac_cut})
    facs = []
    for key_, f in fac.items():
        d_new = f["days"]
        old_x = old_fac.get(key_) or {}
        inv_s, snd_s = [], []
        for d in fac_dates:
            if d in d_new:
                inv_s.append(d_new[d][0])
                snd_s.append(d_new[d][1])
            elif d in old_fd and old_x.get("inv"):
                j = old_fd.index(d)
                inv_s.append(old_x["inv"][j])
                snd_s.append(old_x["send"][j])
            else:
                inv_s.append(None)
                snd_s.append(None)
        d_l, v, st = f["latest"]
        meta = f["meta"]
        facs.append({
            "name": meta["name"], "code": meta["code"], "company": meta["company"], "country": meta["country"],
            "type": meta["type"], "lat": meta["lat"], "lon": meta["lon"],
            "inv": [None if x is None else round(x, 1) for x in inv_s], "send": [None if x is None else round(x, 1) for x in snd_s],
            "latest": {"date": d_l, "status": st, **{k: (None if v[k] is None else round(v[k], 2)) for k in ("inv", "send", "dtmi", "dtrs", "invLng", "dtmiLng")}},
        })
    facs.sort(key=lambda x: -(x["latest"]["dtmi"] or 0))
    if not names.get("EU"):
        names["EU"] = COUNTRY_NAMES["EU"]
    return {
        "dates": dates, "series": series,
        "names": {c: COUNTRY_NAMES.get(c) or names.get(c) or c for c in series},
        "fac_dates": fac_dates, "fac": facs,
        "last_day": last_day, "updated": upd,
    }, errors


# ------------------------------------------------------------------ ENTSOG
def entsog_list(js):
    """Az ENTSOG-válasz rekordlistája; a kulcs neve (operationaldatas / operationalData ...) kisbetűsítve keresendő."""
    if isinstance(js, list):
        return js
    for k, v in js.items():
        if isinstance(v, list) and k.lower() in ("operationaldatas", "operationaldata", "interconnections", "data"):
            return v
    for v in js.values():
        if isinstance(v, list):
            return v
    return []


def _first(r, names):
    for n in names:
        v = r.get(n)
        if v not in (None, ""):
            return str(v)
    return ""


def discover_from_opd(http, errors):
    """Elsődleges út: /operatorpointdirections?hasData=1 (a kézikönyv szerint innen kell venni a pointDirection értékeit).
    A magyar üzemeltető (HU-...) pontjai, amelyeknek a szomszédos oldala másik ország."""
    try:
        js = http.get(f"{ENTSOG_BASE}/operatorpointdirections", params={"hasData": 1, "limit": -1}, timeout=90)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ENTSOG operatorpointdirections: {exc.__class__.__name__} {exc}")
        return []
    pts, seen, hu_rows, fields = [], set(), 0, set()
    for r in entsog_list(js):
        op = str(r.get("operatorKey") or "")
        if not op.startswith("HU"):
            continue
        hu_rows += 1
        fields |= set(r)
        pk = r.get("pointKey")
        side = str(r.get("directionKey") or "").lower()
        nb = _first(r, ("adjacentCountry", "adjacentCountryKey", "adjacentCountryLabel", "connectedCountry")).upper()[:2]
        if not pk or side not in ("entry", "exit") or not nb or nb == "HU":
            continue
        if (op, pk, side) in seen:
            continue
        seen.add((op, pk, side))
        pts.append({"id": f"{pk}|{side}", "label": r.get("pointLabel") or pk, "country": nb, "side": side, "op": op, "point": pk})
    if hu_rows and not pts:
        errors.append("ENTSOG operatorpointdirections: van magyar rekord, de nincs szomszéd-ország mező; mezők: " + ", ".join(sorted(fields)))
    return pts


def discover_from_interconnections(http, errors):
    """Tartalék út: /interconnections (a from/to ország- és üzemeltetőkulcs mezőkre épül)."""
    try:
        js = http.get(f"{ENTSOG_BASE}/interconnections", params={"limit": -1}, timeout=90)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ENTSOG interconnections: {exc.__class__.__name__} {exc}")
        return []
    pts, seen = [], set()
    for r in entsog_list(js):
        fc, tc = str(r.get("fromCountryKey") or ""), str(r.get("toCountryKey") or "")
        pk = r.get("pointKey")
        if not pk or "HU" not in (fc, tc) or fc == tc:
            continue
        if fc == "HU":
            side, op, nb = "exit", r.get("fromOperatorKey"), tc
        else:
            side, op, nb = "entry", r.get("toOperatorKey"), fc
        if not op or (op, pk, side) in seen:
            continue
        seen.add((op, pk, side))
        pts.append({"id": f"{pk}|{side}", "label": r.get("pointLabel") or pk, "country": nb, "side": side,
                    "op": op, "point": pk})
    return pts


def discover_points(http, errors):
    """A magyar határpontok és irányaik: [{"id","label","country","side":"entry|exit","op","point"}];
    a side a magyar üzemeltető oldala. Futáskor derítjük fel, nincs bedrótozott kulcslista."""
    pts = discover_from_opd(http, errors) or discover_from_interconnections(http, errors)
    if not pts:
        errors.append("ENTSOG pontfelderítés: nem találtam magyar határpontot")
    return pts


def collect_flows(http, days=400, today=None, budget_s=300, workers=4):
    today = today or date.today()
    errors, notes = [], []
    pts = discover_points(http, errors)
    if not pts:
        return None, errors, notes
    deadline = time.monotonic() + budget_s
    start = today - timedelta(days=days)
    windows, a = [], start
    while a <= today:
        b = min(a + timedelta(days=119), today)
        windows.append((a, b))
        a = b + timedelta(days=1)
    chunks = [pts[i:i + 8] for i in range(0, len(pts), 8)]

    def job(win, chunk):
        if time.monotonic() > deadline:
            return "skip", []
        pd_ = ",".join(f"{p['op']}{p['point']}{p['side']}" for p in chunk)
        params = {"indicator": "Physical Flow", "periodType": "day", "pointDirection": pd_,
                  "from": win[0].isoformat(), "to": win[1].isoformat(), "limit": -1, "timeZone": "CET", "timezone": "CET"}
        last = None
        for attempt in (1, 2):
            try:
                return "ok", entsog_list(http.get(f"{ENTSOG_BASE}/operationaldatas", params=params, timeout=90))
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(3 * attempt)
        return f"err:{last.__class__.__name__} {last}", []

    futs = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for w in windows:
            for c in chunks:
                futs.append(ex.submit(job, w, c))
    vals = {}                                    # id -> {nap: GWh/nap}
    skipped = 0
    for f in futs:
        st, recs = f.result()
        if st == "skip":
            skipped += 1
        elif st.startswith("err"):
            errors.append(f"ENTSOG áramlás: {st[4:]}")
        for r in recs:
            if str(r.get("indicator", "Physical Flow")) != "Physical Flow":
                continue
            v = num(r.get("value"))
            day = str(r.get("periodFrom") or "")[:10]
            pid = f"{r.get('pointKey')}|{r.get('directionKey')}"
            if v is None or len(day) != 10:
                continue
            unit = str(r.get("unit") or "kWh/d")
            k = 1e-6 if unit.lower().startswith("kwh") else 1e-3 if unit.lower().startswith("mwh") else 1.0
            vals.setdefault(pid, {})[day] = vals.setdefault(pid, {}).get(day, 0.0) + v * k
    if skipped:
        notes.append(f"ENTSOG: az időkeret lejárt, kihagyott kérések: {skipped}")
    pts = [p for p in pts if p["id"] in vals]
    if not pts:
        errors.append("ENTSOG: a felderített pontokra nem érkezett fizikai áramlási adat")
        return None, errors, notes
    alld = sorted({d for p in pts for d in vals[p["id"]]})
    return {
        "days": alld,
        "points": [{"id": p["id"], "label": p["label"], "country": p["country"], "side": p["side"],
                    "gwh": [None if vals[p["id"]].get(d) is None else round(vals[p["id"]][d], 2) for d in alld]}
                   for p in sorted(pts, key=lambda q: (q["country"], q["label"], q["side"]))],
        "unit": "GWh/nap",
    }, errors, notes


# ------------------------------------------------------------------ összerakás
def collect(http, key, existing=None, today=None, budget_s=420, from_date=DEFAULT_FROM, throttle=None):
    today = today or date.today()
    errors, notes = [], []
    out = {
        "schema": 1, "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "GIE AGSI+; GIE ALSI; ENTSOG Transparency Platform", "demo": False,
        "agsi": None, "lng": None, "flows": None, "errors": errors, "notes": notes,
    }
    if key:
        try:
            agsi, e = collect_agsi(http, key, (existing or {}).get("agsi"), from_date, today, budget_s, throttle)
            errors += e
            out["agsi"] = agsi
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(f"AGSI+: {exc.__class__.__name__} {exc}")
    else:
        errors.append("AGSI+: nincs GIE_API_KEY, a tározói adatok kimaradnak")
    if key:
        try:
            lng, e = collect_alsi(http, key, (existing or {}).get("lng"), from_date, today, budget_s, throttle)
            errors += e
            out["lng"] = lng
        except Exception as exc:  # noqa: BLE001
            errors.append(f"ALSI: {exc.__class__.__name__} {exc}")
    try:
        flows, e, n = collect_flows(http, today=today)
        errors += e
        notes += n
        out["flows"] = flows
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ENTSOG: {exc.__class__.__name__} {exc}")
    # ha egy rész most nem sikerült, a korábbi jó adat megmarad (jelezve)
    for part in ("agsi", "lng", "flows"):
        if out[part] is None and (existing or {}).get(part):
            out[part] = existing[part]
            notes.append(f"{part}: most nem sikerült frissíteni, az előző futás adata maradt")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="gas.json")
    ap.add_argument("--from-date", default=DEFAULT_FROM)
    ap.add_argument("--budget", type=int, default=420, help="az AGSI+ rész időkerete, másodpercben")
    args = ap.parse_args()
    key = os.environ.get("GIE_API_KEY", "").strip()
    existing = None
    if os.path.exists(args.out):
        try:
            with open(args.out, encoding="utf-8") as f:
                existing = json.load(f)
        except (OSError, ValueError):
            existing = None
    out = collect(Http(), key, existing, budget_s=args.budget, from_date=args.from_date)
    if not out["agsi"] and not out["flows"]:
        for e in out["errors"]:
            print("  -", e)
        sys.exit("Sem tározói, sem áramlási adat nem érkezett; a gas.json nem íródik felül.")
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    a = out["agsi"]
    print(f"Kész: {args.out} | tározó: {'igen, ' + str(len(a['dates'])) + ' nap, ' + str(len(a['series'])) + ' sorozat' if a else 'nincs'}"
          f" | LNG: {'igen, ' + str(len(out['lng']['fac'])) + ' terminál, ' + str(len(out['lng']['series'])) + ' sorozat' if out['lng'] else 'nincs'}"
          f" | határpont-áramlás: {'igen, ' + str(len(out['flows']['points'])) + ' pont' if out['flows'] else 'nincs'}"
          f" | hibák: {len(out['errors'])}")
    for e in out["errors"] + out["notes"]:
        print("  -", e)


if __name__ == "__main__":
    main()
