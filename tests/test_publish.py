"""Az elemzés-generátor (publish.py) tesztje, böngésző nélkül.

Mit ellenőriz:
  - a demo adatból mind a tíz elemzés megépül, mindegyik rögzített tízrészes szerkezetben, a rögzített sorrendben,
  - az index.json szerkezete és a témák (slug, cím, állapot, minőség) egyezése az oldalakkal,
  - az ábraadatok (beágyazott JSON) értelmesek: nincs NaN, végtelen, None-szöveg, és minden ábrához van <noscript> táblázat,
  - a szövegben szereplő számok újraszámolhatók az eredeti adatból (importfüggőség: a legutóbbi 12 hónap aránya),
  - hiányzó adatnál a téma „adatra vár” állapotot kap és a Korlátok kimondja, nincs összeomlás, nincs kitalált szám,
  - teljesen üres adatnál is mind a tíz oldal megépül,
  - a generálás determinista (két futás bájtra azonos), és az újrafuttatás nem írja át a változatlan fájlt,
  - a Kezdőlap <noscript> témalistája megegyezik a generált témákkal,
  - a kimenetben nincs titok, nincs külső kérés (http/https forrás), és a szövegben nincs hibás szóhasználat („áram” az energia helyett).

Futtatás:  python -I tests/test_publish.py
"""
import copy
import hashlib
import html
import json
import math
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import publish as pb  # noqa: E402

FAIL = []
SECTIONS = ["Kérdés", "Rövid összefoglaló", "Adatok", "Módszer", "Elemzés", "Ábrák", "Értelmezés", "Következtetések", "Korlátok", "Források"]
BAD_WORDS = ("áramrendszer", "áramtermel", "áramot termel", "áramár", "áramfogyaszt", "áramimport", "áramexport")


