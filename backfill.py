#!/usr/bin/env python3
"""Hosszú távú adattár (hist/) visszatöltése és napi frissítése az ENTSO-E Transparency Platformról.

A letöltés zónánként és évenként óránkénti (UTC rácsos) partíciókat ír; a feldolgozást (származtatott kategóriák,
napi/heti/havi/éves összesítők, manifest) az aggregate.py végzi.

Használat:
    export ENTSOE_TOKEN=...
    python backfill.py --root hist --zones HU --years 2026,2025,2024          # visszatöltés
    python backfill.py --root hist --update-days 14                           # napi frissítés: az utolsó 14 nap minden zónára
    python backfill.py --root hist --plan --from-year 2019                    # mely zóna-évek hiányoznak (JSON a workflow-nak)
    python backfill.py --root hist --zones HU --years 2026,2025 --q-years 2   # + HU negyedórás partíciók a legutóbbi 2 évre
    python aggregate.py --root hist                                           # feldolgozás

A token csak környezeti változóból olvasható; semmilyen fájlba vagy kimenetbe nem kerül.
"""
import argparse
import json
import os
import sys
import time

import pandas as pd

import collector as col
import hist_store as hs
from collector import Batch
from hist_store import BORDERS, BUD, ZONES

HOME = col.HOME
REQUIRED = {"HU": ("generation", "load", "price_da", "flow_physical")}      # a hiányzó évek tervezéséhez
DEFAULT_REQUIRED = ("generation", "load", "price_da")
QCATS = ("load", "generation", "price_da")                                    # negyedórás partíció: ezekből készül


def frame_of(obj, name):
    if obj is None:
        return None
    if isinstance(obj, pd.DataFrame):
        obj = obj.iloc[:, 0]
    return obj.rename(name)


def gen_groups(df, quarter=False):
    """ENTSO-E termelési tábla -> típuscsoportonként egy oszlop (UTC rács); a szivattyúzási (fogyasztási) oszlopokat kihagyja.
    Egy csoportban a típusok összege; csak akkor hiányzó, ha minden típusa hiányzik."""
    by, native = {}, None
    for c in df.columns:
        name, kind = (c[0], c[-1]) if isinstance(c, tuple) else (c, "Actual Aggregated")
        if "consumption" in str(kind).lower():
            continue
        if quarter:
            s, nat = hs.to_quarter_utc(df[c])
            s = s.iloc[:, 0]
            native = nat if native is None or (nat is not None and nat < native) else native
        else:
            s = hs.to_hourly_utc(df[c]).iloc[:, 0]
        g = col.TYPE_TO_GROUP.get(name, "other")
        by.setdefault(g, []).append(s)
    out = {g: pd.concat(v, axis=1).sum(axis=1, min_count=1) for g, v in by.items()}
    return (pd.DataFrame(out) if out else None), native


def net_frame(a, b):
    """Két irány különbsége (a − b), csak ott, ahol mindkettő megvan."""
    if a is None or b is None:
        return None
    return (a.iloc[:, 0] - b.iloc[:, 0]).dropna()


def store(root, zone, cat, df, step=3600, native15_from=None):
    """A DataFrame-t naptári (budapesti) évek szerint szétosztja a partíciókba. Visszaadja a módosult fájlok számát."""
    if df is None or df.empty:
        return 0
    n = 0
    yrs = sorted({int(y) for y in df.index.tz_convert(BUD).year})
    for y in yrs:
        s, e = hs.year_bounds(y)
        part = df[(df.index >= s) & (df.index < e)]
        n += bool(hs.save_partition(root, zone, y, cat, part, step, native15_from))
    return n


