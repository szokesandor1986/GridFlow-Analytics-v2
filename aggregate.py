#!/usr/bin/env python3
"""A hist/ tár feldolgozása: származtatott kategóriák, napi/heti/havi/éves összesítők, katalógus, manifest.

Használat:
    python aggregate.py --root hist                       # minden zóna
    python aggregate.py --root hist --zones HU,AT         # csak ezek (a többi a manifestben változatlan marad)
    python aggregate.py --root hist --derive-years 2026   # a származtatott óránkénti fájlokat csak erre az évre számolja újra

Összesítési szabályok (a Módszertan oldal is ezt írja le):
  - teljesítmény (MW): a rendelkezésre álló órák átlaga, min., max.; az energia = átlag × az időszak tényleges órái (23/25 órás napok)
  - ár (€/MWh): időátlag (egyenlő súly), min., max., a negatív órák száma külön
  - CO2-intenzitás: termeléssel súlyozott (Σ g·F / Σ g), nem az óránkénti értékek átlaga
  - lefedettség (n / órák száma) a MIN_COV alatt: az összesítés null (nem becsült, nem nulla)
  - a helyi idő minden zónára Europe/Budapest
"""
import argparse
import math
import os
import sys

import numpy as np
import pandas as pd

import hist_store as hs
from hist_store import BUD, CATS, MIN_COV, ZONES, rnd, rnd1, rnd2

try:
    import collector as col
    CO2_FACTORS, CO2_SOURCE = col.CO2_FACTORS, col.CO2_SOURCE
except Exception:  # noqa: BLE001  (az összesítő a gyűjtő nélkül is fusson)
    CO2_FACTORS = {"nuclear": 12, "gas": 490, "coal": 820, "solar": 48, "wind": 11, "bio": 230, "hydro": 24, "other": 700}
    CO2_SOURCE = "IPCC AR5 WG3 Annex III, életciklus-mediánok (gCO2eq/kWh); egyéb: 700, becslés"


# ------------------------------------------------------------------ származtatott kategóriák
def derive_net_import(root, zone, year):
    df = hs.load_partition(root, zone, year, "flow_physical")
    if df is None:
        return False
    cols = [c for c in df.columns if df[c].notna().any()]
    if not cols:
        return False
    need = math.ceil(0.7 * len(cols))
    ok = df[cols].notna().sum(axis=1) >= need            # az óra érvényes, ha a határok legalább 70 %-ának van adata
    net = df[cols].sum(axis=1, min_count=1).where(ok)
    return hs.save_partition(root, zone, year, "net_import", net.to_frame("net"), replace=True)


def derive_residual(root, zone, year):
    load, gen = hs.load_partition(root, zone, year, "load"), hs.load_partition(root, zone, year, "generation")
    if load is None or gen is None or "solar" not in gen:
        return False
    r = load["load"] - gen["solar"]
    if "wind" in gen:
        r = r - gen["wind"]                                # hiányzó szél-óra: a maradék terhelés is hiányzik (nem nulla)
    return hs.save_partition(root, zone, year, "residual", r.to_frame("residual"), replace=True)


def co2_parts(gen):
    """Óránkénti számláló (Σ g·F) és nevező (Σ g) a termelési táblából."""
    cols = [c for c in gen.columns if c in CO2_FACTORS]
    g = gen[cols].clip(lower=0)
    num = (g * pd.Series({c: CO2_FACTORS[c] for c in cols})).sum(axis=1, min_count=1)
    den = g.sum(axis=1, min_count=1)
    return num.where(den > 0), den.where(den > 0)


def derive_co2(root, zone, year):
    gen = hs.load_partition(root, zone, year, "generation")
    if gen is None:
        return False
    num, den = co2_parts(gen)
    return hs.save_partition(root, zone, year, "co2", (num / den).to_frame("intensity"), replace=True)


def derive(root, zone, years=None):
    """A származtatott óránkénti partíciók (nettó import, maradék terhelés, CO2) újraszámolása az alapkategóriákból."""
    n = 0
    ys = set(years or [])
    for cat, fn in (("flow_physical", derive_net_import), ("load", derive_residual), ("generation", derive_co2)):
        if cat == "flow_physical" and zone not in hs.cat_zones("net_import"):
            continue
        for y in hs.partition_years(root, zone, cat):
            if not ys or y in ys:
                n += bool(fn(root, zone, y))
    return n