def check(ok, msg):
    print(("  ok   " if ok else "  HIBA ") + msg)
    if not ok:
        FAIL.append(msg)


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def visible(s):
    s = re.sub(r"<script.*?</script>", " ", s, flags=re.S)
    s = re.sub(r"<style.*?</style>", " ", s, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", s))


def build(raw, tmp, name, demo=True):
    out = os.path.join(tmp, name)
    meta = pb.build(raw, out, demo=demo, verbose=False)
    return out, meta


def walk(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)
    else:
        yield o


def digest(d):
    h = {}
    for f in sorted(os.listdir(d)):
        h[f] = hashlib.sha256(open(os.path.join(d, f), "rb").read()).hexdigest()
    return h


def main():
    raw = json.load(open(os.path.join(ROOT, "demo-history.json"), encoding="utf-8"))
    tmp = tempfile.mkdtemp(prefix="pubtest-")

    print("[a demo adatból mind a tíz elemzés megépül]")
    out, meta = build(raw, tmp, "a")
    pubs = meta["publications"]
    slugs = [p["slug"] for p in pubs]
    check(len(pubs) == 10 and len(set(slugs)) == 10, "tíz egyedi téma (%d)" % len(pubs))
    files = sorted(f for f in os.listdir(out) if f.endswith(".html"))
    check(sorted(s + ".html" for s in slugs) == files, "minden témához van oldal, felesleg nincs")
    check(meta["schema"] == 1 and meta["demo"] is True and meta["data_through"] == "2026-10", "index.json: séma, demo jelző, a legutóbbi lezárt hónap (%s)" % meta["data_through"])
    check(sum(1 for p in pubs if p["featured"]) == 1, "pontosan egy kiemelt elemzés")
    check([p["n"] for p in pubs] == list(range(1, 11)), "a témák sorszámozása 1–10")
    idx = json.load(open(os.path.join(out, "index.json"), encoding="utf-8"))
    check(idx == json.loads(json.dumps(meta)), "az index.json a visszaadott meta tartalma")
    for p in pubs:
        check(all(p.get(k) not in (None, "") for k in ("slug", "topic", "title", "question", "summary", "status", "quality", "data_through")), "%s: az index-bejegyzés minden mezője kitöltött" % p["slug"])
    check(any(p["status"] == "részleges" for p in pubs) and all(p["status"] in ("teljes", "részleges", "adatra vár") for p in pubs),
          "az állapotok: %s" % sorted({p["status"] for p in pubs}))

    print("[oldalszerkezet, ábrák, szöveg]")
    for p in pubs:
        s = read(os.path.join(out, p["slug"] + ".html"))
        h2 = [re.sub(r"<[^>]+>", "", x).strip() for x in re.findall(r"<h2>(.*?)</h2>", s, re.S)]
        names = [re.sub(r"^\d+\.\s*", "", x) for x in h2]
        check(names == SECTIONS, "%s: a tíz szakasz rögzített sorrendben van" % p["slug"])
        check(s.count("<h1>") == 1 and "<title>" in s and 'name="description"' in s and 'lang="hu"' in s, "%s: egy h1, cím, leírás, nyelv" % p["slug"])
        ids = re.findall(r'id="(f\d+)-data"', s)
        figs = re.findall(r'<figure class="fig" id="(f\d+)"', s)
        check(ids == figs and len(figs) == p["figures"], "%s: ábraadat és ábra párban (%d)" % (p["slug"], len(figs)))
        bad_fig = []
        for fid in ids:
            d = json.loads(re.search(r'id="%s-data">(.*?)</script>' % fid, s, re.S).group(1))
            if any(isinstance(v, float) and (math.isnan(v) or math.isinf(v)) for v in walk(d)):
                bad_fig.append(fid)
        check(not bad_fig, "%s: az ábraadatokban nincs NaN/végtelen %s" % (p["slug"], bad_fig))
        fig_blocks = re.findall(r'<figure class="fig".*?</figure>', s, re.S)
        check(all("<noscript>" in b and "<table" in b for b in fig_blocks), "%s: minden ábrához van JavaScript nélküli táblázat" % p["slug"])
        text = visible(s)
        bad_txt = [w for w in ("NaN", "None", "undefined", "null", "inf ") if re.search(r"(?<![\w-])" + re.escape(w.strip()) + r"(?![\w-])", text)]
        check(not bad_txt, "%s: a látható szövegben nincs technikai maradvány %s" % (p["slug"], bad_txt))
        check(not re.search(r"\{[a-z_]+\}", text), "%s: nincs kitöltetlen helyőrző" % p["slug"])
        check(not [w for w in BAD_WORDS if w in text.lower()], "%s: nincs hibás szóhasználat („áram” az energia helyett)" % p["slug"])
        check(not re.search(r'(?:src|href)="https?://', s.replace('href="https://github.com', "")), "%s: nincs külső forrás betöltése (http/https)" % p["slug"])
        check(not re.search(r"(?i)token|api[_ -]?key|secret", text), "%s: nincs titokra utaló szöveg" % p["slug"])
        check(p["title"] in text and html.unescape(p["summary"]).replace("\xa0", " ")[:30] in text.replace("\xa0", " "), "%s: a cím és az összefoglaló egyezik az indexszel" % p["slug"])

    print("[a szövegben szereplő szám újraszámolható]")
    keys = sorted(k for k, m in raw["months"].items() if not m.get("partial"))
    last12 = keys[-12:]
    imp = sum(raw["months"][k]["imp_gwh"] for k in last12)
    load = sum(raw["months"][k]["load_gwh"] for k in last12)
    exp = pb.nf(100.0 * imp / load, 1)
    s = read(os.path.join(out, "importfuggoseg.html"))
    check(exp in visible(s).replace("\xa0", " ") or exp in visible(s), "importfüggőség: a legutóbbi 12 hónap aránya (%s %%) megegyezik az újraszámolt értékkel" % exp)
    first, last = pb.month_long(last12[0]), pb.month_long(last12[-1])
    check(first in visible(s) and last in visible(s), "importfüggőség: a 12 hónapos ablak határai (%s – %s) a szövegben vannak" % (first, last))

    print("[hiányzó adat: adatra vár, nincs kitalált szám]")
    r2 = copy.deepcopy(raw)
    for m in r2["months"].values():
        m.pop("price", None)
        m.pop("z", None)
    out2, meta2 = build(r2, tmp, "b")
    st = {p["slug"]: p["status"] for p in meta2["publications"]}
    check(len(st) == 10 and st["negativ-arak"] == "adatra vár", "ár nélkül a negatív árak témája „adatra vár” (%s)" % st["negativ-arak"])
    s = read(os.path.join(out2, "negativ-arak.html"))
    check("nincs elegendő adat" in visible(s) and "Korlátok" in visible(s), "az „adatra vár” oldal kimondja, hogy nincs elég adat")
    check(not re.search(r"\d+,\d\s*(%|€)", visible(s).split("Korlátok")[0]), "az „adatra vár” oldalon nincs kitalált százalék vagy ár")
    check(st["importfuggoseg"] == "teljes", "az ártól független téma nem sérül (%s)" % st["importfuggoseg"])
    r3 = copy.deepcopy(raw)
    r3["months"] = {}
    out3, meta3 = build(r3, tmp, "c")
    check(len(meta3["publications"]) == 10 and all(p["status"] == "adatra vár" for p in meta3["publications"]), "üres adatnál is mind a tíz oldal megépül, mind „adatra vár”")
    check(meta3["data_through"] is None, "üres adatnál nincs „adatok állása” dátum")
    r4 = copy.deepcopy(raw)
    last_key = sorted(r4["months"])[-1]
    r4["months"][last_key]["partial"] = True
    out4, meta4 = build(r4, tmp, "d")
    check(meta4["data_through"] < meta["data_through"] or meta4["data_through"] == sorted(k for k, m in r4["months"].items() if not m.get("partial"))[-1],
          "a folyamatban lévő (részleges) hónap nem számít lezártnak (%s)" % meta4["data_through"])

    print("[determinizmus]")
    out5, _ = build(raw, tmp, "e")
    check(digest(out) == digest(out5), "két futás bájtra azonos fájlokat ad")
    p0 = os.path.join(out, "importfuggoseg.html")
    t0 = os.stat(p0).st_mtime_ns
    pb.build(raw, out, demo=True, verbose=False)
    check(os.stat(p0).st_mtime_ns == t0, "az újrafuttatás nem írja át a változatlan fájlt")

    print("[Kezdőlap <noscript> témalistája]")
    idx_html = read(os.path.join(ROOT, "index.html"))
    ns = re.findall(r"<noscript><ul>(.*?)</ul></noscript>", idx_html, re.S)
    links = re.findall(r'<a href="elemzesek/([a-z0-9-]+)\.html">(.*?)</a>', ns[0]) if ns else []
    check(sorted(l[0] for l in links) == sorted(slugs), "a Kezdőlap noscript-listája pontosan a tíz témát tartalmazza")
    topic = {p["slug"]: p["topic"] for p in pubs}
    check(all(html.unescape(t) == topic[sl] for sl, t in links), "a noscript-lista szövege a téma neve")

    print("\n%s" % ("MINDEN OK" if not FAIL else "%d HIBA:\n  - " % len(FAIL) + "\n  - ".join(FAIL)))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