def collect(client, zones, ranges, now, root, workers=8, budget_s=2600, q_years=()):
    """ranges: [(címke, start, end)] – tz-aware (Europe/Budapest) időpontok. Zónánként és tartományonként tölt le és ír.
    Visszaadja a jelentést: [{zone, range, ok, nodata, err, skip, files, problems}]."""
    B = Batch(budget_s, workers=workers)
    plan = []
    for z in zones:
        for tag, s, e in ranges:
            q = z == HOME and any(y in q_years for y in range(s.year, (e - pd.Timedelta(seconds=1)).year + 1))
            keys = {}

            def add(name, fn, z=z, tag=tag, keys=keys):
                k = f"{name} {z} {tag}"
                keys[name] = k
                B.add(k, fn)
            add("load", lambda z=z, s=s, e=e: client.query_load(z, start=s, end=e))
            add("load_forecast", lambda z=z, s=s, e=e: client.query_load_forecast(z, start=s, end=e))
            add("generation", lambda z=z, s=s, e=e: client.query_generation(z, start=s, end=e, nett=True))
            add("price_da", lambda z=z, s=s, e=e: client.query_day_ahead_prices(z, start=s, end=e))
            if z == HOME:
                for b in BORDERS:
                    add(f"flow_physical:{b}:in", lambda b=b, s=s, e=e: client.query_crossborder_flows(b, HOME, start=s, end=e))
                    add(f"flow_physical:{b}:out", lambda b=b, s=s, e=e: client.query_crossborder_flows(HOME, b, start=s, end=e))
                    add(f"flow_scheduled:{b}:in", lambda b=b, s=s, e=e: client.query_scheduled_exchanges(b, HOME, start=s, end=e, dayahead=False))
                    add(f"flow_scheduled:{b}:out", lambda b=b, s=s, e=e: client.query_scheduled_exchanges(HOME, b, start=s, end=e, dayahead=False))
            plan.append((z, tag, keys, q))

    report = []
    for z, tag, keys, q in plan:
        got = {n: B.get(k) for n, k in keys.items()}
        files, problems = 0, []

        def one(cat, raw, name):
            nonlocal files
            if raw is None:
                return
            h = hs.to_hourly_utc(raw)
            files += store(root, z, cat, h.iloc[:, 0].to_frame(name))
            if q and cat in QCATS and cat != "generation":
                qq, nat = hs.to_quarter_utc(raw)
                files += store(root, z, cat, qq.iloc[:, 0].to_frame(name), 900, nat)
        one("load", got["load"], "load")
        one("load_forecast", got["load_forecast"], "load_forecast")
        one("price_da", got["price_da"], "price")
        if got["generation"] is not None:
            g, _ = gen_groups(got["generation"])
            files += store(root, z, "generation", g)
            if q:
                gq, nat = gen_groups(got["generation"], quarter=True)
                files += store(root, z, "generation", gq, 900, nat)
        if z == HOME:
            for cat in ("flow_physical", "flow_scheduled"):
                cols = {}
                for b in BORDERS:
                    a, o = got.get(f"{cat}:{b}:in"), got.get(f"{cat}:{b}:out")
                    h = net_frame(hs.to_hourly_utc(a) if a is not None else None, hs.to_hourly_utc(o) if o is not None else None)
                    if h is not None and len(h):
                        cols[b] = h
                if cols:
                    files += store(root, z, cat, pd.DataFrame(cols).sort_index())
        st = {n: B.status(k) for n, k in keys.items()}
        cnt = {s: sum(1 for v in st.values() if v == s) for s in ("ok", "nodata", "err", "skip")}
        report.append({"zone": z, "range": tag, "files": files, **cnt})
        print(f"  {z} {tag}: ok {cnt['ok']}, nincs adat {cnt['nodata']}, hiba {cnt['err']}, kihagyva {cnt['skip']} | módosult fájl: {files}", flush=True)
    B.close()
    for n in B.notes() + B.errors[:20]:
        print("  -", n)
    return report, B


def year_range(year, now):
    now_bud = now.tz_convert(BUD)
    s = pd.Timestamp(f"{year}-01-01", tz=BUD)
    e = min(pd.Timestamp(f"{year + 1}-01-01", tz=BUD), now_bud.ceil("h"))     # azonos időzóna: az entsoe-py különben ValueError-t dob
    return (str(year), s, e) if e > s else None


def update_range(days, now):
    now_bud = now.tz_convert(BUD)
    s = (now_bud - pd.Timedelta(days=days)).floor("D")
    s = pd.Timestamp(s.strftime("%Y-%m-%d"), tz=BUD)
    return (f"utolsó {days} nap", s, now_bud.ceil("h"))


def plan(root, zones, from_year, now, min_cov=0.9):
    """Mely (zóna, évek) munkák kellenek: ahol hiányzik a partíció vagy a lefedettség alacsony; a folyó év (és január–február
    között az előző év, az utólagos javítások miatt) mindig."""
    man = hs.read_json(os.path.join(root, "manifest.json")) or {}
    now_bud = now.tz_convert(BUD)
    this = now_bud.year
    jobs = []
    for z in zones:
        need = []
        for y in range(this, from_year - 1, -1):
            if y == this or (y == this - 1 and now_bud.month <= 2):
                need.append(y)
                continue
            bad = False
            for cat in REQUIRED.get(z, DEFAULT_REQUIRED):
                if not os.path.exists(hs.part_path(root, z, y, cat)):
                    bad = True
                    break
                cov = ((man.get("zones", {}).get(z, {}).get("cats", {}).get(cat, {}) or {}).get("cov", {}) or {}).get(str(y))
                if cov is not None and cov < min_cov:
                    bad = True
                    break
            if bad:
                need.append(y)
        jobs.append({"zone": z, "years": ",".join(str(y) for y in need)})
    return jobs


