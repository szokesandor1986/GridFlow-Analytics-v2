#!/usr/bin/env python3
"""JAO Publication Tool (Core flow-based): első, felderítő változat. Kimenet: jao_probe.json.

A JAO API-leírása a válasz mezőit nem sorolja fel, ezért ez a program még nem készít oldalt: egy órányi
finalComputation, netPos és maxExchanges mintát kér le (Take=5), és elmenti a mezőneveket, a sorok számát és
néhány mintasort. Ebből építjük meg a kiesés/terhelés (CNEC) fület a valódi szerkezetre.

Betartott szabályok (JAO útmutató): egyszerre egy kérés, gzip, a rejected/messages mezők ellenőrzése, 429-nél várakozás,
rövid időszak (1 óra), kevés kérés. Kulcs nincs.

Futtatás:  python jao.py --out jao_probe.json
"""
import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone

BASE = "https://publicationtool.jao.eu/core/api"
DATASETS = ("finalComputation", "netPos", "maxExchanges")


class Http:
    def get(self, url, params=None, headers=None, timeout=120):
        import requests
        r = requests.get(url, params=params, headers=dict({"Accept-Encoding": "gzip"}, **(headers or {})), timeout=timeout)
        if r.status_code >= 400:
            err = RuntimeError(f"HTTP {r.status_code}")
            err.status_code = r.status_code
            try:
                err.retry_after = int(r.headers.get("Retry-After", ""))
            except ValueError:
                err.retry_after = None
            raise err
        return r.json()


def fmt(d):
    return d.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def get(http, url, params, errors, sleep=time.sleep):
    for attempt in range(3):
        try:
            return http.get(url, params=params)
        except Exception as e:
            st = getattr(e, "status_code", None)
            if st in (400, 404):
                errors.append(f"{url.rsplit('/', 1)[-1]}: {e} (nem próbálom újra)")
                return None
            if attempt == 2:
                errors.append(f"{url.rsplit('/', 1)[-1]}: {e}")
                return None
            ra = getattr(e, "retry_after", None)
            sleep(min(ra if ra else 5 * (attempt + 1) * (3 if st == 429 else 1), 90))
    return None


def probe(http, now=None, sleep=time.sleep):
    now = now or datetime.now(timezone.utc)
    start = (now - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=1)
    out, errors = {}, []
    for ds in DATASETS:
        js = get(http, f"{BASE}/data/{ds}", {"FromUtc": fmt(start), "ToUtc": fmt(end), "Take": 5}, errors, sleep)
        sleep(1)
        if js is None:
            continue
        rows = js.get("data") if isinstance(js, dict) else js
        info = {"top_keys": sorted(js.keys()) if isinstance(js, dict) else None, "rejected": js.get("rejected") if isinstance(js, dict) else None,
                "messages": js.get("messages") if isinstance(js, dict) else None, "totalRows": js.get("totalRows") if isinstance(js, dict) else None,
                "lastModifiedOn": js.get("lastModifiedOn") if isinstance(js, dict) else None}
        rows = rows if isinstance(rows, list) else []
        info["fields"] = sorted({k for r in rows if isinstance(r, dict) for k in r})
        info["sample"] = rows[:3]
        out[ds] = info
        if info["rejected"]:
            errors.append(f"{ds}: a JAO elutasította a kérést: {info['messages']}")
    mon = get(http, f"{BASE}/system/monitoring", {"FromUtc": fmt(start - timedelta(days=1)), "ToUtc": fmt(end)}, errors, sleep)
    return {"generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "from": fmt(start), "to": fmt(end), "datasets": out,
            "monitoring": (mon[:12] if isinstance(mon, list) else mon), "errors": errors}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="jao_probe.json")
    args = ap.parse_args()
    res = probe(Http())
    for e in res["errors"]:
        print("JAO HIBA:", e)
    for ds, i in res["datasets"].items():
        print(f"JAO {ds}: mezők = {i['fields']} | sorok = {i['totalRows']} | rejected = {i['rejected']}")
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, separators=(",", ":"))
    print("JAO próba kész ->", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
