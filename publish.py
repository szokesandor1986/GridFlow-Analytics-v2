#!/usr/bin/env python3
"""GridFlow Analytics – publikációk (Elemzések) építése a havi történeti adatból.

Mit csinál
  - A history.json havi összesítéséből (lezárt hónapok, lezárt évek) kiszámolja a tíz téma mutatóit,
  - minden témához egy statikus HTML-oldalt ír (elemzesek/<téma>.html) rögzített, tízrészes szerkezetben:
        Kérdés · Rövid összefoglaló · Adatok · Módszer · Elemzés · Ábrák · Értelmezés · Következtetések · Korlátok · Források
  - és egy listát (elemzesek/index.json) a Kezdőlap és az Elemzések oldal számára.

Alapelvek
  - A szövegben szereplő minden szám az adatból számolt; kézzel beírt érték nincs. A mondatokat a számított értékek
    választják ki (nőtt / csökkent / változatlan), az okokról a szöveg nem állít többet, mint amit az adat megenged.
  - Ami az adatból nem számolható (hiányzó hónapok, hiányzó adatsor), azt a „Korlátok" rész kimondja; becslés nem pótolja.
  - Csak lezárt hónapokat és lezárt éveket használ; a folyamatban lévő hónap nem kerül bele az évi összesítésekbe.
  - Determinista: ugyanabból az adatból bájtra azonos fájlok jönnek (nincs építési időbélyeg), így a Pages-telepítés
    csak a ténylegesen változott oldalakat cseréli.
  - Nincs külső kérés, nincs titok; az ábrák a böngészőben a közös diagramkönyvtárral rajzolódnak, JavaScript nélkül
    ugyanaz az adat táblázatban látszik.

Használat:  python publish.py --history history.json --out elemzesek [--demo] [--hist hist]
"""
import argparse
import html
import json
import math
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BUD = ZoneInfo("Europe/Budapest")
SCHEMA = 1

MONTHS_HU = ["január", "február", "március", "április", "május", "június", "július", "augusztus", "szeptember", "október", "november", "december"]
IN_MONTH = ["januárban", "februárban", "márciusban", "áprilisban", "májusban", "júniusban", "júliusban", "augusztusban", "szeptemberben", "októberben", "novemberben", "decemberben"]
MON_SHORT = ["jan", "feb", "már", "ápr", "máj", "jún", "júl", "aug", "szep", "okt", "nov", "dec"]
GROUPS = ["nuclear", "gas", "coal", "solar", "wind", "bio", "hydro", "other"]
GLABEL = {"nuclear": "Atomerőmű", "gas": "Földgáz", "coal": "Szén", "solar": "Napenergia", "wind": "Szél", "bio": "Biomassza és hulladék", "hydro": "Víz", "other": "Egyéb"}
ZORDER = ["HU", "AT", "SK", "RO", "HR", "SI", "CZ", "DE_LU"]
ZNAME = {"HU": "Magyarország", "AT": "Ausztria", "SK": "Szlovákia", "RO": "Románia", "HR": "Horvátország", "SI": "Szlovénia", "CZ": "Csehország",
         "DE_LU": "Németország–Luxemburg", "RS": "Szerbia", "UA": "Ukrajna"}
BORDERS = ["AT", "SK", "RO", "RS", "HR", "SI"]
BLABEL = {"AT": "Ausztria", "SK": "Szlovákia", "RO": "Románia", "RS": "Szerbia", "HR": "Horvátország", "SI": "Szlovénia"}

SRC = {
    "load": "ENTSO-E Transparency Platform, 6.1.A – tény fogyasztás (Actual Total Load)",
    "gen": "ENTSO-E Transparency Platform, 16.1.B&C – tény termelés típusonként (Actual Generation per Production Type)",
    "price": "ENTSO-E Transparency Platform, 12.1.D – day-ahead árak (a magyar zónaár megegyezik a HUPX day-ahead piaci árával)",
    "flow": "ENTSO-E Transparency Platform, 12.1.G – fizikai határkeresztező áramlás (Cross-Border Physical Flow)",
    "inst": "ENTSO-E Transparency Platform, 14.1.A – beépített kapacitás termelési típusonként (Installed Capacity per Production Type)",
    "co2": "IPCC AR5 WG3 Annex III – életciklus-alapú kibocsátási tényezők (medián értékek)",
}


# ---------------------------------------------------------------------------------------------------- formázás
def nf(v, d=1):
    """Magyar számformázás: tizedesvessző, ezres elválasztó szóköz (nem törhető), valódi mínuszjel."""
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "–"
    s = f"{abs(v):,.{d}f}".replace(",", " ").replace(".", ",")
    if float(s.replace(" ", "").replace(",", ".")) == 0:
        return s
    return ("−" if v < 0 else "") + s


def pc(v, d=1):
    return nf(v, d) + " %"


def ml(key):
    return key[:4] + "." + key[5:]


def month_long(key):
    return f"{key[:4]}. {MONTHS_HU[int(key[5:7]) - 1]}"


def in_month(key):
    return f"{key[:4]}. {IN_MONTH[int(key[5:7]) - 1]}"


def hours_in_month(key):
    y, m = int(key[:4]), int(key[5:7])
    a = datetime(y, m, 1, tzinfo=BUD)
    b = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=BUD)
    return round((b.astimezone(timezone.utc) - a.astimezone(timezone.utc)).total_seconds() / 3600)


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def pearson(xs, ys):
    pts = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pts) < 8:
        return None
    mx, my = mean([p[0] for p in pts]), mean([p[1] for p in pts])
    sx = math.sqrt(sum((p[0] - mx) ** 2 for p in pts))
    sy = math.sqrt(sum((p[1] - my) ** 2 for p in pts))
    if sx < 1e-9 or sy < 1e-9:
        return None
    return sum((p[0] - mx) * (p[1] - my) for p in pts) / (sx * sy)


def corr_text(r, what, ref=""):
    if r is None:
        return f"{what} együttmozgása nem értékelhető{ref} (nincs elég adatpont, vagy valamelyik mutató nem változik)."
    a = abs(r)
    erő = "gyenge" if a < 0.3 else "mérsékelt" if a < 0.6 else "erős"
    irány = "pozitív" if r > 0 else "negatív"
    return f"{what} között a havi értékek alapján {erő}, {irány} együttmozgás látszik{ref} (Pearson-féle korrelációs együttható: {nf(r, 2)}); ez leíró összefüggés, nem okozati."


def change_word(new, old, tol, up="nőtt", down="csökkent", flat="gyakorlatilag nem változott"):
    if new is None or old is None:
        return None
    d = new - old
    return flat if abs(d) <= tol else (up if d > 0 else down)


def esc(s):
    return html.escape(str(s), quote=True)


# ---------------------------------------------------------------------------------------------------- adatréteg
class Hist:
    """A havi történeti adat (history.json) lezárt hónapjai és évei."""

    def __init__(self, raw):
        self.raw = raw
        self.months = raw.get("months") or {}
        self.keys = sorted(k for k, v in self.months.items() if not v.get("partial"))
        self.all_keys = sorted(self.months)
        self.demo = bool(raw.get("demo"))
        self.generated = raw.get("generated_utc")
        ks = set(self.keys)
        self.years = [y for y in sorted({k[:4] for k in self.keys}) if all(f"{y}-{m:02d}" in ks for m in range(1, 13))]
        self.annual = raw.get("annual") or {}
        self.co2 = ((raw.get("co2") or {}).get("factors")) or {}
        self.last12 = self.keys[-12:] if len(self.keys) >= 12 else []
        self.prev12 = self.keys[-24:-12] if len(self.keys) >= 24 else []

    def rec(self, key):
        return self.months.get(key) or {}

    def gen(self, key, g):
        v = (self.rec(key).get("gen") or {}).get(g)
        return v

    def gen_total(self, key, groups=None):
        gd = self.rec(key).get("gen") or {}
        gs = groups or GROUPS
        vals = [gd.get(g) for g in gs]
        if not gd or any(v is None for v in vals if gs is groups):
            return None
        present = [v for v in vals if v is not None]
        return sum(present) if present else None

    def total_complete(self, key):
        """A termelés összege, ha mind a nyolc csoport adata megvan (különben a részarány félrevezető lenne)."""
        gd = self.rec(key).get("gen") or {}
        if any(gd.get(g) is None for g in GROUPS):
            return None
        return sum(gd[g] for g in GROUPS)

    def share(self, key, g):
        t = self.total_complete(key)
        v = self.gen(key, g)
        return None if t is None or t <= 0 or v is None else 100.0 * v / t

    def f(self, key, *path):
        o = self.months.get(key) or {}
        for p in path:
            if not isinstance(o, dict):
                return None
            o = o.get(p)
        return o

    def import_share(self, key):
        i, l = self.f(key, "imp_gwh"), self.f(key, "load_gwh")
        return None if i is None or not l else 100.0 * i / l

    def mw(self, key, gwh):
        return None if gwh is None else gwh * 1000.0 / hours_in_month(key)

    def year_keys(self, y):
        return [f"{y}-{m:02d}" for m in range(1, 13)]

    def year_sum(self, y, fn):
        vals = [fn(k) for k in self.year_keys(y)]
        return None if any(v is None for v in vals) else sum(vals)

    def window_sum(self, keys, fn):
        vals = [fn(k) for k in keys]
        return None if not keys or any(v is None for v in vals) else sum(vals)

    def prelim_note(self, last_key=None):
        """A legutóbbi lezárt hónapok előzetesek lehetnek (az ENTSO-E utólag módosíthat) – 90 napos szabály, mint a tárban."""
        last_key = last_key or (self.keys[-1] if self.keys else None)
        if not last_key or not self.generated:
            return None
        y, m = int(last_key[:4]), int(last_key[5:7])
        end = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=BUD)
        gen = datetime.fromisoformat(self.generated.replace("Z", "+00:00"))
        return (gen - end).days < 90


# ---------------------------------------------------------------------------------------------------- ábraleírók
def jan_ticks(keys):
    return [{"i": i, "label": k[:4]} for i, k in enumerate(keys) if k.endswith("-01")]


def fig_line(fid, title, labels, series, unit, dec=1, caption="", ticks=None, zero=False):
    return {"id": fid, "kind": "line", "title": title, "labels": labels, "series": series, "unit": unit, "dec": dec, "caption": caption, "ticks": ticks, "zero": zero}


def fig_bars(fid, title, labels, series, unit, dec=1, caption="", stacked=False):
    return {"id": fid, "kind": "bars", "title": title, "labels": labels, "series": series, "unit": unit, "dec": dec, "caption": caption, "stacked": stacked}


def fig_scatter(fid, title, points, xlabel, ylabel, xunit, yunit, caption=""):
    return {"id": fid, "kind": "scatter", "title": title, "points": points, "xLabel": xlabel, "yLabel": ylabel, "xUnit": xunit, "yUnit": yunit, "caption": caption}