def daily_ramp(resid):
    """Napi mutatók a maradék terhelésből (helyi nap): déli minimum (9–16 h) és a legnagyobb esti (15–21 h) óránkénti emelkedés."""
    r = resid.dropna()
    if r.empty:
        return None
    loc = r.index.tz_convert(BUD)
    day = pd.Index(loc.strftime("%Y-%m-%d"))
    mid = r[(loc.hour >= 9) & (loc.hour <= 16)]
    midd = pd.Index(mid.index.tz_convert(BUD).strftime("%Y-%m-%d"))
    cnt = mid.groupby(midd).count()
    res_mid = mid.groupby(midd).min()[cnt >= 6]            # legalább 6 érvényes óra a 8-ból
    d = r.diff()
    ok = (r.index.to_series().diff() == pd.Timedelta(hours=1)).to_numpy()
    dl = d.index.tz_convert(BUD)
    eve = d[ok & (dl.hour >= 15) & (dl.hour <= 21)]
    eved = pd.Index(eve.index.tz_convert(BUD).strftime("%Y-%m-%d"))
    ecnt = eve.groupby(eved).count()
    ramp = eve.clip(lower=0).groupby(eved).max()[ecnt >= 4]  # legalább 4 érvényes óraváltás a 7-ből
    out = pd.DataFrame({"res_mid_min": res_mid, "ramp_eve": ramp})
    if out.empty:
        return None
    out.index = pd.DatetimeIndex([pd.Timestamp(x).tz_localize(BUD).tz_convert("UTC") for x in out.index])
    return out


# ------------------------------------------------------------------ időszakok
def keys_for(index_utc, tier):
    loc = index_utc.tz_convert(BUD)
    if tier == "d":
        return pd.Index(loc.strftime("%Y-%m-%d"))
    if tier == "w":
        iso = loc.isocalendar()
        return pd.Index([f"{int(y)}-W{int(w):02d}" for y, w in zip(iso["year"], iso["week"])])
    if tier == "m":
        return pd.Index(loc.strftime("%Y-%m"))
    return pd.Index(loc.strftime("%Y"))


def _start(key, tier):
    if tier == "d":
        return pd.Timestamp(key)
    if tier == "w":
        y, w = key.split("-W")
        return pd.Timestamp(pd.Timestamp.fromisocalendar(int(y), int(w), 1))
    if tier == "m":
        return pd.Timestamp(key + "-01")
    return pd.Timestamp(key + "-01-01")


def _end(s, tier):
    return {"d": lambda: s + pd.Timedelta(days=1), "w": lambda: s + pd.Timedelta(days=7),
            "m": lambda: s + pd.offsets.MonthBegin(1), "y": lambda: s + pd.DateOffset(years=1)}[tier]()


def span(key, tier, unit="h"):
    """Az időszak hossza: órában (a tényleges, DST-t figyelembe vevő óraszám) vagy napban."""
    s = _start(key, tier)
    e = _end(s, tier)
    if unit == "d":
        return (e - s).days
    return int(round((e.tz_localize(BUD) - s.tz_localize(BUD)).total_seconds() / 3600))


def all_keys(keys, tier):
    lo, hi = min(keys), max(keys)
    if tier == "d":
        return [t.strftime("%Y-%m-%d") for t in pd.date_range(lo, hi, freq="D")]
    if tier == "w":
        out, t, end = [], _start(lo, "w"), _start(hi, "w")
        while t <= end:
            iso = t.isocalendar()
            out.append(f"{iso[0]}-W{iso[1]:02d}")
            t += pd.Timedelta(days=7)
        return out
    if tier == "m":
        return [str(p) for p in pd.period_range(lo, hi, freq="M")]
    return [str(y) for y in range(int(lo), int(hi) + 1)]


def _pack(full, tier, unit, avg, mn, mx, n, neg=None, rf=rnd):
    spans = np.array([span(k, tier, unit) for k in full], dtype=float)
    ok = (n.to_numpy(dtype=float) / spans) >= MIN_COV
    def col_(s, f=rf):
        return [f(v) if o else None for v, o in zip(s.to_numpy(dtype=float), ok)]
    out = {"avg": col_(avg, rnd2 if rf is rnd2 else rnd1), "min": col_(mn), "max": col_(mx), "n": [int(v) for v in n.to_numpy()]}
    if neg is not None:
        out["neg"] = [int(v) if o else None for v, o in zip(neg.to_numpy(), ok)]
    return out, [int(s) for s in spans]


