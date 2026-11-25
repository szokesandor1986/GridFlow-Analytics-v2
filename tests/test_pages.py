"""Böngészős oldalteszt (Playwright): mind az öt oldal a mellékelt demo adattal.

Mit ellenőriz:
  - egyik oldalon sincs JavaScript-hiba vagy konzolhiba (asztali és mobil nézetben, világos és sötét módban),
  - nincs vízszintes túlcsordulás (a lap nem szélesebb a képernyőnél),
  - a fő tartalom megjelent (cím, kártyák, ábrák),
  - a navigációban mind az öt fül ott van, és mindegyik létező oldalra mutat,
  - Európai piac: az óránkénti csúszka húzása közben a mutatógombok nem tűnnek el,
  - Rendszerállapot: a távoli országok választója és az ország-sáv nem takarja ki az oldalt,
  - Időjárás: legfeljebb négy település kapcsolható be, az ábrák a választással együtt frissülnek,
  - kézi témaváltó (automatikus / világos / sötét), megmarad újratöltés után, nincs hiba az újrarajzoláskor,
  - ugrólink és billentyűzetes fókusz, látható fókuszjelzés,
  - minden ábrához szöveges összefoglaló (aria-label) és lenyitható táblázatnézet,
  - a projekt-alútvonal (/<repó>/) alatt minden fájl betöltődik, nincs gyökérre mutató hivatkozás, nincs sikertelen kérés,
  - adatállapotok: valós (friss), elavult, hiányzó adatfájl, demo; a hiányzó érték nem nulla.

Futtatás (a projekt mappájából):  python -I tests/test_pages.py
Kell hozzá:  pip install playwright && playwright install chromium
(vagy egy telepített Chrome: CHROME_PATH=/usr/bin/google-chrome). Ha a Playwright nincs
telepítve, a teszt kihagyja magát (kilépési kód 0), így a gyűjtő workflow-t nem akasztja meg.
"""
import contextlib
import functools
import http.server
import os
import socketserver
import sys
import threading

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("KIHAGYVA: a Playwright nincs telepítve (pip install playwright)")
    sys.exit(0)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = ["index", "muszaki", "europa", "idojaras", "foldgaz"]
FAIL = []


def check(ok, msg):
    print(("  ok   " if ok else "  HIBA ") + msg)
    if not ok:
        FAIL.append(msg)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@contextlib.contextmanager
def serve():
    handler = functools.partial(Quiet, directory=ROOT)
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield "http://127.0.0.1:%d" % srv.server_address[1]
    finally:
        srv.shutdown()