def S(id_, label, values):
    return {"id": id_, "label": label, "values": [None if v is None else round(v, 4) for v in values]}


def year_overlay(h, fn, years=None, last_n=8):
    """Évenkénti vonalak a naptári hónapok fölött: [(év, [12 érték vagy None])], legfeljebb 8 év."""
    ys = sorted({k[:4] for k in h.keys})[-last_n:] if years is None else years
    out = []
    for y in ys:
        vals = []
        for m in range(1, 13):
            k = f"{y}-{m:02d}"
            vals.append(fn(k) if k in set(h.keys) else None)
        if any(v is not None for v in vals):
            out.append((y, vals))
    return out


# ---------------------------------------------------------------------------------------------------- közös szövegrészek
def data_desc(h, what, keys, unit_note=""):
    if not keys:
        return f"{what}: nincs elegendő lezárt hónap."
    return (f"{what}. Az elemzés {month_long(keys[0])} és {month_long(keys[-1])} között {len(keys)} lezárt hónapot használ"
            f"{unit_note}. A folyamatban lévő hónap és a hiányos hónapok nem szerepelnek az összesítésekben.")


GENERIC_LIMITS = [
    "Az adatok az ENTSO-E átláthatósági platformról származnak; az adatszolgáltatók utólag módosíthatnak, ezért a legutóbbi hónapok értéke előzetes.",
    "A havi összesítés elfedi a napon belüli és a napi különbségeket; az óránkénti és napi nézet a Historikus adatok oldalon érhető el.",
]


def prelim_limit(h, last_key=None):
    if h.prelim_note(last_key):
        return "A legutóbbi felhasznált hónap kevesebb mint 90 napja zárult le, ezért értéke előzetes, és még változhat."
    return None


def new_pub(n, slug, topic, title, question):
    return {"n": n, "slug": slug, "topic": topic, "title": title, "question": question, "summary": [], "data": [], "method": [], "analysis": [],
            "figures": [], "interpretation": [], "conclusions": [], "limits": list(GENERIC_LIMITS), "sources": [], "status": "teljes", "data_through": None, "quality": "végleges"}


def finish(h, pub, keys):
    pub["data_through"] = keys[-1] if keys else None
    pr = prelim_limit(h, keys[-1] if keys else None)
    if pr:
        pub["limits"].append(pr)
        pub["quality"] = "előzetes"
    return pub


def insufficient(h, pub, why):
    pub["status"] = "adatra vár"
    pub["quality"] = "hiányzik"
    pub["summary"] = [f"Ehhez a témához az adattárban jelenleg nincs elegendő adat: {why}"]
    pub["data"] = [f"Szükséges adat: {why}"]
    pub["method"] = ["A mutatók számítása a rendelkezésre álló lezárt hónapokból történik; elegendő adat híján számítás nem készült."]
    pub["analysis"] = ["Számított eredmény nincs."]
    pub["interpretation"] = ["Értelmezés nélkül, mert nincs számított eredmény."]
    pub["conclusions"] = ["A téma elemzése az adatok megérkezése után automatikusan elkészül."]
    pub["limits"].append(f"Hiányzó adat: {why}")
    return pub


# ---------------------------------------------------------------------------------------------------- 1. importfüggőség
def t_import(h):
    p = new_pub(1, "importfuggoseg", "Importfüggőség", "Mekkora részét fedezi import a magyar villamosenergia-fogyasztásnak?",
                "Mennyi a nettó import a hazai villamosenergia-fogyasztáshoz képest, és hogyan alakult ez az elmúlt években?")
    keys = [k for k in h.keys if h.import_share(k) is not None]
    if len(keys) < 13:
        return insufficient(h, p, "legalább 13 lezárt hónap nettó import (ENTSO-E 12.1.G) és fogyasztás (6.1.A) adata")
    sh = [h.import_share(k) for k in keys]
    l12 = keys[-12:]
    s12 = h.window_sum(l12, lambda k: h.f(k, "imp_gwh")) / h.window_sum(l12, lambda k: h.f(k, "load_gwh")) * 100 if h.window_sum(l12, lambda k: h.f(k, "load_gwh")) else None
    p12 = keys[-24:-12] if len(keys) >= 24 else []
    s_prev = (h.window_sum(p12, lambda k: h.f(k, "imp_gwh")) / h.window_sum(p12, lambda k: h.f(k, "load_gwh")) * 100) if p12 and h.window_sum(p12, lambda k: h.f(k, "load_gwh")) else None
    ann = {}
    for y in h.years:
        i, l = h.year_sum(y, lambda k: h.f(k, "imp_gwh")), h.year_sum(y, lambda k: h.f(k, "load_gwh"))
        if i is not None and l:
            ann[y] = 100.0 * i / l
    mx = max(l12, key=lambda k: h.import_share(k)); mn = min(l12, key=lambda k: h.import_share(k))
    cw = change_word(s12, s_prev, 0.5, up="magasabb", down="alacsonyabb", flat="gyakorlatilag azonos")
    brd = {b: h.window_sum(l12, lambda k, b=b: (h.f(k, "border") or {}).get(b)) for b in BORDERS}
    brd = {b: v for b, v in brd.items() if v is not None}
    load12 = h.window_sum(l12, lambda k: h.f(k, "load_gwh"))
    p["summary"] = [
        f"Az elmúlt 12 lezárt hónapban ({month_long(l12[0])} – {month_long(l12[-1])}) a nettó import a fogyasztás {pc(s12)}-át tette ki.",
        (f"Az azt megelőző 12 hónap értéke {pc(s_prev)} volt, vagyis a mutató {cw}." if cw and s_prev is not None else "Az előző 12 hónapra nincs elég adat az összevetéshez."),
        f"A legmagasabb havi érték {in_month(mx)} volt ({pc(h.import_share(mx))}), a legalacsonyabb {in_month(mn)} ({pc(h.import_share(mn))}).",
    ]
    p["data"] = [data_desc(h, "A nettó import a hat nyugati és déli szomszéd (AT, SK, RO, RS, HR, SI) fizikai határkeresztező áramlásainak összege; a fogyasztás a tény teljes terhelés", keys),
                 "Mértékegység: GWh havonta; a mutató százalékban értendő. Pozitív érték import Magyarországra, negatív érték export."]
    p["method"] = ["Importfüggőségi mutató = a hónap nettó importja (GWh) osztva a hónap fogyasztásával (GWh), százalékban. A nettó import minden határon az import és az export különbsége, a határokra összegezve; a havi érték csak akkor számít, ha a határok adatai megvannak.",
                   "A 12 hónapos érték a 12 hónap importjának és fogyasztásának összegéből számolt arány (nem a havi arányok átlaga), így a nagyobb fogyasztású hónapok nagyobb súlyt kapnak."]
    p["analysis"] = [f"A havi mutató a vizsgált időszakban {pc(min(sh))} és {pc(max(sh))} között mozgott (1. ábra)."]
    if ann:
        ys = sorted(ann)
        p["analysis"].append("Lezárt évekre: " + "; ".join(f"{y}: {pc(ann[y])}" for y in ys) + " (2. ábra).")
        hi = max(ys, key=lambda y: ann[y]); lo = min(ys, key=lambda y: ann[y])
        p["analysis"].append(f"Az évi mutató a legmagasabb a {hi}. évben ({pc(ann[hi])}), a legalacsonyabb a {lo}. évben ({pc(ann[lo])}).")
    if brd and load12:
        tops = sorted(brd.items(), key=lambda kv: -kv[1])
        p["analysis"].append("Az elmúlt 12 hónap nettó importja határonként (a fogyasztás százalékában, 3. ábra): " + "; ".join(f"{BLABEL[b]}: {pc(100 * v / load12)}" for b, v in tops) + ".")
    p["figures"] = [
        fig_line("f1", "Nettó import a fogyasztás százalékában, havonta", [ml(k) for k in keys], [S("share", "Nettó import / fogyasztás", sh)], "%", 1, "Pozitív: import Magyarországra.", jan_ticks(keys), zero=True),
    ]
    if ann:
        ys = sorted(ann)
        p["figures"].append(fig_bars("f2", "Nettó import a fogyasztás százalékában, lezárt évek", ys, [S("ann", "Nettó import / fogyasztás", [ann[y] for y in ys])], "%", 1))
    l24 = keys[-24:]
    bs = [b for b in BORDERS if any(((h.f(k, "border") or {}).get(b)) is not None for k in l24)]
    if bs:
        p["figures"].append(fig_bars("f3", "Nettó import határonként, az elmúlt 24 hónap (GWh/hó)", [ml(k) for k in l24],
                                     [S(b, BLABEL[b], [(h.f(k, "border") or {}).get(b) for k in l24]) for b in bs], "GWh", 0, "Pozitív: import, negatív: export.", stacked=True))
    p["interpretation"] = ["A nettó import a határkeresztező fizikai áramlások egyenlege: tranzitáramlást is tartalmazhat, ezért nem azonos azzal, amennyi villamos energiát a hazai fogyasztók ténylegesen külföldi termelésből kapnak.",
                           "Az arány változásának okait (hazai termelés, árkülönbségek, időjárás) ez az elemzés nem választja szét; az összefüggések a további témákban (napenergia, árak) külön szerepelnek."]
    p["conclusions"] = [f"Az elmúlt 12 lezárt hónapban a nettó import a fogyasztás {pc(s12)}-a volt." + (f" Ez az előző 12 hónaphoz képest {cw}." if cw and s_prev is not None else ""),
                        f"A havi érték az elmúlt 12 hónapban {pc(min(h.import_share(k) for k in l12))} és {pc(max(h.import_share(k) for k in l12))} között mozgott, ezért egy-egy hónapból trend nem olvasható le; érdemes az éves vagy a 12 hónapos értéket nézni."]
    p["limits"] += ["Az RS (Szerbia) és az UA (Ukrajna) határ adata nem minden időszakban áll rendelkezésre; a hiányzó határ miatt hiányos havi összeget a rendszer nem használ fel.",
                    "A nettó import fizikai áramlásból számolt; az ütemezett (kereskedelmi) kereskedelem eltérhet tőle."]
    p["sources"] = [SRC["flow"], SRC["load"]]
    return finish(h, p, keys)


