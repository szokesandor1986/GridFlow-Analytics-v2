"""Az oldalszerkezet statikus ellenőrzése, böngésző nélkül (a közzétételi workflow-ban is futtatható).

Mit ellenőriz minden gyökérszintű oldalra és a demo elemzésekre:
  - nyelv, cím, leírás, viewport, a body data-section/data-page egyezik a fájlnévvel,
  - a hét főmenüpont és a JavaScript nélküli tartalék menü (noscript) létezik, és minden pontja létező oldalra mutat,
  - a hivatkozott szkriptek, stíluslapok, demo-adatfájlok léteznek, a közös szkript sorrendje helyes,
  - minden belső hivatkozás létező fájlra és létező horgonyra (#id) mutat; az elemzések linkjei a generált témákra,
  - a HTML címkéi kiegyensúlyozottak, nincs külső (http/https) szkript vagy stíluslap,
  - a látható szövegben nincs hibás szóhasználat („áram” az energia helyett),
  - a Rendszerkép szekciói (A–G) és a rájuk mutató ugrólinkek megvannak.

Futtatás:  python -I tests/test_site.py
"""
import html
import json
import os
import re
import sys
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = []
SECTIONS = {"kezdolap", "elemzesek", "adatok", "rolunk"}
MENU = ["index.html", "elemzesek.html", "rendszerkep.html"]                      # a három főmenüpont (Főoldal, Elemzések, Adatok)
DATA = ["rendszerkep.html", "historikus.html", "eromuvek.html", "idojaras.html", "foldgaz.html", "nemzetkozi.html", "modszertan.html"]   # az Adatok modulsora
SUB = ["rendszerkep.html", "hatarok.html", "muszaki.html", "europa.html"]       # az aktuális rendszerkép nézetei
NSMENU = ["index.html", "elemzesek.html", "rendszerkep.html", "historikus.html", "eromuvek.html", "idojaras.html", "foldgaz.html", "nemzetkozi.html",
          "modszertan.html", "rolunk.html"]                                      # a JavaScript nélküli tartalék menü
SECTION_OF = {"index": "kezdolap", "elemzesek": "elemzesek", "rolunk": "rolunk"}
for _n in ("rendszerkep", "hatarok", "muszaki", "europa", "idojaras", "foldgaz", "historikus", "eromuvek", "nemzetkozi", "modszertan"):
    SECTION_OF[_n] = "adatok"
BAD_WORDS = ("áramrendszer", "áramtermel", "áramot termel", "áramár", "áramfogyaszt", "áramimport", "áramexport")
VOID = {"meta", "link", "br", "hr", "img", "input", "source", "area", "base", "col", "embed", "param", "track", "wbr"}
TRACK = {"div", "section", "ul", "ol", "li", "table", "thead", "tbody", "tr", "td", "th", "nav", "main", "header", "footer", "article", "details", "summary",
         "figure", "form", "select", "button", "a", "span", "p", "h1", "h2", "h3", "noscript", "label", "script", "style", "body", "head", "html"}


def check(ok, msg):
    print(("  ok   " if ok else "  HIBA ") + msg)
    if not ok:
        FAIL.append(msg)


