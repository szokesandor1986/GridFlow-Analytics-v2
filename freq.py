#!/usr/bin/env python3
"""Hálózati frekvencia a Mérnöki nézet (muszaki.html) frekvencia-szekcióihoz. Kimenet: frequency.json.

Forrás: Energy-Charts API (Fraunhofer ISE), GET /v2/frequency: a kontinentális európai szinkronterület
(RG Continental Europe) hálózati frekvenciája, 1 másodperces felbontásban. Kulcs nem kell.
Licenc: CC BY 4.0, forrásmegjelölés: energy-charts.info (az oldalon szerepel).

A nyers másodperces adatot nem tároljuk. Naponta (UTC-nap) összesítünk:
  átlag, minimum és maximum (időponttal), szórás, az 50 Hz körüli ±50 mHz és ±100 mHz sávon kívül töltött
  idő aránya, a legnagyobb frekvenciaváltozási sebesség (10 s-os átlagok különbségéből), és hisztogram (10 mHz-es
  sávok, -200..+200 mHz, a szélén túlcsorduló sávval). Az utolsó 24 órára percenkénti min/átlag/max sorozat készül.

Korlát: 2 kérés/perc (burst 4), a 429-es válasz Retry-After fejlécét tiszteletben tartjuk. Ezért egy futás
legfeljebb néhány napot kér le (a mai és a tegnapi nap mindig, a hiányzó régebbi napok a legújabbtól visszafelé),
és a hiányzó napok futásról futásra pótlódnak.

Futtatás:  python freq.py --out frequency.json
"""
import argparse
import json
import math
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import numpy as np

BASE = "https://api.energy-charts.info"
ENDPOINTS = ("/v2/frequency", "/frequency")     # a v2 az elsődleges, a v1 tartalék
F0 = 50.0
EDGES = [round(F0 + k * 0.01, 2) for k in range(-20, 21)]       # 49,80 .. 50,20 Hz
HIST_LABELS = ["<-200"] + [f"{k * 10}..{(k + 1) * 10}" for k in range(-20, 20)] + [">+200"]   # mHz


class Http:
    """get(url, params, headers) -> kiértékelt JSON; hibára kivétel status_code és retry_after attribútummal."""

    def get(self, url, params=None, headers=None, timeout=120):
        import requests
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        if r.status_code >= 400:
            err = RuntimeError(f"HTTP {r.status_code}")
            err.status_code = r.status_code
            try:
                err.retry_after = int(r.headers.get("Retry-After", ""))
            except ValueError:
                err.retry_after = None
            raise err
        return r.json()


class Throttle:
    """Legalább `gap` másodperc két kérés között (2 kérés/perc -> 31 s)."""

    def __init__(self, gap=31.0):
        self.gap, self.last = gap, 0.0

    def wait(self):
        d = self.last + self.gap - time.monotonic()
        if d > 0:
            time.sleep(d)
        self.last = time.monotonic()


def parse_series(js):
    """Válasz -> (epoch másodpercek, Hz) numpy tömbök. Érti a v2 borítékot és a v1 oszlopos alakot.
    Hiányzó és hihetetlen (45..55 Hz-en kívüli) értékek kimaradnak."""
    t, f = [], []
    if isinstance(js.get("data"), list) and js["data"] and isinstance(js["data"][0], dict) and "timestamp" in js["data"][0]:
        ids = [s.get("id") for s in js.get("series") or []]
        pick = next((i for i in ids if i and "freq" in str(i).lower()), ids[0] if ids else None)
        for rec in js["data"]:
            vals = rec.get("values") or {}
            v = vals.get(pick) if pick in vals else (next(iter(vals.values()), None) if vals else None)
            if v is None:
                continue
            t.append(datetime.fromisoformat(str(rec["timestamp"]).replace("Z", "+00:00")).timestamp())
            f.append(float(v))
    elif "unix_seconds" in js:
        ts = js["unix_seconds"]
        arr = next((v for k, v in js.items() if k != "unix_seconds" and isinstance(v, list) and len(v) == len(ts)
                    and (not v or not isinstance(v[0], (dict, list)))), None)
        if arr is None:
            return np.array([]), np.array([])
        for a, b in zip(ts, arr):
            if b is not None:
                t.append(float(a))
                f.append(float(b))
    t, f = np.asarray(t, dtype=float), np.asarray(f, dtype=float)
    ok = np.isfinite(f) & (f > 45) & (f < 55)
    t, f = t[ok], f[ok]
    o = np.argsort(t, kind="stable")
    return t[o], f[o]