# ---------------------------------------------------------------------------------------------------- 2. napenergia részaránya
def t_solar_share(h):
    p = new_pub(2, "napenergia-reszarany", "Napenergia részaránya", "Mekkora részét adja a napenergia a hazai villamosenergia-termelésnek?",
                "Hogyan változott a napenergia részaránya a jelentett hazai termelésben, és mennyire használják ki a jelentett napelem-kapacitást?")
    keys = [k for k in h.keys if h.share(k, "solar") is not None]
    if len(keys) < 13:
        return insufficient(h, p, "legalább 13 lezárt hónap termelési adata mind a nyolc termelési csoportra (ENTSO-E 16.1.B&C)")
    sh = [h.share(k, "solar") for k in keys]
    l12 = keys[-12:]
    solar12 = h.window_sum(l12, lambda k: h.gen(k, "solar")); tot12 = h.window_sum(l12, lambda k: h.total_complete(k))
    s12 = 100 * solar12 / tot12 if solar12 is not None and tot12 else None
    p12 = keys[-24:-12] if len(keys) >= 24 else []
    sp = h.window_sum(p12, lambda k: h.gen(k, "solar")); tp = h.window_sum(p12, lambda k: h.total_complete(k))
    s_prev = 100 * sp / tp if sp is not None and tp else None
    ann = {}
    for y in h.years:
        a, b = h.year_sum(y, lambda k: h.gen(k, "solar")), h.year_sum(y, lambda k: h.total_complete(k))
        if a is not None and b:
            ann[y] = (100.0 * a / b, a)
    mx = max(l12, key=lambda k: h.share(k, "solar")); mn = min(l12, key=lambda k: h.share(k, "solar"))
    inst = {y: ((h.annual.get(y) or {}).get("inst") or {}).get("solar") for y in h.years}
    cf = {y: 100.0 * ann[y][1] * 1000 / (inst[y] * 8760.0) for y in ann if inst.get(y)}
    cw = change_word(s12, s_prev, 0.3, up="nőtt", down="csökkent")
    p["summary"] = [f"Az elmúlt 12 lezárt hónapban a napenergia a jelentett termelés {pc(s12)}-át adta.",
                    (f"Az azt megelőző 12 hónapban ez {pc(s_prev)} volt, vagyis a részarány {cw}." if cw and s_prev is not None else "Az előző 12 hónapra nincs elég adat az összevetéshez."),
                    f"A havi részarány csúcsa {in_month(mx)} volt ({pc(h.share(mx, 'solar'))}), mélypontja {in_month(mn)} ({pc(h.share(mn, 'solar'))})."]
    p["data"] = [data_desc(h, "A termelés típusonkénti havi energiája az ENTSO-E tény termelési adatából", keys, "; a részarány csak akkor számít, ha mind a nyolc termelési csoport adata megvan"),
                 "Mértékegység: GWh havonta; a részarány százalék. A beépített kapacitás (MW) az ENTSO-E évi közlése."]
    p["method"] = ["Részarány = a napenergia havi termelése (GWh) osztva az összes jelentett termeléssel (GWh), százalékban. Az évi és a 12 hónapos érték az energiák összegéből számolt arány.",
                   "Kihasználtság = az évi napenergia-termelés (GWh) osztva a beépített napelem-kapacitás (MW) és az év óraszáma (8 760 óra) szorzatával; a kapacitást az ENTSO-E évi adata adja."]
    p["analysis"] = [f"A havi részarány a vizsgált időszakban {pc(min(sh))} és {pc(max(sh))} között mozgott (1. ábra)."]
    if ann:
        ys = sorted(ann)
        p["analysis"].append("Az évi részarány a lezárt években: " + "; ".join(f"{y}: {pc(ann[y][0])}" for y in ys) + " (2. ábra).")
    if cf:
        ys = sorted(cf)
        p["analysis"].append("A jelentett termelés és a jelentett kapacitás hányadosa: " + "; ".join(f"{y}: {pc(cf[y])}" for y in ys) + " (3. ábra).")
    p["figures"] = [fig_line("f1", "A napenergia részaránya a jelentett termelésben, havonta", [ml(k) for k in keys], [S("solar", "Napenergia részaránya", sh)], "%", 1, "", jan_ticks(keys), zero=True)]
    if ann:
        ys = sorted(ann)
        p["figures"].append(fig_bars("f2", "A napenergia részaránya, lezárt évek", ys, [S("ann", "Napenergia részaránya", [ann[y][0] for y in ys])], "%", 1))
    if cf:
        ys = sorted(cf)
        p["figures"].append(fig_bars("f3", "Jelentett napenergia-termelés a jelentett kapacitás arányában, lezárt évek", ys, [S("cf", "Kihasználtság", [cf[y] for y in ys])], "%", 1, "Éves termelés / (kapacitás × 8 760 óra)."))
    ia, ib = inst.get(ys[0]) if ann else None, inst.get(ys[-1]) if ann else None
    both_up = bool(ann) and len(ys) >= 2 and ann[ys[-1]][0] > ann[ys[0]][0] and ia and ib and ib > ia
    p["interpretation"] = [("A részarány növekedése a jelentett kapacitás növekedésével együtt jár" + f" (a {ys[0]}. évi {nf(ia, 0)} MW-ról a {ys[-1]}. évi {nf(ib, 0)} MW-ra)" + ", de az ENTSO-E adatai nem feltétlenül fedik le a háztartási méretű napelemek teljes termelését; ezért a számított részarány a jelentett termelésre vonatkozik, nem a tényleges összes napenergia-termelésre."
                            if both_up else "A részarány és a jelentett kapacitás változása a 2–3. ábrán követhető. Az ENTSO-E adatai nem feltétlenül fedik le a háztartási méretű napelemek teljes termelését; ezért a számított részarány a jelentett termelésre vonatkozik, nem a tényleges összes napenergia-termelésre."),
                           "A kihasználtsági mutató csak akkor ad valós képet, ha a jelentett termelés és a jelentett kapacitás ugyanarra a körre vonatkozik; eltérő lefedettség esetén a hányados torz lehet."]
    sm_ = [h.share(k, "solar") for k in l12 if int(k[5:7]) in (6, 7, 8)]; wn_ = [h.share(k, "solar") for k in l12 if int(k[5:7]) in (12, 1, 2)]
    seas = (f"Az elmúlt 12 hónapban a nyári (június–augusztus) havi részarányok átlaga {pc(mean(sm_))}, a téli (december–február) átlaga {pc(mean(wn_))} volt." if len(sm_) == 3 and len(wn_) == 3 else None)
    p["conclusions"] = [f"A napenergia részaránya az elmúlt 12 lezárt hónapban {pc(s12)} volt." + (f" Az előző 12 hónaphoz képest {cw}." if cw and s_prev is not None else "")] + ([seas] if seas else [])
    p["limits"] += ["Az ENTSO-E által jelentett napenergia-termelés nem feltétlenül tartalmazza a kis, hálózati mérés nélküli háztartási rendszereket.",
                    "A beépített kapacitás évi adat; a kapacitás év közbeni bővülése a kihasználtsági mutatót torzíthatja."]
    p["sources"] = [SRC["gen"], SRC["inst"]]
    return finish(h, p, keys)


# ---------------------------------------------------------------------------------------------------- 3. napenergia és esti rámpa
def t_ramp(h):
    p = new_pub(3, "napenergia-es-esti-rampa", "Napenergia és esti rámpa", "Hogyan hat a napenergia a maradék terhelésre és az esti felfutásra?",
                "Mennyire süllyed a déli maradék terhelés, mennyire meredek az esti felfutás, és mekkora az esti és déli árak közötti különbség?")
    keys = [k for k in h.keys if h.f(k, "ramp_p99") is not None and h.f(k, "res_min_mid") is not None]
    if len(keys) < 13:
        return insufficient(h, p, "legalább 13 lezárt hónap óránkénti terhelési, nap- és szélenergia-termelési adata (ENTSO-E 6.1.A, 16.1.B&C)")
    ov = year_overlay(h, lambda k: h.f(k, "ramp_p99"))
    summer = lambda y, fld: mean([h.f(f"{y}-{m:02d}", fld) for m in (5, 6, 7, 8)])
    ys = [y for y in sorted({k[:4] for k in keys}) if all(f"{y}-{m:02d}" in set(keys) for m in (5, 6, 7, 8))]
    sr = {y: summer(y, "ramp_p99") for y in ys}
    sm = {y: summer(y, "res_min_mid") for y in ys}
    spread = {k: (h.f(k, "price", "eve") - h.f(k, "price", "mid")) if h.f(k, "price", "eve") is not None and h.f(k, "price", "mid") is not None else None for k in keys}
    sp_keys = [k for k in keys if spread[k] is not None]
    p["summary"] = []
    if len(ys) >= 2:
        a, b = ys[0], ys[-1]
        p["summary"].append(f"A nyári hónapok (május–augusztus) átlagos esti rámpája (a 99. percentilis) a {a}. évi {nf(sr[a], 0)} MW/h-ról a {b}. évi {nf(sr[b], 0)} MW/h-ra {'nőtt' if sr[b] > sr[a] else 'csökkent'}.")
        p["summary"].append(f"A nyári déli maradék terhelés minimuma átlagosan {nf(sm[a], 0)} MW-ról {nf(sm[b], 0)} MW-ra {'nőtt' if sm[b] > sm[a] else 'csökkent'} ugyanezen évek között.")
    else:
        p["summary"].append(f"A havi esti rámpa a vizsgált időszakban {nf(min(h.f(k, 'ramp_p99') for k in keys), 0)} és {nf(max(h.f(k, 'ramp_p99') for k in keys), 0)} MW/h között mozgott.")
    if sp_keys:
        l = sp_keys[-12:]
        p["summary"].append(f"Az esti (18–21 h) és a déli (10–15 h) day-ahead átlagár különbsége az elmúlt {len(l)} hónapban átlagosan {nf(mean([spread[k] for k in l]), 1)} €/MWh volt.")
    p["data"] = [data_desc(h, "A maradék terhelés a tény fogyasztás mínusz a nap- és szélenergia-termelés (óránkénti); a day-ahead ár a magyar zónaár", keys),
                 "Mértékegység: MW (maradék terhelés), MW/h (rámpa), €/MWh (ár)."]
    p["method"] = ["Maradék terhelés = fogyasztás − napenergia − szélenergia, óránként. Déli minimum = a maradék terhelés havi legkisebb értéke 9 és 16 óra között (helyi idő).",
                   "Esti rámpa = a maradék terhelés két szomszédos óra közötti emelkedésének (csak pozitív változások, 15–21 óra között) havi 99. percentilise, MW/h-ban.",
                   "Ársáv = az esti (18–21 h) day-ahead átlagár mínusz a déli (10–15 h) átlagár, havonta."]
    p["analysis"] = []
    if ys:
        p["analysis"].append("A nyári (május–augusztus) évi átlagok: " + "; ".join(f"{y}: rámpa {nf(sr[y], 0)} MW/h, déli minimum {nf(sm[y], 0)} MW" for y in ys) + " (1–2. ábra).")
    if sp_keys:
        mxk = max(sp_keys, key=lambda k: spread[k])
        p["analysis"].append(f"Az esti és déli ár közötti különbség legnagyobb havi értéke {in_month(mxk)} volt ({nf(spread[mxk], 1)} €/MWh) (3. ábra).")
    p["figures"] = [
        fig_line("f1", "Esti rámpa (99. percentilis), évenként a naptári hónapok fölött", MON_SHORT, [S("y" + y, y, v) for y, v in ov], "MW/h", 0),
        fig_line("f2", "Déli maradék terhelés minimuma, évenként a naptári hónapok fölött", MON_SHORT, [S("y" + y, y, v) for y, v in year_overlay(h, lambda k: h.f(k, "res_min_mid"))], "MW", 0),
    ]
    if sp_keys:
        p["figures"].append(fig_line("f3", "Esti és déli day-ahead átlagár különbsége, havonta", [ml(k) for k in sp_keys], [S("spread", "Esti − déli átlagár", [spread[k] for k in sp_keys])], "€/MWh", 1, "", jan_ticks(sp_keys)))
    pattern = len(ys) >= 2 and sr[ys[-1]] > sr[ys[0]] and sm[ys[-1]] < sm[ys[0]]
    p["interpretation"] = [("A számított mutatók a napenergia terjedésének ismert mintáját követik: a napelemek délben csökkentik a maradék terhelést, estére kiesve viszont a többi erőműnek, a tárolóknak és az importnak gyorsabban kell pótolnia a hiányt."
                            if pattern else "A számított mutatók a nyári déli maradék terhelés és az esti felfutás alakulását írják le; a napenergia terjedésének ismert mintája (alacsonyabb déli minimum, meredekebb esti rámpa) ebben az adatsorban nem mindkét mutatón látszik egyértelműen."),
                           "Azt, hogy a rendszer az esti felfutást milyen tartalékból és milyen költséggel fedezte, ez az elemzés nem vizsgálja."]
    concl = []
    if len(ys) >= 2:
        concl.append(f"A nyári esti rámpa a {ys[0]}. évi {nf(sr[ys[0]], 0)} MW/h-ról a {ys[-1]}. évi {nf(sr[ys[-1]], 0)} MW/h-ra, a nyári déli minimum {nf(sm[ys[0]], 0)} MW-ról {nf(sm[ys[-1]], 0)} MW-ra változott.")
    if sp_keys:
        concl.append(f"Az esti és a déli átlagár különbsége az elmúlt {len(sp_keys[-12:])} hónapban átlagosan {nf(mean([spread[k] for k in sp_keys[-12:]]), 1)} €/MWh volt; havi alakulása a 3. ábrán követhető.")
    p["conclusions"] = concl or ["A havi esti rámpa és déli minimum a fenti ábrákon követhető."]
    p["limits"] += ["A szélenergia-termelés hiányos hónapjaiban a maradék terhelés nem számolható, ezek a hónapok kimaradnak.",
                    "A 99. percentilis egy kiugró értékekre érzékeny mutató; kevés órát tartalmazó hónapban bizonytalanabb."]
    p["sources"] = [SRC["load"], SRC["gen"], SRC["price"]]
    return finish(h, p, keys)