def merge_parts(root, parts_dir):
    """A párhuzamos futások részeredményeit (parts_dir/h/..., parts_dir/q/...) a tárba fésüli: az új, nem hiányzó érték felülír,
    a hiány nem töröl. Visszaadja a módosult fájlok számát."""
    n = 0
    for tier, step in (("h", 3600), ("q", 900)):
        base = os.path.join(parts_dir, tier)
        if not os.path.isdir(base):
            continue
        for zone in sorted(os.listdir(base)):
            for year in sorted(os.listdir(os.path.join(base, zone))):
                d = os.path.join(base, zone, year)
                for fn in sorted(os.listdir(d)):
                    if not (year.isdigit() and fn.endswith(".json")):
                        continue
                    cat = fn[:-5]
                    if cat not in hs.CATS:
                        continue
                    df = hs.load_partition(parts_dir, zone, int(year), cat, step)
                    if df is not None:
                        n += bool(hs.save_partition(root, zone, int(year), cat, df, step, df.attrs.get("native15_from")
                                                    and pd.Timestamp(df.attrs["native15_from"], unit="s", tz="UTC")))
    return n


def make_client(token):
    from entsoe import EntsoePandasClient
    return col.GroupClient(EntsoePandasClient(api_key=token, retry_count=2, retry_delay=5, timeout=90))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default="hist")
    p.add_argument("--zones", help="vesszővel elválasztott zónakódok (alapértelmezés: mind a 10)")
    p.add_argument("--years", help="ezek az évek, vesszővel elválasztva (a legfrissebb az első)")
    p.add_argument("--from-year", type=int, default=2019)
    p.add_argument("--update-days", type=int, help="napi frissítés: az utolsó N nap (az évek helyett)")
    p.add_argument("--q-years", type=int, default=0, help="a magyar negyedórás partíciók ennyi legutóbbi évre (0: nincs)")
    p.add_argument("--merge-parts", metavar="KÖNYVTÁR", help="részeredmények összefésülése a --root tárba, nem tölt le semmit")
    p.add_argument("--plan", action="store_true", help="kiírja a hiányzó zóna-éveket (JSON), nem tölt le semmit")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--budget", type=int, default=2600, help="időkeret másodpercben")
    a = p.parse_args()
    zones = [z for z in (a.zones.split(",") if a.zones else ZONES) if z in ZONES]
    now = pd.Timestamp.now(tz="UTC")
    if a.plan:
        print(json.dumps(plan(a.root, zones, a.from_year, now)))
        return
    if a.merge_parts:
        os.makedirs(a.root, exist_ok=True)
        print(f"Összefésülve: módosult fájl: {merge_parts(a.root, a.merge_parts)}")
        return
    token = os.environ.get("ENTSOE_TOKEN", "").strip()
    if not token:
        sys.exit("Hiányzik az ENTSOE_TOKEN környezeti változó.")
    if a.update_days:
        ranges = [update_range(a.update_days, now)]
        qd = os.path.join(a.root, "q", HOME)          # negyedórás partíciót csak ott frissítünk, ahol már van
        qy = {int(y) for y in os.listdir(qd) if y.isdigit()} if os.path.isdir(qd) else set()
    else:
        if not a.years:
            sys.exit("Add meg a --years vagy az --update-days kapcsolót.")
        ys = [int(x) for x in a.years.replace(" ", "").split(",") if x]
        ranges = [r for r in (year_range(y, now) for y in ys) if r]
        qy = set(range(now.tz_convert(BUD).year - a.q_years + 1, now.tz_convert(BUD).year + 1)) if a.q_years else set()
    os.makedirs(a.root, exist_ok=True)
    t0 = time.monotonic()
    report, B = collect(make_client(token), zones, ranges, now, a.root, a.workers, a.budget, qy)
    ok = sum(r["ok"] for r in report)
    print(f"Kész: {len(report)} zóna-időszak, sikeres lekérdezés: {ok}, módosult fájl: {sum(r['files'] for r in report)} | {time.monotonic() - t0:.0f} s")
    if ok == 0:
        sys.exit("Egyetlen lekérdezés sem hozott adatot.")


if __name__ == "__main__":
    main()