def iso_utc(sec):
    return datetime.fromtimestamp(float(sec), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def day_stats(t, f):
    n = len(f)
    if n == 0:
        return None
    dev = f - F0
    blocks = (t // 10).astype(np.int64)
    ub, inv = np.unique(blocks, return_inverse=True)
    bm = np.bincount(inv, weights=f) / np.bincount(inv)
    dfdt = 0.0
    if len(ub) > 1:
        adj = np.diff(ub) == 1
        d = np.abs(np.diff(bm))[adj] * 1000 / 10.0          # mHz/s
        dfdt = float(d.max()) if len(d) else 0.0
    hist = np.histogram(f, bins=[0.0] + EDGES + [100.0])[0]
    imin, imax = int(np.argmin(f)), int(np.argmax(f))
    return {
        "n": int(n), "cov": round(n / 86400.0, 3),
        "mean": round(float(f.mean()), 4), "std": round(float(f.std()) * 1000, 2),          # std mHz-ben
        "min": round(float(f[imin]), 3), "min_ts": iso_utc(t[imin]),
        "max": round(float(f[imax]), 3), "max_ts": iso_utc(t[imax]),
        "out50": round(float((np.abs(dev) > 0.05).mean()) * 100, 3),
        "out100": round(float((np.abs(dev) > 0.10).mean()) * 100, 3),
        "dfdt": round(dfdt, 2), "hist": [int(x) for x in hist],
    }


def minute_series(t, f, hours=24):
    if len(f) == 0:
        return None
    end = int(t.max() // 60) * 60
    t0 = end - (hours * 60 - 1) * 60
    m = (t >= t0)
    tt, ff = t[m], f[m]
    idx = ((tt - t0) // 60).astype(np.int64)
    n = hours * 60
    mn, mx, sm, ct = np.full(n, np.inf), np.full(n, -np.inf), np.zeros(n), np.zeros(n)
    np.minimum.at(mn, idx, ff)
    np.maximum.at(mx, idx, ff)
    np.add.at(sm, idx, ff)
    np.add.at(ct, idx, 1)
    ok = ct > 0
    out = lambda a, dec: [round(float(v), dec) if o else None for v, o in zip(a, ok)]    # noqa: E731
    return {"t0": iso_utc(t0), "step": 60, "min": out(mn, 3), "mean": out(np.where(ok, sm / np.maximum(ct, 1), 0), 4), "max": out(mx, 3)}


def fetch_day(http, day, throttle, errors):
    """Egy UTC-nap adata: (t, f) vagy None. 429-nél a Retry-After szerint vár."""
    params = {"start": f"{day}T00:00Z", "end": f"{day}T23:59:59Z"}
    last = None
    for ep in ENDPOINTS:
        for attempt in range(3):
            throttle.wait()
            try:
                t, f = parse_series(http.get(BASE + ep, params=params))
                if len(f):
                    return t, f
                last = "üres válasz"
                break
            except Exception as exc:  # noqa: BLE001
                st = getattr(exc, "status_code", None)
                last = f"{exc.__class__.__name__} {exc}"
                if st == 429:
                    ra = getattr(exc, "retry_after", None)
                    time.sleep(min(ra if ra is not None else 60, 150))
                    continue
                if st in (400, 404, 422):
                    break                         # ez a végpont/paraméter nem jó, próbáljuk a következőt
                time.sleep(3)
    errors.append(f"frekvencia {day}: {last}")
    return None


def collect(http, existing=None, today=None, throttle=None, max_fetch=6, keep_days=400):
    today = today or datetime.now(timezone.utc).date()
    throttle = throttle or Throttle()
    errors, notes = [], []
    daily = dict((existing or {}).get("daily") or {})
    minute = (existing or {}).get("minute")
    todo = [today.isoformat(), (today - timedelta(days=1)).isoformat()]
    for k in range(2, keep_days):
        d = (today - timedelta(days=k)).isoformat()
        if d not in daily and len(todo) < max_fetch:
            todo.append(d)
    recent = []
    got = 0
    for d in todo:
        r = fetch_day(http, d, throttle, errors)
        if r is None:
            continue
        got += 1
        st = day_stats(*r)
        if st:
            daily[d] = st
        if d in todo[:2]:
            recent.append(r)
    if recent:
        t = np.concatenate([x[0] for x in recent])
        f = np.concatenate([x[1] for x in recent])
        o = np.argsort(t, kind="stable")
        ms = minute_series(t[o], f[o])
        if ms:
            minute = ms
    missing = sum(1 for k in range(keep_days) if (today - timedelta(days=k)).isoformat() not in daily)
    if missing:
        notes.append(f"{missing} nap még hiányzik a visszamenőleges sorozatból, a következő futások pótolják")
    keep = sorted(daily)[-keep_days:]
    return {
        "schema": 1, "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Energy-Charts (Fraunhofer ISE), RG Continental Europe", "license": "CC BY 4.0, energy-charts.info",
        "demo": False, "daily": {d: daily[d] for d in keep}, "minute": minute, "hist_labels": HIST_LABELS,
        "errors": errors, "notes": notes,
    }, got


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="frequency.json")
    ap.add_argument("--max-fetch", type=int, default=6, help="legfeljebb ennyi nap kérése egy futásban")
    args = ap.parse_args()
    existing = None
    if os.path.exists(args.out):
        try:
            with open(args.out, encoding="utf-8") as fh:
                existing = json.load(fh)
        except (OSError, ValueError):
            existing = None
    out, got = collect(Http(), existing, max_fetch=args.max_fetch)
    if not out["daily"]:
        for e in out["errors"]:
            print("  -", e)
        sys.exit("Nem érkezett frekvenciaadat; a frequency.json nem íródik felül.")
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"Kész: {args.out} | napok: {len(out['daily'])} | most lekérve: {got} | hibák: {len(out['errors'])}")
    for e in out["errors"] + out["notes"]:
        print("  -", e)


if __name__ == "__main__":
    main()