# ---------------------------------------------------------------------------------------------------- 4. negatív árak
def t_negative(h):
    p = new_pub(4, "negativ-arak", "Negatív HUPX-árak", "Hány órában negatív a magyar day-ahead villamosenergia-ár?",
                "Hány órán át volt negatív a day-ahead zónaár, mikor jelentkezik, és hogyan függ a napenergia részarányától?")
    keys = [k for k in h.keys if h.f(k, "price", "neg_h") is not None and h.f(k, "price", "n")]
    if len(keys) < 13:
        return insufficient(h, p, "legalább 13 lezárt hónap magyar day-ahead ára (ENTSO-E 12.1.D)")
    neg = [h.f(k, "price", "neg_h") for k in keys]
    l12 = keys[-12:]
    n12 = sum(h.f(k, "price", "neg_h") for k in l12); hrs12 = sum(h.f(k, "price", "n") for k in l12)
    p12 = keys[-24:-12] if len(keys) >= 24 else []
    nprev = sum(h.f(k, "price", "neg_h") for k in p12) if p12 else None
    ann = {}
    for y in h.years:
        a = h.year_sum(y, lambda k: h.f(k, "price", "neg_h"))
        if a is not None:
            ann[y] = a
    mx = max(keys, key=lambda k: h.f(k, "price", "neg_h"))
    mn_price = [h.f(k, "price", "min") for k in l12 if h.f(k, "price", "min") is not None]
    solar = [h.share(k, "solar") for k in keys]
    r = pearson(solar, neg)
    cw = change_word(n12, nprev, 5, up="több", down="kevesebb", flat="közel azonos") if nprev is not None else None
    p["summary"] = [f"Az elmúlt 12 lezárt hónapban {nf(n12, 0)} órában volt negatív a magyar day-ahead ár ({pc(100 * n12 / hrs12)} az órákból).",
                    (f"Az előző 12 hónapban {nf(nprev, 0)} ilyen óra volt, vagyis {cw} negatív árú óra jelentkezett." if cw else "Az előző 12 hónapra nincs elég adat az összevetéshez."),
                    f"A legtöbb negatív árú óra {in_month(mx)} jelentkezett ({nf(h.f(mx, 'price', 'neg_h'), 0)} óra)."]
    p["data"] = [data_desc(h, "A magyar day-ahead zónaár órás értékei (ENTSO-E 12.1.D, ami megegyezik a HUPX day-ahead piaci árával) és a napenergia részaránya", keys),
                 "Mértékegység: óra (negatív árú órák száma), €/MWh (ár), % (részarány)."]
    p["method"] = ["Negatív árú óra = olyan óra, amelynek day-ahead zónaára 0 €/MWh alatt van. A havi darabszámot az órás árak megszámlálásából kapjuk; az évi érték csak 12 teljes hónap esetén számít.",
                   "A negatív órák és a napenergia részaránya közötti összefüggést a havi értékpárokból számolt Pearson-féle korrelációs együttható írja le (leíró mutató)."]
    p["analysis"] = [f"Havonta legfeljebb {nf(max(neg), 0)} negatív árú óra fordult elő (1. ábra)."]
    if ann:
        ys = sorted(ann)
        p["analysis"].append("Lezárt évekre: " + "; ".join(f"{y}: {nf(ann[y], 0)} óra" for y in ys) + " (2. ábra).")
    if mn_price:
        p["analysis"].append(f"Az elmúlt 12 hónap legkisebb órás ára {nf(min(mn_price), 1)} €/MWh volt.")
    p["analysis"].append(corr_text(r, "A napenergia részaránya és a negatív árú órák száma", " (3. ábra)"))
    p["figures"] = [fig_bars("f1", "Negatív árú órák száma, havonta", [ml(k) for k in keys], [S("neg", "Negatív árú órák", neg)], "óra", 0)]
    if ann:
        ys = sorted(ann)
        p["figures"].append(fig_bars("f2", "Negatív árú órák száma, lezárt évek", ys, [S("ann", "Negatív árú órák", [ann[y] for y in ys])], "óra", 0))
    pts = [{"x": round(s, 2), "y": n} for s, n in zip(solar, neg) if s is not None]
    if pts:
        p["figures"].append(fig_scatter("f3", "Napenergia részaránya és negatív árú órák, havi értékpárok", pts, "Napenergia részaránya", "Negatív árú órák", "%", "óra", "Egy pont egy hónap."))
    p["interpretation"] = ["A negatív ár azt jelzi, hogy az adott órában a piacon több kínálat volt, mint amennyit a kereslet és a kapcsolt zónák felvenni tudtak; a napelemes termelés délutáni csúcsa ennek tipikus, de nem kizárólagos oka.",
                           "A korrelációs együttható az együttmozgás erősségét méri, az okozatot nem bizonyítja; a szomszédos zónák árai, a hőmérséklet és a hétvégék is hatnak."]
    tot_neg = sum(neg); warm = sum(h.f(k, "price", "neg_h") for k in keys if 4 <= int(k[5:7]) <= 9)
    p["conclusions"] = [f"Az elmúlt 12 lezárt hónapban {nf(n12, 0)} negatív árú óra volt." + (f" Ez az előző 12 hónaphoz képest {cw} ilyen óra." if cw else ""),
                        (f"A teljes vizsgált időszak negatív árú óráinak {pc(100 * warm / tot_neg)}-a áprilistól szeptemberig jelentkezett." if tot_neg > 0 else "A vizsgált időszakban nem volt negatív árú óra.")]
    p["limits"] += ["A day-ahead ár nem azonos a tényleges értékesítési árral: kiegyenlítő piaci és szabályozási elemek ebben nincsenek.",
                    "A negatív órák kisebb része 15 perces piaci időegységeket takarhat; a számítás órás értékekre épül."]
    p["sources"] = [SRC["price"], SRC["gen"]]
    return finish(h, p, keys)


