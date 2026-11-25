#!/usr/bin/env python3
"""REMIT bennfentes információk (UMM) a HUPX Inside Information Platformról. Kimenet: hupx.json.

Forrás: HUPX IIP, GET https://iip.hupx.hu/api/v1/umm (Authorization: Bearer <kulcs>).
A kulcs a HUPX_KEY környezeti változóból jön (GitHub Secret). Kulcs nélkül a program csendben kilép,
hiba esetén sem bukik el a workflow (a Mérnöki nézet kártyája ilyenkor egyszerűen nem jelenik meg).

Itt a villamosenergia-kiesések (ELECTRICITY, ACTIVE állapot) kellenek: a legutóbbi 7 nap óta és a következő
45 napban érvényes események. Az oldalon a forrás: HUPX IIP (REMIT).

Futtatás:  python hupx.py --out hupx.json
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

BASE = "https://iip.hupx.hu/api"
MAX_PAGES = 60
OPEN_END = "0001-01-01"


class Http:
    """get(url, params, headers) -> JSON; hibára kivétel status_code attribútummal."""

    def get(self, url, params=None, headers=None, timeout=60):
        import requests
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        if r.status_code >= 400:
            err = RuntimeError(f"HTTP {r.status_code}")
            err.status_code = r.status_code
            raise err
        return r.json()


def parse_dt(s):
    if not s or s.startswith(OPEN_END):
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ") if d else None


def cap_now(intervals, now):
    """Az aktuális (különben a következő, különben az utolsó) kapacitásintervallum: (kieső, elérhető)."""
    iv = []
    for c in intervals or []:
        a, b = parse_dt(c.get("intervalStart")), parse_dt(c.get("intervalStop"))
        if a:
            iv.append((a, b, c))
    iv.sort(key=lambda x: x[0])
    cur = next((c for a, b, c in iv if a <= now and (b is None or now < b)), None)
    if cur is None:
        cur = next((c for a, b, c in iv if a > now), None)
    if cur is None and iv:
        cur = iv[-1][2]
    if not cur:
        return None, None
    return cur.get("unavailableCapacity"), cur.get("availableCapacity")


def convert(it, now):
    """Egy UMM-verzió -> az oldal kiesés-formátuma. None, ha nem használható."""
    m = it.get("message") or {}
    ev, cap = m.get("event") or {}, m.get("capacity") or {}
    start, stop = parse_dt(ev.get("eventStart")), parse_dt(ev.get("eventStop"))
    if not start:
        return None
    unit = (cap.get("unitMeasure") or "MW").upper().replace("MAW", "MW")
    if unit != "MW":
        return None
    un, av = cap_now(cap.get("capacityIntervals"), now)
    nom = cap.get("installedCapacity")
    if av is None and un is not None and nom is not None:
        av = max(0.0, nom - un)
    asset = m.get("affectedAsset") or {}
    parts = m.get("marketParticipants") or []
    return {
        "thread": it.get("threadKey"), "title": m.get("title"),
        "name": asset.get("name") or m.get("title") or "?", "eic": asset.get("eic"),
        "participant": parts[0].get("name") if parts else None,
        "type": m.get("fuelType"), "event_type": ev.get("eventType"),
        "start": iso(start), "end": iso(stop), "open_end": stop is None,
        "planned": m.get("unavailabilityType") == "Planned",
        "nominal_mw": nom, "avail_mw": av, "unavail_mw": un,
        "reason": m.get("unavailabilityReason"), "reason_hu": m.get("unavailabilityReasonHun"),
        "published": it.get("publishedAt"), "first_published": it.get("firstPublishedAt"),
        "version": it.get("versionNo"),
    }


def fetch_page(http, url, params, headers, errors, sleep=time.sleep):
    for attempt in range(3):
        try:
            return http.get(url, params=params, headers=headers)
        except Exception as e:
            st = getattr(e, "status_code", None)
            if st in (400, 401, 403, 422):
                errors.append(f"HUPX IIP: {e} (kulcs vagy paraméter hiba, nem próbálom újra)")
                return None
            if attempt == 2:
                errors.append(f"HUPX IIP: {e}")
                return None
            sleep(3 * (attempt + 1))
    return None


def collect(http, key, now=None, sleep=time.sleep):
    now = now or datetime.now(timezone.utc)
    headers = {"Authorization": f"Bearer {key}"}
    filt = {"energyTypes": "ELECTRICITY", "status": "ACTIVE", "limit": 500,
            "eventFrom": (now - timedelta(days=7)).strftime("%Y-%m-%d"),
            "eventTo": (now + timedelta(days=45)).strftime("%Y-%m-%d")}
    errors, items, cursor, pages = [], [], None, 0
    while pages < MAX_PAGES:
        params = dict(filt)
        if cursor:
            params["cursor"] = cursor
        js = fetch_page(http, f"{BASE}/v1/umm", params, headers, errors, sleep)
        if js is None:
            break
        pages += 1
        items += js.get("items") or []
        cursor = js.get("nextCursor")
        if not cursor:
            break
    else:
        errors.append(f"HUPX IIP: {MAX_PAGES} oldal után megszakítva")
    seen, out = set(), []
    for it in items:
        k = it.get("threadKey")
        if k in seen:
            continue
        seen.add(k)
        o = convert(it, now)
        if o:
            out.append(o)
    out.sort(key=lambda o: (o["planned"], o["start"]))
    return {"generated_utc": iso(now), "source": "HUPX Inside Information Platform (REMIT)", "pages": pages,
            "count": len(out), "items": out, "errors": errors}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="hupx.json")
    args = ap.parse_args()
    key = os.environ.get("HUPX_KEY", "").strip()
    if not key:
        print("HUPX_KEY nincs megadva, a HUPX-gyűjtés kimarad.")
        return 0
    res = collect(Http(), key)
    for e in res["errors"]:
        print("HIBA:", e)
    if res["pages"] == 0:
        print("HUPX: nem sikerült adatot kérni, a hupx.json nem készül el.")
        return 0
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, separators=(",", ":"))
    print(f"HUPX: {res['count']} villamosenergia-kiesés, {res['pages']} oldal -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