def rollup(df, tier, unit="h", price=False):
    """df: óránkénti (vagy napi, unit="d") DataFrame UTC indexszel -> {"keys", "h", "series"}."""
    keys = keys_for(df.index, tier)
    full = all_keys(list(keys), tier)
    g = df.groupby(keys)
    mean, mn, mx, cnt = g.mean(), g.min(), g.max(), g.count()
    rf = rnd2 if price else rnd
    series, hh = {}, None
    for c in df.columns:
        neg = (df[c] < 0).groupby(keys).sum().reindex(full).fillna(0) if price else None
        s, hh = _pack(full, tier, unit, mean[c].reindex(full), mn[c].reindex(full), mx[c].reindex(full),
                      cnt[c].reindex(full).fillna(0), neg, rf)
        series[c] = s
    return {"keys": full, "h": hh, "series": series}


def rollup_co2(gen, tier):
    num, den = co2_parts(gen)
    keys = keys_for(gen.index, tier)
    full = all_keys(list(keys), tier)
    inten = (num / den)
    gi = inten.groupby(keys)
    avg = (num.groupby(keys).sum(min_count=1) / den.groupby(keys).sum(min_count=1)).reindex(full)
    s, hh = _pack(full, tier, "h", avg, gi.min().reindex(full), gi.max().reindex(full), gi.count().reindex(full).fillna(0))
    return {"keys": full, "h": hh, "series": {"intensity": s}}


# ------------------------------------------------------------------ zóna feldolgozása
def _last_epoch(df):
    ix = df.dropna(how="all").index
    return int(ix[-1].timestamp()) if len(ix) else None


def coverage(df, year, now):
    """Egy év lefedettsége: a nem hiányzó cellák aránya az eddig eltelt órákra (sorozatonként átlagolva)."""
    s, e = hs.year_bounds(year)
    stop = min(e, now.ceil("h"))
    if stop <= s:
        return None
    part = df[(df.index >= s) & (df.index < stop)]
    if part.empty:
        return 0.0
    exp = (stop - s) / pd.Timedelta(hours=1)
    return round(float(part.notna().to_numpy().sum() / (exp * part.shape[1])), 3)


def aggregate_zone(root, zone, now, derive_years=None):
    """Egy zóna összes kategóriájának összesítése. Visszaadja a manifest zónarekordját."""
    derive(root, zone, derive_years)
    cats = {}
    for cat in CATS:
        if zone not in hs.cat_zones(cat):
            continue
        meta = CATS[cat]
        if cat == "ramp":
            res = hs.load_all(root, zone, "residual")
            if res is None:
                continue
            base = daily_ramp(res["residual"])
            if base is None:
                continue
            for t in hs.TIERS:
                r = rollup(base, t, unit="d")
                _write_tier(root, zone, cat, t, meta, r, _last_epoch(base))
            cats[cat] = {"years": hs.partition_years(root, zone, "residual"), "series": list(base.columns), "cov": {},
                         "first": int(base.index[0].timestamp()), "last": _last_epoch(base), "tiers": list(hs.TIERS)}
            continue
        df = hs.load_all(root, zone, cat)
        if df is None:
            continue
        years = hs.partition_years(root, zone, cat)
        gen = hs.load_all(root, zone, "generation") if cat == "co2" else None
        for t in hs.TIERS:
            r = rollup_co2(gen, t) if cat == "co2" else rollup(df, t, price=(cat == "price_da"))
            _write_tier(root, zone, cat, t, meta, r, _last_epoch(df))
        ix = df.dropna(how="all").index
        cats[cat] = {"years": years, "series": list(df.columns), "cov": {str(y): coverage(df, y, now) for y in years},
                     "first": int(ix[0].timestamp()) if len(ix) else None, "last": _last_epoch(df), "tiers": list(hs.TIERS)}
        qy = [int(y) for y in (os.listdir(os.path.join(root, "q", zone)) if os.path.isdir(os.path.join(root, "q", zone)) else [])
              if y.isdigit() and os.path.exists(hs.part_path(root, zone, int(y), cat, 900))]
        if qy:
            cats[cat]["q_years"] = sorted(qy)
    return {"name": ZONES[zone]["name"], "country": ZONES[zone]["country"], "note": ZONES[zone].get("note"), "cats": cats}