class Parse(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.errors, self.links, self.ids, self.scripts, self.styles = [], [], [], set(), [], []
        self.text, self.skip, self.body, self.ns_links, self.in_ns, self.title = [], 0, {}, [], 0, ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "body":
            self.body = a
        if tag == "a" and a.get("href") is not None:
            self.links.append(a["href"])
            if self.in_ns:
                self.ns_links.append(a["href"])
        if tag == "script" and a.get("src"):
            self.scripts.append(a["src"])
        if tag == "link" and a.get("rel") == "stylesheet":
            self.styles.append(a.get("href", ""))
        if tag == "noscript":
            self.in_ns += 1
        if tag in ("script", "style"):
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag in TRACK:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1
        if tag == "noscript":
            self.in_ns -= 1
        if tag == "title":
            self._in_title = False
        if tag in TRACK:
            if tag in self.stack:
                # a ki nem zárt <p>/<li> automatikusan záródik; a többi címke sorrendjének egyeznie kell
                while self.stack and self.stack[-1] != tag:
                    t = self.stack.pop()
                    if t not in ("p", "li", "td", "th", "tr", "thead", "tbody"):
                        self.errors.append("nem zárt <%s> a </%s> előtt" % (t, tag))
                self.stack.pop()
            else:
                self.errors.append("felesleges </%s>" % tag)

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if not self.skip:
            self.text.append(data)


def parse(path):
    p = Parse()
    p.feed(open(path, encoding="utf-8").read())
    p.close()
    return p


def exists_target(href, base_dir, demo_map=False):
    """Belső hivatkozás célja: (fájl létezik, horgony létezik)."""
    h = href.split("?")[0]
    frag = href.split("#")[1] if "#" in href else ""
    path = h.split("#")[0]
    if not path:
        return None, frag
    full = os.path.normpath(os.path.join(base_dir, path))
    if not os.path.exists(full) and path.startswith(("elemzesek/", "../elemzesek/")):
        # a production elemzések a közzétételkor készülnek: a demo-változat azonos nevű oldala a mérce
        alt = os.path.join(ROOT, "demo-elemzesek", os.path.basename(path))
        return (alt if os.path.exists(alt) else None), frag
    return (full if os.path.exists(full) else None), frag


def main():
    pages = sorted(f for f in os.listdir(ROOT) if f.endswith(".html"))
    check(set(SECTION_OF) == {p[:-5] for p in pages}, "a gyökérben pontosan a várt oldalak vannak %s" % sorted(p[:-5] for p in pages))
    cache = {}

    def ids_of(path):
        if path not in cache:
            cache[path] = parse(path).ids if path.endswith(".html") else set()
        return cache[path]

    docs = [(f, os.path.join(ROOT, f), ROOT) for f in pages]
    ed = os.path.join(ROOT, "demo-elemzesek")
    docs += [("demo-elemzesek/" + f, os.path.join(ed, f), ed) for f in sorted(os.listdir(ed)) if f.endswith(".html")]
    for name, path, base in docs:
        P = parse(path)
        raw = open(path, encoding="utf-8").read()
        root_page = os.path.dirname(name) == ""
        key = name[:-5] if root_page else None
        print("[%s]" % name)
        check('<html lang="hu"' in raw and 'name="viewport"' in raw and 'name="description"' in raw and len(P.title.strip()) > 8, "%s: nyelv, viewport, leírás, cím" % name)
        if root_page:
            check(P.body.get("data-page") == name and P.body.get("data-section") == SECTION_OF[key], "%s: data-page és data-section helyes (%s / %s)" % (name, P.body.get("data-page"), P.body.get("data-section")))
        else:
            check(P.body.get("data-root") == "../" and P.body.get("data-section") == "elemzesek", "%s: data-root és data-section helyes" % name)
        check(not P.errors and not P.stack, "%s: a címkék kiegyensúlyozottak %s" % (name, (P.errors + P.stack)[:3]))
        ns = [l for l in P.ns_links]
        rootp = "" if root_page else "../"
        check(ns[:len(NSMENU)] == [rootp + m for m in NSMENU], "%s: a JavaScript nélküli tartalék menü a tíz pontot tartalmazza" % name)
        gf = [s for s in P.scripts if s.endswith("gf.js")]
        check(len(gf) == 1 and P.scripts[0] == gf[0], "%s: a gf.js az első szkript" % name)
        bad_ext = [s for s in P.scripts + P.styles if re.match(r"(https?:)?//", s)]
        check(not bad_ext, "%s: nincs külső szkript vagy stíluslap %s" % (name, bad_ext))
        miss = [s for s in P.scripts + P.styles if not re.match(r"(https?:)?//", s) and not os.path.exists(os.path.join(base, s.split("?")[0]))]
        check(not miss, "%s: minden szkript és stíluslap létezik %s" % (name, miss))
        for h in P.scripts:
            pass
        # belső hivatkozások
        bad = []
        for href in P.links:
            if re.match(r"(https?:|mailto:|tel:|javascript:)", href):
                continue
            if href in ("#",):
                bad.append("üres horgony: #")
                continue
            tgt, frag = exists_target(href, base)
            if tgt is None and href.startswith("#"):
                tgt = path
            if tgt is None:
                bad.append("nincs fájl: " + href)
                continue
            if frag and tgt.endswith(".html"):
                if frag not in ids_of(tgt):
                    bad.append("nincs horgony: " + href)
        check(not bad, "%s: minden belső hivatkozás létező fájlra és horgonyra mutat %s" % (name, bad[:3]))
        if root_page:
            data = set(re.findall(r'["\'](demo-[a-z-]+\.json)["\']', raw))
            nodata = [d for d in data if not os.path.exists(os.path.join(ROOT, d))]
            check(not nodata, "%s: a hivatkozott demo-adatfájlok léteznek %s" % (name, nodata))
        text = html.unescape(" ".join(P.text)).lower()
        check(not [w for w in BAD_WORDS if w in text], "%s: nincs hibás szóhasználat („áram” az energia helyett)" % name)
        check("javascript:" not in raw, "%s: nincs javascript: hivatkozás" % name)

    print("[Rendszerkép szekciók]")
    P = parse(os.path.join(ROOT, "rendszerkep.html"))
    letters = [c for c in "ABCDEFG"]
    check(all("sz" + c in P.ids and "k" + c in P.ids for c in letters), "az A–G szekciók és mutatósoraik megvannak")
    jumps = [l for l in P.links if l.startswith("#sz")]
    check(sorted(jumps) == sorted("#sz" + c for c in letters), "hét ugrólink, mind az A–G szekcióra mutat %s" % jumps)

    print("[Menü: három főmenüpont, az Adatok alatt modulsor]")
    js = open(os.path.join(ROOT, "assets", "gf.js"), encoding="utf-8").read()
    hrefs = [h for h, _ in re.findall(r'href: "([a-z]+\.html)", t: "([^"]+)"', js)]
    check(hrefs[:3] == MENU, "a gf.js főmenüje a három várt pontot tartalmazza %s" % hrefs[:3])
    check(hrefs[3:10] == DATA, "az Adatok modulsora hét modult tartalmaz %s" % hrefs[3:10])
    check(hrefs[10:] == SUB, "az aktuális rendszerkép nézetei négy oldal %s" % hrefs[10:])
    check(all(os.path.exists(os.path.join(ROOT, h)) for h in hrefs), "a menü minden pontja létező oldalra mutat")

    print("\n%s" % ("MINDEN OK" if not FAIL else "%d HIBA:\n  - " % len(FAIL) + "\n  - ".join(FAIL)))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