# ---------------------------------------------------------------------------------------------------- 5. szomszédos zónák árai
def t_zones(h):
    p = new_pub(5, "szomszedos-zonak-arai", "Szomszédos zónák árai", "Mennyiben tér el a magyar day-ahead ár a szomszédos zónákétól?",
                "Mennyivel drágább vagy olcsóbb a magyar zóna a szomszédos ajánlati zónáknál, és milyen gyakran azonos az áruk?")
    zs = [z for z in ZORDER if z != "HU"]
    keys = [k for k in h.keys if h.f(k, "z", "HU", "avg") is not None]
    if len(keys) < 13:
        return insufficient(h, p, "legalább 13 lezárt hónap zónaára (ENTSO-E 12.1.D) Magyarországra és a szomszédos zónákra")
    l12 = keys[-12:]
    have = [z for z in zs if sum(1 for k in l12 if h.f(k, "z", z, "avg") is not None) >= 10]
    if not have:
        return insufficient(h, p, "a szomszédos zónák day-ahead ára az elmúlt 12 hónapra")
    avg12 = {z: mean([h.f(k, "z", z, "avg") for k in l12]) for z in ["HU"] + have}
    spread = {z: avg12["HU"] - avg12[z] for z in have}
    same = {z: mean([h.f(k, "z", z, "same") for k in l12]) for z in have}
    corr = {z: mean([h.f(k, "z", z, "corr") for k in l12]) for z in have}
    zone_dearer = [z for z in have if spread[z] < 0]       # a zóna drágább a magyarnál
    zone_cheaper = [z for z in have if spread[z] > 0]      # a zóna olcsóbb a magyarnál
    cmean = mean([v for v in corr.values() if v is not None])
    far = max(have, key=lambda z: abs(spread[z]))
    near = min(have, key=lambda z: abs(spread[z]))
    p["summary"] = [f"Az elmúlt 12 lezárt hónapban a magyar day-ahead átlagár {nf(avg12['HU'], 1)} €/MWh volt.",
                    f"A szomszédos zónák közül Magyarországtól a legnagyobb átlagos eltérés {ZNAME[far]} esetén látszik ({nf(spread[far], 1)} €/MWh, a magyar ár és a zóna ára különbsége), a legkisebb {ZNAME[near]} esetén ({nf(spread[near], 1)} €/MWh).",
                    f"A vizsgált {len(have)} zóna közül {len(zone_cheaper)} átlagosan olcsóbb a magyarnál, {len(zone_dearer)} drágább."]
    p["data"] = [data_desc(h, "A day-ahead zónaárak havi időátlagai Magyarországra és a szomszédos ajánlati zónákra", keys),
                 "Mértékegység: €/MWh; az azonos órák aránya százalék. A zónák: " + ", ".join(ZNAME[z] for z in have) + ". Szerbia és Ukrajna day-ahead ára az ENTSO-E-n nem áll rendelkezésre."]
    p["method"] = ["Havi átlagár = az óránkénti zónaárak időátlaga. Eltérés = a magyar havi átlagár mínusz a zóna havi átlagára; a 12 hónapos érték a havi átlagok számtani átlaga.",
                   "Azonos órák aránya = azoknak az óráknak a százaléka, amelyekben a két zóna day-ahead ára 0,01 €/MWh pontossággal megegyezik; a 12 hónapos érték a havi arányok átlaga."]
    p["analysis"] = ["Az elmúlt 12 hónap átlagos eltérései (magyar ár − zónaár): " + "; ".join(f"{ZNAME[z]}: {nf(spread[z], 1)} €/MWh" for z in sorted(have, key=lambda z: -spread[z])) + " (2. ábra).",
                     "Az azonos árú órák aránya: " + "; ".join(f"{ZNAME[z]}: {pc(same[z])}" for z in sorted(have, key=lambda z: -(same[z] or 0)) if same[z] is not None) + " (3. ábra)."]
    lines = [S("HU", ZNAME["HU"], [h.f(k, "z", "HU", "avg") for k in keys])] + [S(z, ZNAME[z], [h.f(k, "z", z, "avg") for k in keys]) for z in have]
    zc = ", ".join(f"{z.replace('_', '–')} = {ZNAME[z]}" for z in have)          # az ábra tengelyén rövid zónakód van, hogy minden oszlop felirata látsszon
    p["figures"] = [fig_line("f1", "Day-ahead átlagár zónánként, havonta", [ml(k) for k in keys], lines, "€/MWh", 1, "", jan_ticks(keys)),
                    fig_bars("f2", "A magyar ár eltérése a szomszédos zónáktól, az elmúlt 12 hónap átlagában", [z.replace("_", "–") for z in sorted(have, key=lambda z: -spread[z])], [S("d", "Magyar ár − zónaár", [spread[z] for z in sorted(have, key=lambda z: -spread[z])])], "€/MWh", 1, "Pozitív: Magyarországon drágább. Zónák: " + zc + ".")]
    sz = [z for z in sorted(have, key=lambda z: -(same[z] or 0)) if same[z] is not None]
    if sz:
        p["figures"].append(fig_bars("f3", "Azonos day-ahead árú órák aránya Magyarországgal, az elmúlt 12 hónap átlagában", [z.replace("_", "–") for z in sz], [S("s", "Azonos árú órák", [same[z] for z in sz])], "%", 1, "Zónák: " + zc + "."))
    p["interpretation"] = ["A day-ahead piac összekapcsolt: ha két zóna között nem szűk a határkeresztező kapacitás, az áruk megegyezik; az eltérés a szűk keresztmetszet jele. Az azonos árú órák aránya ezért a piaci összekapcsolódás szorosságát mutatja: minél magasabb, annál ritkábban volt szűk a keresztmetszet.",
                           "Az átlagos eltérés a hónapok átlagából számolt, ezért nem mutatja az órákon belüli különbségeket; a pozitív és negatív eltérések kiolthatják egymást."]
    p["conclusions"] = [f"Az elmúlt 12 lezárt hónapban a magyar day-ahead átlagár {nf(avg12['HU'], 1)} €/MWh volt, a szomszédos zónákhoz képest az eltérés {nf(min(spread.values()), 1)} és {nf(max(spread.values()), 1)} €/MWh között alakult.",
                        (f"A havi korrelációk átlaga a zónák között {nf(cmean, 2)}: a szomszédos zónák árai " + ("szorosan együtt mozognak a magyarral." if cmean >= 0.9 else "mérsékelten mozognak együtt a magyarral." if cmean >= 0.6 else "gyengén mozognak együtt a magyarral.") if cmean is not None else "Az árak együttmozgása nem számolható.")]
    p["limits"] += ["A zónaárak ajánlati zónákra, nem országokra vonatkoznak (pl. Németország–Luxemburg közös zóna).",
                    "A day-ahead ár nem tartalmazza a nap közbeni és a kiegyenlítő piacot."]
    p["sources"] = [SRC["price"]]
    return finish(h, p, keys)


# ---------------------------------------------------------------------------------------------------- 6. termelési mix
def t_mix(h):
    p = new_pub(6, "termelesi-mix", "Termelési mix átalakulása", "Hogyan alakult át a hazai villamosenergia-termelés összetétele?",
                "Hogyan változott az egyes termelési csoportok részaránya a lezárt években?")
    ys = [y for y in h.years if h.year_sum(y, lambda k: h.total_complete(k)) is not None]
    if len(ys) < 2:
        return insufficient(h, p, "legalább két lezárt év teljes termelési adata mind a nyolc termelési csoportra (ENTSO-E 16.1.B&C)")
    tot = {y: h.year_sum(y, lambda k: h.total_complete(k)) for y in ys}
    shr = {y: {g: 100 * h.year_sum(y, lambda k, g=g: h.gen(k, g)) / tot[y] for g in GROUPS} for y in ys}
    a, b = ys[0], ys[-1]
    d = {g: shr[b][g] - shr[a][g] for g in GROUPS}
    big_up = max(GROUPS, key=lambda g: d[g]); big_dn = min(GROUPS, key=lambda g: d[g])
    var = lambda y: shr[y]["solar"] + shr[y]["wind"]
    fos = lambda y: shr[y]["gas"] + shr[y]["coal"]
    p["summary"] = [f"A {a}. és a {b}. év között a legnagyobb részarány-növekedés a következő csoportnál látszik: {GLABEL[big_up].lower()} ({nf(d[big_up], 1)} százalékpont), a legnagyobb csökkenés: {GLABEL[big_dn].lower()} ({nf(d[big_dn], 1)} százalékpont).",
                    f"A fosszilis tüzelőanyagú termelés (földgáz és szén) részaránya a {a}. évi {pc(fos(a))}-ról a {b}. évi {pc(fos(b))}-ra változott.",
                    f"A változó megújuló termelés (nap és szél) részaránya a {a}. évi {pc(var(a))}-ról a {b}. évi {pc(var(b))}-ra változott."]
    p["data"] = [f"A termelés típusonkénti évi energiája (GWh) a {a}. és {b}. év között, {len(ys)} lezárt évre (ENTSO-E 16.1.B&C). Csak az az év számít, amelynek mind a 12 hónapjában megvan mind a nyolc csoport adata.",
                 "Mértékegység: GWh évente; a részarányok százalékban."]
    p["method"] = ["Részarány = a csoport évi termelése osztva az összes jelentett évi termeléssel. A csoportok: atomerőmű, földgáz, szén, napenergia, szél, biomassza és hulladék, víz, egyéb (az ENTSO-E besorolása szerint).",
                   "Fosszilis = földgáz + szén; változó megújuló = napenergia + szél. A százalékpont-változás a két év részarányának különbsége."]
    p["analysis"] = [f"A {b}. évben a részarányok: " + "; ".join(f"{GLABEL[g].lower()}: {pc(shr[b][g])}" for g in sorted(GROUPS, key=lambda g: -shr[b][g])) + " (1. ábra).",
                     f"A {a}. és {b}. év közötti változás százalékpontban: " + "; ".join(f"{GLABEL[g].lower()}: {nf(d[g], 1)}" for g in sorted(GROUPS, key=lambda g: -d[g])) + "."]
    gwh = {y: {g: h.year_sum(y, lambda k, g=g: h.gen(k, g)) for g in GROUPS} for y in ys}
    p["figures"] = [fig_bars("f1", "A termelés összetétele, lezárt évek (a jelentett termelés %-ában)", ys, [S(g, GLABEL[g], [shr[y][g] for y in ys]) for g in GROUPS], "%", 1, "", stacked=True),
                    fig_bars("f2", "A termelés összetétele, lezárt évek (GWh)", ys, [S(g, GLABEL[g], [gwh[y][g] for y in ys]) for g in GROUPS], "GWh", 0, "", stacked=True)]
    p["interpretation"] = ["A részarányok változása a termelés és az erőműpark átalakulását mutatja. A részarány azonban nem a villamosenergia-ellátás egészét írja le: az import és a fogyasztás szerkezete ebben nincs benne.",
                           "A százalékpont-változás a részarányok különbsége, nem az energia relatív változása; a csoportok mennyisége közben nőhetett is, ha az összes termelés nőtt."]
    p["conclusions"] = [f"A {a}. és {b}. év között a legnagyobb részarány-növekedés: {GLABEL[big_up].lower()} ({nf(d[big_up], 1)} százalékpont), a legnagyobb csökkenés: {GLABEL[big_dn].lower()} ({nf(d[big_dn], 1)} százalékpont); a teljes összetétel az 1. ábrán követhető."]
    p["limits"] += ["A hazai termelés részaránya nem azonos a fogyasztás forrásösszetételével, mert az import ebben nem szerepel.",
                    "A termelési csoportok besorolása az ENTSO-E adatszolgáltatásán múlik; a csoporton belüli átsorolás évek között torzíthat."]
    p["sources"] = [SRC["gen"]]
    return finish(h, p, [k for y in ys for k in h.year_keys(y)])