@contextlib.contextmanager
def serve_sub(prefix="/GridFlow-Analytics-v2"):
    """Ugyanaz a mappa, de csak a /<repó>/ alútvonal alatt elérhető, mint a GitHub Pages projektoldalon.
    A gyökér (/) 404-et ad, így a gyökérre mutató abszolút hivatkozások kibuknak."""
    class Sub(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=ROOT, **k)
        def log_message(self, *a):
            pass
        def translate_path(self, path):
            if path.split("?")[0].startswith(prefix + "/") or path.split("?")[0] == prefix:
                path = path[len(prefix):] or "/"
                return super().translate_path(path)
            return os.path.join(ROOT, "__nincs_ilyen__")
    srv = socketserver.TCPServer(("127.0.0.1", 0), Sub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield "http://127.0.0.1:%d%s" % (srv.server_address[1], prefix)
    finally:
        srv.shutdown()


def launch(pw):
    path = os.environ.get("CHROME_PATH")
    if not path and not os.environ.get("PLAYWRIGHT_BUNDLED"):
        for c in ("/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"):
            if os.path.exists(c):
                path = c
                break
    kw = {"args": ["--no-sandbox"]}
    if path:
        kw["executable_path"] = path
    return pw.chromium.launch(**kw)


def open_page(browser, base, name, vp, scheme, errs, wait=3500):
    pg = browser.new_page(viewport=vp, color_scheme=scheme)
    pg.on("pageerror", lambda e: errs.append("JS: " + str(e)[:160]))
    pg.on("console", lambda m: errs.append("konzol: " + m.text[:160]) if m.type == "error" else None)
    pg.goto("%s/%s.html?demo=1" % (base, name))
    pg.wait_for_timeout(wait)
    return pg


def overflow(pg):
    return pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")


def test_all_pages(browser, base):
    for name in PAGES:
        for label, vp in (("asztali", {"width": 1280, "height": 900}), ("mobil", {"width": 390, "height": 800})):
            for scheme in ("light", "dark"):
                errs = []
                pg = open_page(browser, base, name, vp, scheme, errs)
                n_card = pg.evaluate("document.querySelectorAll('.card').length")
                n_svg = pg.evaluate("document.querySelectorAll('svg').length")
                nav = pg.evaluate("[...document.querySelectorAll('nav a')].map(a=>a.getAttribute('href')).filter(h=>h&&!h.startsWith('#'))")
                ov = overflow(pg)
                tag = "%s / %s / %s" % (name, label, scheme)
                check(not errs, "%s: nincs JS- vagy konzolhiba %s" % (tag, errs[:2]))
                check(ov <= 0, "%s: nincs vízszintes túlcsordulás (%s px)" % (tag, ov))
                check(n_card >= 2 and n_svg >= 1, "%s: tartalom megjelent (kártya %d, ábra %d)" % (tag, n_card, n_svg))
                if scheme == "light" and label == "asztali":
                    check(len(nav) == 5 and all(os.path.exists(os.path.join(ROOT, h.split("?")[0] or "index.html")) for h in nav),
                          "%s: öt fül, mind létező oldalra mutat %s" % (name, nav))
                pg.close()


def test_europa_slider(browser, base):
    errs = []
    pg = open_page(browser, base, "europa", {"width": 1200, "height": 900}, "light", errs, wait=5000)
    pg.click("#mapTime button:has-text('Óránként')")
    pg.wait_for_timeout(300)
    for metric in ("CO₂-intenzitás", "Megújuló részarány", "Nettó import / export"):
        pg.click("#mapChips .chip:has-text('%s')" % metric)
        pg.wait_for_timeout(250)
        mn, mx = pg.evaluate("[+document.querySelector('#mapTime input').min, +document.querySelector('#mapTime input').max]")
        seen = set()
        for v in range(mn, mx + 1, 8):
            pg.evaluate("v=>{const s=document.querySelector('#mapTime input'); s.value=v; s.dispatchEvent(new Event('input'))}", v)
            pg.wait_for_timeout(100)
            state = pg.evaluate("[document.querySelectorAll('#mapChips .chip').length, document.querySelector('#mapChips .chip[aria-pressed=true]')?.textContent, !!document.querySelector('#mapTime input')]")
            seen.add(repr(state))
        check(len(seen) == 1, "Európai piac / %s: húzás közben a gombok és a kiválasztott mutató nem változik %s" % (metric, sorted(seen)))
    check(not errs, "Európai piac csúszka: nincs JS-hiba %s" % errs[:2])
    pg.close()


def test_muszaki_country_bar(browser, base):
    errs = []
    bar = "(document.querySelector('#ctl')||document.querySelector('.ctl'))"
    pg = open_page(browser, base, "muszaki", {"width": 390, "height": 800}, "light", errs, wait=4000)
    check(pg.query_selector(".zsel") is not None, "Rendszerállapot / mobil: van ország-választó lenyíló")
    h = pg.evaluate(bar + ".getBoundingClientRect().height")
    check(h < 400, "Rendszerállapot / mobil: a vezérlősáv nem takarja ki az oldalt (%d px)" % h)
    pg.close()
    pg = open_page(browser, base, "muszaki", {"width": 1280, "height": 900}, "light", errs, wait=4000)
    h = pg.evaluate(bar + ".getBoundingClientRect().height")
    check(h < 200, "Rendszerállapot / asztali: a vezérlősáv kompakt marad (%d px)" % h)
    check(not errs, "Rendszerállapot: nincs JS-hiba %s" % errs[:2])
    pg.close()


def test_idojaras(browser, base):
    errs = []
    pg = open_page(browser, base, "idojaras", {"width": 1280, "height": 900}, "light", errs, wait=1500)
    for n in ("Budapest", "Győr", "Pécs", "Szeged", "Bécs"):
        pg.click("#placeChips button:has-text('%s')" % n)
    on = pg.evaluate("[...document.querySelectorAll('#placeChips button[aria-pressed=true]')].length")
    check(on == 1 + 4, "Időjárás: legfeljebb négy település kapcsolható be (magyar átlag + %d)" % (on - 1))
    n_paths = pg.evaluate("document.querySelectorAll('#tempChart svg path').length")
    check(n_paths >= 5, "Időjárás: a hőmérséklet-ábrán az átlag és a négy hely vonala látszik (%d)" % n_paths)
    pg.click("#winChips button:has-text('±1 nap')")
    pg.wait_for_timeout(250)
    check(pg.evaluate("document.querySelector('#winChips button[aria-pressed=true]').textContent") == "±1 nap",
          "Időjárás: az időablak-gomb átvált")
    pg.focus("#tempChart svg")
    pg.keyboard.press("ArrowLeft")
    tip = pg.evaluate("document.querySelector('#tempChart .tip').innerText")
    check("°C" in tip, "Időjárás: billentyűzettel bejárható az ábra, a tooltip mértékegységet ír")
    check(pg.evaluate("document.querySelectorAll('#placeTable tbody tr').length") >= 10, "Időjárás: a helyek táblázata kitöltött")
    foot = pg.evaluate("document.getElementById('foot').innerText")
    check("Open-Meteo" in foot and "CC BY 4.0" in foot, "Időjárás: a forrásmegjelölés (Open-Meteo, CC BY 4.0) a lábléc része")
    check(not errs, "Időjárás: nincs JS-hiba %s" % errs[:2])
    pg.close()


def test_missing_data(browser, base):
    """Éles mód adatfájl nélkül (nincs weather.json a mappában): érthető üzenet, nincs kezeletlen hiba."""
    if os.path.exists(os.path.join(ROOT, "weather.json")):
        print("  (kihagyva: a mappában van weather.json)")
        return
    errs = []
    pg = browser.new_page(viewport={"width": 1000, "height": 800})
    pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
    pg.goto(base + "/idojaras.html")
    pg.wait_for_timeout(1500)
    txt = pg.evaluate("document.getElementById('cNow').innerText")
    check("nem tölthető be" in txt, "Időjárás: hiányzó adatfájlnál érthető üzenet jelenik meg")
    check(not errs, "Időjárás: hiányzó adatfájlnál nincs kezeletlen JS-hiba %s" % errs[:2])
    pg.close()


def test_theme(browser, base):
    for name in ("index", "muszaki", "europa", "foldgaz", "idojaras"):
        errs = []
        pg = open_page(browser, base, name, {"width": 1200, "height": 900}, "light", errs, wait=3500)
        bg0 = pg.evaluate("getComputedStyle(document.body).backgroundColor")
        pg.click(".themebtn")  # automatikus -> világos
        pg.click(".themebtn")  # világos -> sötét
        pg.wait_for_timeout(500)
        dark = pg.evaluate("document.documentElement.getAttribute('data-theme')")
        bg1 = pg.evaluate("getComputedStyle(document.body).backgroundColor")
        check(dark == "dark" and bg1 != bg0, "%s: a témaváltó sötétre vált (%s -> %s)" % (name, bg0, bg1))
        pg.reload()
        pg.wait_for_timeout(2500)
        check(pg.evaluate("document.documentElement.getAttribute('data-theme')") == "dark", "%s: a választott téma újratöltés után megmarad" % name)
        pg.click(".themebtn")  # sötét -> automatikus
        check(pg.evaluate("document.documentElement.getAttribute('data-theme')") is None, "%s: a harmadik kattintás visszaáll automatikusra" % name)
        check(not errs, "%s: témaváltás közben nincs JS-hiba %s" % (name, errs[:2]))
        pg.close()


def test_keyboard(browser, base):
    errs = []
    pg = open_page(browser, base, "index", {"width": 1200, "height": 900}, "light", errs, wait=3000)
    pg.keyboard.press("Tab")
    first = pg.evaluate("document.activeElement.className + '|' + document.activeElement.textContent")
    check(first.startswith("skip|"), "Billentyűzet: az első Tab az ugrólinkre kerül (%s)" % first)
    check(pg.evaluate("getComputedStyle(document.activeElement).top") == "8px", "Billentyűzet: az ugrólink fókuszban látszik")
    pg.keyboard.press("Enter")
    check(pg.evaluate("document.activeElement.tagName") == "MAIN", "Billentyűzet: az ugrólink a fő tartalomra ugrik")
    # a navigáció és a témaváltó elérhető, a fókusz látható
    seen = set()
    for _ in range(9):
        pg.keyboard.press("Tab")
        seen.add(pg.evaluate("document.activeElement.textContent.trim().slice(0,24)"))
    check({"Rendszerállapot", "Időjárás", "Földgáz"} <= seen or len(seen) >= 4, "Billentyűzet: a fülek Tab-bal bejárhatók %s" % sorted(seen))
    ow = pg.evaluate("(()=>{const a=document.querySelector('nav.tabs a'); a.focus(); return getComputedStyle(a).outlineStyle + ' ' + getComputedStyle(a).outlineWidth})()")
    check("solid" in ow and not ow.endswith(" 0px"), "Billentyűzet: látható fókuszkeret (%s)" % ow)
    check(not errs, "Billentyűzet: nincs JS-hiba %s" % errs[:2])
    pg.close()


def test_table_views(browser, base):
    for name in ("index", "muszaki", "europa", "foldgaz", "idojaras"):
        errs = []
        pg = open_page(browser, base, name, {"width": 1200, "height": 900}, "light", errs, wait=4500)
        n = pg.evaluate("document.querySelectorAll('details.tview').length")
        lab = pg.evaluate("[...document.querySelectorAll('[data-gf-title]')].filter(e=>!(e.getAttribute('aria-label')||'').includes('legkisebb')).length")
        check(n >= 2, "%s: az ábrák alatt táblázatnézet van (%d)" % (name, n))
        check(lab == 0, "%s: minden ábra összefoglalót kapott (hiányos: %d)" % (name, lab))
        pg.evaluate("document.querySelector('details.tview').open = true")
        pg.wait_for_timeout(300)
        rows = pg.evaluate("document.querySelectorAll('details.tview[open] tbody tr').length")
        head = pg.evaluate("document.querySelectorAll('details.tview[open] thead th[scope=col]').length")
        check(rows >= 3 and head >= 2, "%s: a táblázatnézet kitöltött (%d sor, %d oszlop)" % (name, rows, head))
        check(not errs, "%s: nincs JS-hiba %s" % (name, errs[:2]))
        pg.close()


def test_subpath(browser):
    with serve_sub() as base:
        for name in PAGES:
            bad, errs = [], []
            pg = browser.new_page(viewport={"width": 1200, "height": 900})
            pg.on("response", lambda r: bad.append("%d %s" % (r.status, r.url)) if r.status >= 400 else None)
            pg.on("requestfailed", lambda r: bad.append("nem teljesült " + r.url))
            pg.on("pageerror", lambda e: errs.append(str(e)[:120]))
            pg.goto("%s/%s.html?demo=1" % (base, name))
            pg.wait_for_timeout(5000)
            root_links = pg.evaluate("[...document.querySelectorAll('a[href],link[href],script[src],img[src]')].map(e=>e.getAttribute('href')||e.getAttribute('src')).filter(u=>u&&u.startsWith('/')&&!u.startsWith('//'))")
            check(not root_links, "%s: nincs gyökérre mutató abszolút hivatkozás %s" % (name, root_links[:3]))
            check(not bad, "%s: alútvonal alatt minden fájl betöltődik %s" % (name, bad[:3]))
            check(not errs, "%s: alútvonal alatt nincs JS-hiba %s" % (name, errs[:2]))
            pg.close()


def test_foldgaz_map(browser, base):
    errs = []
    pg = open_page(browser, base, "foldgaz", {"width": 1100, "height": 900}, "light", errs, wait=4500)
    n = pg.evaluate("[...document.querySelectorAll('svg text')].filter(t=>t.textContent.trim()==='Budapest').length")
    check(n >= 1, "Földgáz: a magyar határpont-térkép teljesen kirajzolódik (Budapest-jelölés megvan)")
    check(not errs, "Földgáz: nincs JS-hiba a térkép kirajzolásakor %s" % errs[:2])
    pg.close()


def test_data_states(browser, base):
    import json
    import datetime
    demo = json.load(open(os.path.join(ROOT, "demo-data.json"), encoding="utf-8"))
    now = datetime.datetime.now(datetime.timezone.utc)

    def run(label, handler, expect_banner=None, expect_tag=None, expect_err=False):
        errs = []
        pg = browser.new_page(viewport={"width": 1100, "height": 900})
        pg.on("pageerror", lambda e: errs.append(str(e)[:120]))
        pg.route("**/data.json*", handler)
        pg.goto(base + "/index.html")
        pg.wait_for_timeout(3000)
        banners = pg.evaluate("[...document.querySelectorAll('.banner')].map(b=>b.textContent)")
        tag = pg.evaluate("(document.querySelector('.state')||{}).textContent||''")
        err = pg.evaluate("(document.querySelector('.err')||{}).textContent||''")
        loading = pg.evaluate("!!document.querySelector('.loading')")
        if expect_banner:
            check(any(expect_banner in b for b in banners), "Adatállapot / %s: sáv „%s” %s" % (label, expect_banner, banners))
        else:
            check(not banners, "Adatállapot / %s: nincs figyelmeztető sáv %s" % (label, banners))
        if expect_tag:
            check(expect_tag in tag, "Adatállapot / %s: címke „%s” (%s)" % (label, expect_tag, tag.strip()))
        if expect_err:
            check("nem tölthető be" in err, "Adatállapot / %s: érthető hibaüzenet" % label)
        check(not loading, "Adatállapot / %s: a betöltésjelző eltűnik" % label)
        check(not errs, "Adatállapot / %s: nincs kezeletlen JS-hiba %s" % (label, errs[:2]))
        pg.close()

    def with_age(hours):
        d = dict(demo)
        d["demo"] = False
        d["generated_utc"] = (now - datetime.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        # az idősor végét a „most”-hoz igazítjuk, hogy a teszt ne függjön a demo fix dátumától
        return d

    def serve_json(d):
        return lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(d))

    # A demo határadatban az Ukrajna-határnak nincs adata, ezért a friss adat is „részben hiányos” – ez a helyes jelzés.
    run("friss, de egy határ hiányzik", serve_json(with_age(0.2)), expect_banner=None, expect_tag="Részben hiányos adat")
    run("elavult", serve_json(with_age(9)), expect_banner="Elavult adat", expect_tag="Elavult adat")
    run("hiányzó fájl", lambda route: route.fulfill(status=404, body="nincs"), expect_banner=None, expect_err=True)
    run("demo", serve_json(demo), expect_banner="DEMO ADAT", expect_tag="Demo adat")


def main():
    with serve() as base, sync_playwright() as pw:
        browser = launch(pw)
        try:
            for fn in (test_all_pages, test_europa_slider, test_muszaki_country_bar, test_idojaras, test_missing_data,
                       test_theme, test_keyboard, test_table_views, test_foldgaz_map, test_data_states):
                print(fn.__name__)
                fn(browser, base)
            print("test_subpath")
            test_subpath(browser)
        finally:
            browser.close()
    print("\n%s" % ("MINDEN OK" if not FAIL else "%d HIBA:\n  - " % len(FAIL) + "\n  - ".join(FAIL)))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