def _write_tier(root, zone, cat, tier, meta, r, last):
    obj = {"schema": hs.SCHEMA, "zone": zone, "cat": cat, "tier": tier, "unit": meta["unit"], "agg": meta["agg"], "quality": meta["kind"],
           "per": "d" if cat == "ramp" else "h", "last": last, "keys": r["keys"], "h": r["h"], "series": r["series"]}
    hs.write_if_changed(hs.tier_path(root, tier, zone, cat), obj)


# ------------------------------------------------------------------ katalógus és manifest
def build_catalog(root):
    cats = {}
    for k, m in CATS.items():
        cats[k] = {"label": m["label"], "unit": m["unit"], "agg": m["agg"], "source": m["src"], "quality": m["kind"], "series": m["series"],
                   "zones": hs.cat_zones(k)}
    obj = {"schema": hs.SCHEMA, "zones": ZONES, "cats": cats, "tiers": {"d": "napi", "w": "heti (ISO-hét)", "m": "havi", "y": "éves"},
           "co2": {"factors": CO2_FACTORS, "source": CO2_SOURCE}, "local_tz": BUD, "prelim_days": hs.PRELIM_DAYS, "min_cov": MIN_COV,
           "quality_labels": {"published": "Közölt (90 nap után végleges, előtte előzetes)", "calculated": "Számított", "estimated": "Becsült tényezőkkel számított", "missing": "Hiányzó"}}
    return hs.write_if_changed(os.path.join(root, "catalog.json"), obj)


def build_manifest(root, zones_info, now):
    old = hs.read_json(os.path.join(root, "manifest.json")) or {}
    zones = dict(old.get("zones", {}))
    zones.update(zones_info)
    files = {}
    for dp, _, fs in os.walk(root):
        for f in sorted(fs):
            if f.endswith(".json") and f not in ("manifest.json",):
                p = os.path.join(dp, f)
                files[os.path.relpath(p, root).replace(os.sep, "/")] = hs.file_hash(p)
    obj = {"schema": hs.SCHEMA, "generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "prelim_days": hs.PRELIM_DAYS, "min_cov": MIN_COV,
           "zones": dict(sorted(zones.items())), "files": dict(sorted(files.items()))}
    # a generated_utc minden futásnál változik; ha a tartalom egyébként azonos, a manifest fájlt nem írjuk újra
    prev = hs.read_json(os.path.join(root, "manifest.json"))
    if prev and {k: v for k, v in prev.items() if k != "generated_utc"} == {k: v for k, v in obj.items() if k != "generated_utc"}:
        return False
    return hs.write_if_changed(os.path.join(root, "manifest.json"), obj)


def run(root, zones=None, now=None, derive_years=None):
    now = now or pd.Timestamp.now(tz="UTC")
    zs = [z for z in (zones or ZONES) if z in ZONES]
    present = [z for z in zs if os.path.isdir(os.path.join(root, "h", z))]
    info = {z: aggregate_zone(root, z, now, derive_years) for z in present}
    build_catalog(root)
    build_manifest(root, info, now)
    return info


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default="hist")
    p.add_argument("--zones", help="vesszővel elválasztott zónakódok (alapértelmezés: mind)")
    p.add_argument("--derive-years", help="a származtatott óránkénti fájlokat csak ezekre az évekre számolja újra")
    p.add_argument("--now", help="ISO időpont (tesztekhez)")
    a = p.parse_args()
    if not os.path.isdir(a.root):
        sys.exit(f"Nincs ilyen könyvtár: {a.root}")
    info = run(a.root, a.zones.split(",") if a.zones else None, pd.Timestamp(a.now, tz="UTC") if a.now else None,
               [int(x) for x in a.derive_years.split(",")] if a.derive_years else None)
    for z, i in info.items():
        print(f"  {z}: " + ", ".join(f"{c} ({len(v['years'])} év)" for c, v in i["cats"].items()))
    print(f"Kész: {len(info)} zóna feldolgozva")


if __name__ == "__main__":
    main()