# ---------------------------------------------------------------------------------------------------- 7. megújulók és szabályozás
def t_flex(h):
    p = new_pub(7, "megujulok-es-szabalyozas", "Megújulók és szabályozás", "Mennyire nő a szabályozási igény a változó megújuló termelés bővülésével?",
                "Hogyan függ össze a nap- és szélenergia részaránya az esti rámpával és a rugalmas (gáz, víz) termeléssel?")
    keys = [k for k in h.keys if h.share(k, "solar") is not None and h.share(k, "wind") is not None and h.f(k, "ramp_p99") is not None]
    if len(keys) < 13:
        return insufficient(h, p, "legalább 13 lezárt hónap termelési és óránkénti terhelési adata (ENTSO-E 16.1.B&C, 6.1.A)")
    p["status"] = "részleges"
    vre = [h.share(k, "solar") + h.share(k, "wind") for k in keys]
    ramp = [h.f(k, "ramp_p99") for k in keys]
    flex = [(h.share(k, "gas") or 0) + (h.share(k, "hydro") or 0) for k in keys]
    r1, r2 = pearson(vre, ramp), pearson(vre, flex)
    ann = {}
    for y in h.years:
        ks = [k for k in h.year_keys(y) if k in set(keys)]
        if len(ks) == 12:
            ann[y] = (mean([h.share(k, "solar") + h.share(k, "wind") for k in ks]), mean([h.f(k, "ramp_p99") for k in ks]))
    p["summary"] = [f"A változó megújuló termelés (nap és szél) havi részaránya a vizsgált időszakban {pc(min(vre))} és {pc(max(vre))} között mozgott.",
                    corr_text(r1, "A változó megújuló részarány és az esti rámpa"),
                    "A ténylegesen igénybe vett szabályozási energia (aFRR, mFRR) mennyisége és költsége ebben az elemzésben még nem szerepel, mert ezek historikus adatsora nincs az adattárban."]
    p["data"] = [data_desc(h, "A nap- és szélenergia havi részaránya, az esti rámpa (a maradék terhelés 99. percentilise) és a rugalmas termelők (földgáz és víz) részaránya", keys),
                 "Mértékegység: % (részarány), MW/h (rámpa)."]
    p["method"] = ["Változó megújuló részarány = (napenergia + szélenergia) / összes jelentett termelés. Rugalmas részarány = (földgáz + víz) / összes jelentett termelés. Az esti rámpa számítását a 3. téma írja le.",
                   "Az együttmozgást a havi értékpárokra számolt Pearson-féle korrelációs együttható adja; ez leíró mutató."]
    p["analysis"] = [corr_text(r1, "A változó megújuló részarány és az esti rámpa") + " (3. ábra)", corr_text(r2, "A változó megújuló részarány és a rugalmas termelők részaránya")]
    if ann:
        ys = sorted(ann)
        p["analysis"].append("Évi átlagok: " + "; ".join(f"{y}: megújuló {pc(ann[y][0])}, rámpa {nf(ann[y][1], 0)} MW/h" for y in ys) + " (1–2. ábra).")
    ys = sorted(ann)
    p["figures"] = []
    if ann:
        p["figures"] += [fig_bars("f1", "A változó megújuló termelés (nap + szél) évi átlagos részaránya", ys, [S("v", "Nap + szél részaránya", [ann[y][0] for y in ys])], "%", 1),
                         fig_bars("f2", "Az esti rámpa évi átlaga (99. percentilis)", ys, [S("r", "Esti rámpa", [ann[y][1] for y in ys])], "MW/h", 0)]
    p["figures"].append(fig_scatter("f3", "Változó megújuló részarány és esti rámpa, havi értékpárok", [{"x": round(a, 2), "y": b} for a, b in zip(vre, ramp)], "Nap + szél részaránya", "Esti rámpa", "%", "MW/h", "Egy pont egy hónap."))
    p["interpretation"] = ["Az esti rámpa a maradék terhelés felfutásának meredekségét mutatja: ez az az igény, amelyet a szabályozható erőműveknek, a tárolóknak és az importnak kell fedezniük. A rámpa maga a szabályozási igény közelítő mutatója, nem a ténylegesen aktivált szabályozás.",
                           "A részarányok összege 100 %, ezért a rugalmas termelők részarányának és a megújulók részarányának negatív együttmozgása részben matematikai következmény, nem feltétlenül jelent működési összefüggést.",
                           "A változó megújuló részarány és az esti rámpa együttmozgását a szezonális fogyasztási minta és a szélenergia ingadozása is befolyásolja."]
    p["conclusions"] = [corr_text(r1, "A változó megújuló részarány és az esti rámpa"),
                        "A szabályozás tényleges költségéhez és mennyiségéhez további adatsor (ENTSO-E kiegyenlítési adatok) szükséges; ez a bővítés előkészítés alatt áll."]
    p["limits"] += ["Ez a téma részleges: a szabályozási energia (aFRR, mFRR) mennyiségi és pénzügyi adatai a historikus adattárban még nincsenek meg, ezért a szabályozási igényt közelítő mutatók (esti rámpa, rugalmas termelők részaránya) képviselik.",
                    "A rugalmas termelők csoportja (földgáz, víz) csak durva közelítés: a földgáz egy része kapcsolt, nem szabályozott termelés."]
    p["sources"] = [SRC["gen"], SRC["load"]]
    return finish(h, p, keys)


# ---------------------------------------------------------------------------------------------------- 8. kiesések és importigény
def t_outage(h):
    p = new_pub(8, "kiesesek-es-importigeny", "Kiesések és importigény", "Összefügg-e az atomerőművi termelés havi alakulása az importigénnyel?",
                "Hogyan alakul a nettó import azokban a hónapokban, amikor az atomerőművi termelés alacsonyabb?")
    keys = [k for k in h.keys if h.gen(k, "nuclear") is not None and h.import_share(k) is not None]
    if len(keys) < 13:
        return insufficient(h, p, "legalább 13 lezárt hónap atomerőművi termelési és nettó import adata (ENTSO-E 16.1.B&C, 12.1.G)")
    p["status"] = "részleges"
    nuc_mw = {k: h.mw(k, h.gen(k, "nuclear")) for k in keys}
    ref = {k: max(nuc_mw[j] for j in keys[max(0, i - 35):i + 1]) for i, k in enumerate(keys)}      # a saját, legfeljebb 36 hónapos mozgó maximuma
    idx = {k: (100.0 * nuc_mw[k] / ref[k] if ref[k] else None) for k in keys}
    sh = {k: h.import_share(k) for k in keys}
    r = pearson([idx[k] for k in keys], [sh[k] for k in keys])
    low = sorted(keys, key=lambda k: idx[k])[:3]
    flat = max(idx.values()) - min(idx.values()) < 1.0
    what8 = "Az atomerőművi termelési index és a nettó import"
    p["summary"] = ["A havi atomerőművi termelés a saját mozgó maximumához képest " + (f"{pc(min(idx.values()))} és {pc(max(idx.values()))} között mozgott." if not flat else "gyakorlatilag nem változott, ezért az összefüggés nem vizsgálható érdemben.") ,
                    corr_text(r, what8),
                    "Az egyes egységek kiesési adatai (ENTSO-E 15.1.A–D) historikus sorozata még nincs az adattárban, ezért ez az elemzés csak a termelés havi alakulásából következtet az elérhetőségre."]
    p["data"] = [data_desc(h, "Az atomerőművi termelés havi átlagteljesítménye (MW) és a nettó import a fogyasztás százalékában", keys),
                 "Mértékegység: MW (átlagteljesítmény), % (index és import aránya)."]
    p["method"] = ["Átlagteljesítmény = a hónap atomerőművi energiája (GWh) osztva a hónap óraszámával; az óraszám a nyári időszámítás miatt 23–25 órás napokat is helyesen tartalmaz.",
                   "Termelési index = az átlagteljesítmény százaléka az adott hónapig tartó legfeljebb 36 hónap legnagyobb havi átlagteljesítményének. Az index csökkenése jelezheti, hogy kisebb volt az elérhető atomerőművi teljesítmény, de okot nem azonosít.",
                   "Az importigény a 1. téma nettó import mutatója (a fogyasztás százalékában)."]
    p["analysis"] = ([] if flat else ["A három legalacsonyabb termelési indexű hónap: " + "; ".join(f"{month_long(k)} ({pc(idx[k])}, nettó import: {pc(sh[k])})" for k in low) + " (1–2. ábra)."]) + \
                    [("A havi atomerőművi termelés a vizsgált időszakban a saját mozgó maximumához képest nem változott, így az importigénnyel való összevetés nem ad információt (1–3. ábra)." if flat else corr_text(r, what8, " (3. ábra)"))]
    p["figures"] = [fig_line("f1", "Atomerőművi termelési index (a saját mozgó maximum %-ában), havonta", [ml(k) for k in keys], [S("i", "Termelési index", [idx[k] for k in keys])], "%", 1, "", jan_ticks(keys)),
                    fig_line("f2", "Nettó import a fogyasztás százalékában, havonta", [ml(k) for k in keys], [S("s", "Nettó import / fogyasztás", [sh[k] for k in keys])], "%", 1, "", jan_ticks(keys), zero=True),
                    fig_scatter("f3", "Atomerőművi termelési index és nettó import, havi értékpárok", [{"x": round(idx[k], 2), "y": round(sh[k], 2)} for k in keys], "Termelési index", "Nettó import / fogyasztás", "%", "%", "Egy pont egy hónap.")]
    p["interpretation"] = ["Az atomerőművi termelés havi csökkenése összhangban lehet tervezett karbantartásokkal és üzemanyagcserével, de a havi energiaadatból ez nem azonosítható; a kiesések tényleges időpontja és terjedelme egységszintű adatból olvasható le.",
                           "Az importigény sok más tényezőtől is függ (árak, időjárás, nap- és szélenergia), ezért a korreláció nem tekinthető az atomerőművi elérhetőség hatásának."]
    p["conclusions"] = [("A havi atomerőművi termelés ebben az adatsorban nem változott, ezért összefüggés nem állapítható meg." if flat else corr_text(r, what8)),
                        "A téma teljes körű elemzéséhez az egységszintű kiesési adatsor betöltése szükséges; ez a bővítés előkészítés alatt áll."]
    p["limits"] += ["Ez a téma részleges: az egységszintű (tervezett és nem tervezett) kiesések historikus adatsora nincs az adattárban, ezért a kiesés időtartama és teljesítménye nem szerepel.",
                    "A termelési index nem tesz különbséget kiesés és szándékos teljesítménycsökkentés között."]
    p["sources"] = [SRC["gen"], SRC["flow"], SRC["load"]]
    return finish(h, p, keys)


# ---------------------------------------------------------------------------------------------------- 9. CO2-intenzitás
def t_co2(h):
    p = new_pub(9, "co2-intenzitas", "CO₂-intenzitás", "Mekkora a magyar villamosenergia-termelés fajlagos CO₂-kibocsátása?",
                "Hogyan alakult a termelés-alapú CO₂-intenzitás (g CO₂-egyenérték/kWh), és mely csoportok adják a kibocsátást?")
    f = {g: h.co2.get(g) for g in GROUPS}
    if any(v is None for v in f.values()):
        return insufficient(h, p, "az életciklus-alapú kibocsátási tényezők mind a nyolc termelési csoportra")
    def inten(k):
        t = h.total_complete(k)
        return None if not t else sum(h.gen(k, g) * f[g] for g in GROUPS) / t
    keys = [k for k in h.keys if inten(k) is not None]
    if len(keys) < 13:
        return insufficient(h, p, "legalább 13 lezárt hónap termelési adata mind a nyolc termelési csoportra (ENTSO-E 16.1.B&C)")
    iv = [inten(k) for k in keys]
    l12 = keys[-12:]
    t12 = h.window_sum(l12, lambda k: h.total_complete(k)); e12 = h.window_sum(l12, lambda k: sum(h.gen(k, g) * f[g] for g in GROUPS))
    i12 = e12 / t12 if t12 else None
    p12 = keys[-24:-12] if len(keys) >= 24 else []
    tp = h.window_sum(p12, lambda k: h.total_complete(k)); ep = h.window_sum(p12, lambda k: sum(h.gen(k, g) * f[g] for g in GROUPS))
    iprev = ep / tp if tp else None
    ann = {}
    contrib = {}
    for y in h.years:
        ks = h.year_keys(y)
        if all(k in set(keys) for k in ks):
            t = h.year_sum(y, lambda k: h.total_complete(k))
            ann[y] = sum(h.year_sum(y, lambda k, g=g: h.gen(k, g)) * f[g] for g in GROUPS) / t
            contrib[y] = {g: h.year_sum(y, lambda k, g=g: h.gen(k, g)) * f[g] / t for g in GROUPS}
    cw = change_word(i12, iprev, 5, up="nőtt", down="csökkent")
    mx = max(keys, key=lambda k: inten(k)); mn = min(keys, key=lambda k: inten(k))
    p["summary"] = [f"Az elmúlt 12 lezárt hónapban a hazai termelés átlagos CO₂-intenzitása {nf(i12, 0)} g CO₂-egyenérték/kWh volt.",
                    (f"Az azt megelőző 12 hónapban {nf(iprev, 0)} g/kWh volt, vagyis a mutató {cw}." if cw and iprev is not None else "Az előző 12 hónapra nincs elég adat az összevetéshez."),
                    f"A havi érték legmagasabb {in_month(mx)} ({nf(inten(mx), 0)} g/kWh), legalacsonyabb {in_month(mn)} ({nf(inten(mn), 0)} g/kWh) volt."]
    p["data"] = [data_desc(h, "A termelés típusonkénti havi energiája (ENTSO-E 16.1.B&C) és az életciklus-alapú kibocsátási tényezők (IPCC AR5)", keys),
                 "Mértékegység: g CO₂-egyenérték/kWh. Minőség: becsült (számított érték, nem mért kibocsátás)."]
    p["method"] = ["Intenzitás = Σ (a csoport termelése × a csoport kibocsátási tényezője) / az összes termelés, az energiákkal súlyozva. A tényezők (g CO₂-egyenérték/kWh): " + ", ".join(f"{GLABEL[g].lower()} {f[g]}" for g in GROUPS) + ".",
                   "A tényezők életciklus-alapú mediánértékek, amelyek az üzemi kibocsátás mellett az építés és az üzemanyag-ellátási lánc hatását is tartalmazzák; így az atom-, nap- és szélenergia sem nulla."]
    p["analysis"] = [f"A havi intenzitás a vizsgált időszakban {nf(min(iv), 0)} és {nf(max(iv), 0)} g/kWh között mozgott (1. ábra)."]
    if ann:
        ys = sorted(ann)
        p["analysis"].append("Lezárt évekre: " + "; ".join(f"{y}: {nf(ann[y], 0)} g/kWh" for y in ys) + " (2. ábra).")
    p["figures"] = [fig_line("f1", "A hazai termelés CO₂-intenzitása, havonta", [ml(k) for k in keys], [S("i", "CO₂-intenzitás", iv)], "g/kWh", 0, "Becsült érték.", jan_ticks(keys))]
    if ann:
        ys = sorted(ann)
        p["figures"].append(fig_bars("f2", "A CO₂-intenzitás csoportonkénti hozzájárulása, lezárt évek (g/kWh)", ys, [S(g, GLABEL[g], [contrib[y][g] for y in ys]) for g in GROUPS], "g/kWh", 0, "A csoportok hozzájárulásának összege az évi intenzitás.", stacked=True))
    p["interpretation"] = ["A termelés-alapú intenzitás a hazai erőművek összetételét tükrözi; a földgáz és a szén részarányának változása a legnagyobb hatású tényező.",
                           "Mivel az import nincs benne, a mutató nem a fogyasztás fajlagos kibocsátása: a ténylegesen felhasznált villamos energia intenzitása az import összetételétől is függ."]
    p["conclusions"] = [f"A hazai termelés becsült CO₂-intenzitása az elmúlt 12 lezárt hónapban {nf(i12, 0)} g/kWh volt." + (f" Ez az előző 12 hónaphoz képest {cw}." if cw and iprev is not None else ""),
                        "A mutató becsült: a kiválasztott kibocsátási tényezők megváltoztatása a számot módosítja."]
    p["limits"] += ["Termelés-alapú mutató: az importált és exportált villamos energia kibocsátását nem tartalmazza.",
                    "A kibocsátási tényező csoportonként állandó; az egyes erőművek tényleges hatásfoka, a kapcsolt hőtermelés és az üzemanyag-összetétel eltérést okozhat.",
                    "Az „Egyéb” csoport tényezője durva közelítés, mert az ENTSO-E besorolása heterogén."]
    p["sources"] = [SRC["gen"], SRC["co2"]]
    return finish(h, p, keys)


# ---------------------------------------------------------------------------------------------------- 10. szezonális trendek
def t_season(h):
    p = new_pub(10, "szezonalis-trendek", "Szezonális trendek", "Hogyan változik évszakonként a fogyasztás és a termelés, és van-e hosszabb távú trend?",
                "Mekkora a fogyasztás szezonális ingadozása, hogyan alakult az éves fogyasztás, és milyen szezonális mintát követ a termelés összetétele?")
    keys = [k for k in h.keys if h.f(k, "load_avg") is not None]
    if len(keys) < 13 or len(h.years) < 2:
        return insufficient(h, p, "legalább két lezárt év havi fogyasztási adata (ENTSO-E 6.1.A)")
    ann = {}
    amp = {}
    for y in h.years:
        ks = h.year_keys(y)
        if all(h.f(k, "load_avg") is not None and h.f(k, "load_gwh") is not None for k in ks):
            ann[y] = sum(h.f(k, "load_gwh") for k in ks)
            vals = [h.f(k, "load_avg") for k in ks]
            amp[y] = 100.0 * (max(vals) - min(vals)) / mean(vals)
    if len(ann) < 2:
        return insufficient(h, p, "legalább két lezárt év teljes havi fogyasztási adata (ENTSO-E 6.1.A)")
    ys = sorted(ann)
    yoy = {y: 100.0 * (ann[y] / ann[ys[i - 1]] - 1) for i, y in enumerate(ys) if i > 0}
    a, b = ys[0], ys[-1]
    wmean = lambda y: mean([h.f(f"{y}-{m:02d}", "load_avg") for m in (12, 1, 2)]) if all(f"{y}-{m:02d}" in set(keys) for m in (12, 1, 2)) else None
    smean = lambda y: mean([h.f(f"{y}-{m:02d}", "load_avg") for m in (6, 7, 8)])
    ratio = {y: (wmean(y) / smean(y)) for y in ys if wmean(y) and smean(y)}
    tot = [h.total_complete(k) for k in keys]
    p["summary"] = [f"Az éves fogyasztás a {a}. évi {nf(ann[a], 0)} GWh-ról a {b}. évi {nf(ann[b], 0)} GWh-ra {'nőtt' if ann[b] > ann[a] else 'csökkent'} ({nf(100 * (ann[b] / ann[a] - 1), 1)} %).",
                    f"A havi átlagteljesítmény éven belüli ingadozása (legnagyobb és legkisebb hónap különbsége az évi átlag százalékában) a {b}. évben {pc(amp[b])} volt.",
                    (f"A téli (december–február) és a nyári (június–augusztus) átlagterhelés aránya a {max(ratio)}. évben {nf(ratio[max(ratio)], 2)} volt." if ratio else "A téli és nyári átlagterhelés aránya nem számolható teljes évekre.")]
    p["data"] = [data_desc(h, "A havi fogyasztás energiája (GWh) és átlagteljesítménye (MW) az ENTSO-E tény teljes terheléséből", keys),
                 "Mértékegység: GWh évente, MW (havi átlagteljesítmény), % (ingadozás)."]
    p["method"] = ["Éves fogyasztás = a 12 havi fogyasztási energia összege (csak teljes évekre). Éves változás = az éves fogyasztás százalékos különbsége az előző évhez képest.",
                   "Szezonális ingadozás = (a legnagyobb − a legkisebb havi átlagteljesítmény) / az évi átlagos havi átlagteljesítmény, százalékban. Téli/nyári arány = a december–február és a június–augusztus havi átlagteljesítmények átlagának hányadosa."]
    p["analysis"] = ["Az éves fogyasztás: " + "; ".join(f"{y}: {nf(ann[y], 0)} GWh" for y in ys) + " (2. ábra).",
                     "Az éves változás: " + "; ".join(f"{y}: {nf(yoy[y], 1)} %" for y in ys[1:]) + ".",
                     "A szezonális ingadozás évenként: " + "; ".join(f"{y}: {pc(amp[y])}" for y in ys) + " (3. ábra)."]
    # termelés szezonalitása: csoportonkénti havi átlagteljesítmény (MW) az elmúlt 24 lezárt hónapban
    gk = [k for k in keys[-24:] if h.total_complete(k) is not None]
    l12g = [k for k in gk[-12:]]
    summ = [k for k in l12g if int(k[5:7]) in (6, 7, 8)]; wint = [k for k in l12g if int(k[5:7]) in (12, 1, 2)]
    if len(summ) == 3 and len(wint) == 3:
        gm = lambda ks, g: mean([h.mw(k, h.gen(k, g)) for k in ks])
        p["analysis"].append("Az elmúlt 12 hónap termelése csoportonként, havi átlagteljesítmény (téli: december–február, nyári: június–augusztus): " +
                             "; ".join(f"{GLABEL[g].lower()}: {nf(gm(wint, g), 0)} MW télen, {nf(gm(summ, g), 0)} MW nyáron" for g in ("gas", "solar", "wind", "nuclear")) + " (4. ábra).")
    p["figures"] = [fig_line("f1", "Havi átlagos fogyasztás (MW), évenként a naptári hónapok fölött", MON_SHORT, [S("y" + y, y, v) for y, v in year_overlay(h, lambda k: h.f(k, "load_avg"))], "MW", 0),
                    fig_bars("f2", "Éves fogyasztás, lezárt évek (GWh)", ys, [S("a", "Éves fogyasztás", [ann[y] for y in ys])], "GWh", 0),
                    fig_bars("f3", "A havi átlagteljesítmény éven belüli ingadozása, lezárt évek", ys, [S("amp", "Szezonális ingadozás", [amp[y] for y in ys])], "%", 1)]
    if len(gk) >= 12:
        p["figures"].append(fig_bars("f4", "Termelés csoportonként, havi átlagteljesítmény az elmúlt 24 hónapban (MW)", [ml(k) for k in gk],
                                     [S(g, GLABEL[g], [h.mw(k, h.gen(k, g)) for k in gk]) for g in GROUPS], "MW", 0, "", stacked=True))
    p["interpretation"] = ["A fogyasztás szezonális mintája a fűtés, a hűtés és a világítás évszakos változásához kötődik; a havi átlagok az éven belüli különbséget mutatják, az időjárás évek közötti különbségei ezt módosítják.",
                           "A két-három éves változásokból trend nem olvasható le megbízhatóan: az évek időjárása és a gazdasági helyzet külön-külön is érezhetően hat."]
    p["conclusions"] = [f"Az éves fogyasztás a {a}. és {b}. év között {nf(100 * (ann[b] / ann[a] - 1), 1)} %-kal változott.",
                        "A szezonális ingadozás mértéke évről évre eltér; hosszabb távú iránya a fenti ábrán követhető."]
    p["limits"] += ["A fogyasztás időjárásfüggő; az adat hőmérséklet-korrekció nélküli.",
                    "A termelési összetétel szezonalitását a jelentett termelés mutatja; a kapcsolt (hőigényhez kötött) földgáztermelés szezonális mintája és a szabályozott termelés itt nem választható szét.",
                    "A tény teljes terhelés (6.1.A) nem tartalmazza a mérők mögötti (pl. háztartási napelemes önfogyasztás) fogyasztást."]
    p["sources"] = [SRC["load"], SRC["gen"]]
    return finish(h, p, keys)


TOPICS = [t_import, t_solar_share, t_ramp, t_negative, t_zones, t_mix, t_flex, t_outage, t_co2, t_season]
FEATURED = "napenergia-es-esti-rampa"


# ---------------------------------------------------------------------------------------------------- HTML
SECTIONS = [("kerdes", "Kérdés"), ("osszefoglalo", "Rövid összefoglaló"), ("adatok", "Adatok"), ("modszer", "Módszer"), ("elemzes", "Elemzés"),
            ("abrak", "Ábrák"), ("ertelmezes", "Értelmezés"), ("kovetkeztetesek", "Következtetések"), ("korlatok", "Korlátok"), ("forrasok", "Források")]


def jdump(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def fig_table(fg):
    """JavaScript nélkül ugyanazt az adatot táblázatban mutatja."""
    if fg["kind"] == "scatter":
        rows = "".join(f"<tr><td class=\"r num\">{esc(nf(p['x'], 2))}</td><td class=\"r num\">{esc(nf(p['y'], 2))}</td></tr>" for p in fg["points"])
        return f"<table><caption>{esc(fg['title'])}</caption><thead><tr><th scope=\"col\" class=\"r\">{esc(fg['xLabel'])} ({esc(fg['xUnit'])})</th><th scope=\"col\" class=\"r\">{esc(fg['yLabel'])} ({esc(fg['yUnit'])})</th></tr></thead><tbody>{rows}</tbody></table>"
    head = "".join(f"<th scope=\"col\" class=\"r\">{esc(s['label'])}</th>" for s in fg["series"])
    rows = ""
    for i, lab in enumerate(fg["labels"]):
        cells = "".join("<td class=\"r num\">" + (esc(nf(s["values"][i], fg.get("dec", 1))) if s["values"][i] is not None else "–") + "</td>" for s in fg["series"])
        rows += f"<tr><th scope=\"row\">{esc(lab)}</th>{cells}</tr>"
    return f"<table><caption>{esc(fg['title'])} ({esc(fg['unit'])})</caption><thead><tr><th scope=\"col\">Időszak</th>{head}</tr></thead><tbody>{rows}</tbody></table>"


def ul(items):
    return "<ul>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"


def paras(items):
    return "".join(f"<p>{esc(i)}</p>" for i in items)


QUALITY_TXT = {"végleges": ("final", "Végleges"), "előzetes": ("prelim", "Előzetes"), "hiányzik": ("miss", "Hiányzik")}


MENU = [("index.html", "Főoldal"), ("elemzesek.html", "Elemzések"), ("rendszerkep.html", "Adatok: aktuális rendszerkép"), ("historikus.html", "Historikus adatok"),
        ("eromuvek.html", "Erőművek és termelőegységek"), ("idojaras.html", "Időjárási adatok"), ("foldgaz.html", "Földgáz és tárolók"),
        ("nemzetkozi.html", "Nemzetközi összehasonlítás"), ("modszertan.html", "Módszertan és adatforrások"), ("rolunk.html", "Rólunk")]


def ns_nav(root):
    """JavaScript nélkül a gf.js nem építi a főmenüt: ez a tartalék, hogy az oldalak így is elérhetők legyenek egymásból."""
    return '<noscript><nav class="nsnav" aria-label="Főmenü">' + "".join(f'<a href="{root}{h}">{esc(t)}</a>' for h, t in MENU) + "</nav></noscript>"


def render_page(pub, hist, demo):
    qk = QUALITY_TXT.get(pub["quality"], ("final", "Végleges"))[0]
    title = f"{pub['topic']} – GridFlow Analytics"
    thru = month_long(pub["data_through"]) if pub["data_through"] else "nincs adat"
    status_note = "" if pub["status"] == "teljes" else f"<p class=\"banner warn\" role=\"note\"><b>{esc(pub['status'].capitalize())}.</b> {esc(pub['limits'][-1] if pub['status'] == 'adatra vár' else 'Ez az elemzés a jelenleg elérhető adatokra épül; a hiányzó részeket a Korlátok rész sorolja fel.')}</p>"
    demo_note = "<div class=\"banner demo\" role=\"status\"><b>DEMO ADAT</b> – szintetikus, nem valós mérés. A számok csak az oldal működését mutatják.</div>" if demo else ""
    body = [f'<article class="pub" data-slug="{esc(pub["slug"])}">',
            f'<header><p class="eyebrow">Elemzés · {esc(pub["topic"])}</p><h1>{esc(pub["title"])}</h1>',
            f'<p class="pubmeta"><span>Adatok állása: <b>{esc(thru)}</b></span> <span class="q-slot" data-q="{qk}">Minőség: <b>{esc(pub["quality"])}</b></span> <span>Állapot: <b>{esc(pub["status"])}</b></span></p></header>',
            status_note]
    fig_html = ""
    for fg in pub["figures"]:
        spec = {k: v for k, v in fg.items() if k not in ("caption",)}
        cap = f"<figcaption><b>{esc(fg['title'])}</b>" + (f" – {esc(fg['caption'])}" if fg.get("caption") else "") + "</figcaption>"
        fig_html += (f'<figure class="fig" id="{esc(fg["id"])}">{cap}<div class="chart" data-fig="{esc(fg["id"])}"></div>'
                     f'<script type="application/json" id="{esc(fg["id"])}-data">{jdump(spec)}</script>'
                     f'<noscript><div class="tscroll">{fig_table(fg)}</div></noscript></figure>')
    if not pub["figures"]:
        fig_html = "<p>Ehhez a témához jelenleg nincs megjeleníthető ábra.</p>"
    hist_link = '<p class="hint">Az adatok tovább vizsgálhatók a <a href="../historikus.html">Historikus adatok</a> oldalon.</p>'
    secs = {
        "kerdes": paras([pub["question"]]), "osszefoglalo": ul(pub["summary"]), "adatok": paras(pub["data"]), "modszer": paras(pub["method"]),
        "elemzes": paras(pub["analysis"]), "abrak": fig_html + hist_link, "ertelmezes": paras(pub["interpretation"]), "kovetkeztetesek": ul(pub["conclusions"]),
        "korlatok": ul(pub["limits"]), "forrasok": ul(pub["sources"] + ["GridFlow Analytics saját számítás; módszertan: Módszertan oldal."]),
    }
    for i, (sid, sname) in enumerate(SECTIONS, 1):
        body.append(f'<section id="{sid}"><h2><span class="sn">{i}.</span> {esc(sname)}</h2>{secs[sid]}</section>')
    body.append('<p class="pubnav"><a href="../elemzesek.html">← Összes elemzés</a> · <a href="../modszertan.html">Módszertan</a></p></article>')
    return f'''<!doctype html>
<html lang="hu">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<link rel="icon" href="data:,">
<meta name="description" content="{esc(pub['summary'][0] if pub['summary'] else pub['question'])}">
<link rel="stylesheet" href="../assets/gf.css">
<script src="../assets/gf.js"></script>
<script src="../assets/gfchart.js" defer></script>
<script src="../assets/gfpub.js" defer></script>
</head>
<body data-root="../" data-section="elemzesek" data-page="elemzesek/{esc(pub['slug'])}.html"{' data-demo="1"' if demo else ''}>
{ns_nav("../")}
<main>
{demo_note}
{''.join(body)}
</main>
<noscript><p style="padding:16px">Az ábrák JavaScript nélkül táblázatként jelennek meg.</p></noscript>
</body>
</html>
'''


def build(hist_raw, out_dir, demo=False, verbose=True):
    h = Hist(hist_raw)
    os.makedirs(out_dir, exist_ok=True)
    index = []
    for fn in TOPICS:
        pub = fn(h)
        page = render_page(pub, h, demo or h.demo)
        path = os.path.join(out_dir, pub["slug"] + ".html")
        write_if_changed(path, page)
        index.append({"slug": pub["slug"], "n": pub["n"], "topic": pub["topic"], "title": pub["title"], "question": pub["question"],
                      "summary": pub["summary"][0] if pub["summary"] else "", "status": pub["status"], "quality": pub["quality"],
                      "data_through": pub["data_through"], "figures": len(pub["figures"]), "featured": pub["slug"] == FEATURED})
        if verbose:
            print(f"  {pub['n']:>2}. {pub['slug']:<28} {pub['status']:<11} ábra: {len(pub['figures'])}")
    if not any(i["featured"] and i["status"] != "adatra vár" for i in index):          # ha a kiemelt téma adatra vár, az első elérhető lesz a kiemelt
        for i in index:
            i["featured"] = False
        for i in index:
            if i["status"] != "adatra vár":
                i["featured"] = True
                break
    meta = {"schema": SCHEMA, "demo": bool(demo or h.demo), "data_generated_utc": h.generated, "data_through": h.keys[-1] if h.keys else None, "publications": index}
    write_if_changed(os.path.join(out_dir, "index.json"), json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    return meta


def write_if_changed(path, text):
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return False
    except FileNotFoundError:
        pass
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--history", default="history.json")
    ap.add_argument("--out", default="elemzesek")
    ap.add_argument("--demo", action="store_true", help="a kimeneti oldalakat DEMO-nak jelöli")
    a = ap.parse_args(argv)
    try:
        with open(a.history, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        print(f"HIBA: a {a.history} nem olvasható ({e}); az elemzések nem épültek meg.", file=sys.stderr)
        return 2
    meta = build(raw, a.out, demo=a.demo)
    print(f"Kész: {len(meta['publications'])} elemzés → {a.out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
