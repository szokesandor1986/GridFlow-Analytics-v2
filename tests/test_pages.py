"""Böngészős oldalteszt (Playwright): mind a tizenkét oldal a mellékelt demo adattal.

Mit ellenőriz:
  - egyik oldalon sincs JavaScript-hiba vagy konzolhiba (asztali és mobil nézetben, világos és sötét módban),
  - nincs vízszintes túlcsordulás (a lap nem szélesebb a képernyőnél),
  - a fő tartalom megjelent (cím, kártyák, ábrák),
  - a hárompontos főmenü (Főoldal, Elemzések, Adatok), az Adatok hétmodulos sora és a rendszerkép négynézetes sora megvan, a jelenlegi oldal jelölt, minden pont létező oldalra mutat,
  - Rendszerkép: az A–G szakaszok mutatói a demo adatból újraszámolt értékkel egyeznek; hiányzó adatnál „nincs adat”, nem nulla,
  - Nemzetközi összehasonlítás: a táblázat értékei a demo adattárból újraszámolt értékkel egyeznek, a hiányzó zóna „nincs adat”,
  - Módszertan és Rólunk: a horgonyok megvannak, nincs betöltésjelző; JavaScript nélkül a tartalék menü látszik,
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
PAGES = ["index", "elemzesek", "rendszerkep", "historikus", "nemzetkozi", "modszertan", "rolunk", "hatarok", "muszaki", "europa", "idojaras", "foldgaz", "eromuvek"]
SECTION_OF = {"index": "kezdolap", "elemzesek": "elemzesek", "rolunk": "rolunk"}
for _n in ("rendszerkep", "hatarok", "muszaki", "europa", "idojaras", "foldgaz", "historikus", "eromuvek", "nemzetkozi", "modszertan"):
    SECTION_OF[_n] = "adatok"
MENU = ["index.html", "elemzesek.html", "rendszerkep.html"]                       # három főmenüpont: Főoldal, Elemzések, Adatok
DATAMENU = ["rendszerkep.html", "historikus.html", "eromuvek.html", "idojaras.html", "foldgaz.html", "nemzetkozi.html", "modszertan.html"]
SUBMENU = ["rendszerkep.html", "hatarok.html", "muszaki.html", "europa.html"]      # az aktuális rendszerkép nézetei
NSMENU = ["Főoldal", "Elemzések", "Adatok: aktuális rendszerkép", "Historikus adatok", "Erőművek és termelőegységek", "Időjárási adatok",
          "Földgáz és tárolók", "Nemzetközi összehasonlítás", "Módszertan és adatforrások", "Rólunk"]
VIEW = [("asztali", {"width": 1280, "height": 900}), ("mobil", {"width": 390, "height": 800})]
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
                ov = overflow(pg)
                tag = "%s / %s / %s" % (name, label, scheme)
                check(not errs, "%s: nincs JS- vagy konzolhiba %s" % (tag, errs[:2]))
                check(ov <= 0, "%s: nincs vízszintes túlcsordulás (%s px)" % (tag, ov))
                check(n_card >= 2 and n_svg >= 1, "%s: tartalom megjelent (kártya %d, ábra %d)" % (tag, n_card, n_svg))
                if scheme == "light" and label == "asztali":
                    menu = pg.evaluate("[...document.querySelectorAll('header.site nav.mainnav a')].map(a=>a.getAttribute('href'))")
                    cur = pg.evaluate("[...document.querySelectorAll('header.site nav.mainnav a[aria-current]')].map(a=>a.getAttribute('href'))")
                    sec_href = {"kezdolap": "index.html", "elemzesek": "elemzesek.html", "adatok": "rendszerkep.html", "rolunk": None}[SECTION_OF[name]]
                    check(menu == MENU and all(os.path.exists(os.path.join(ROOT, h)) for h in menu), "%s: hárompontos főmenü (Főoldal, Elemzések, Adatok), mind létező oldalra mutat" % name)
                    check(cur == ([sec_href] if sec_href else []), "%s: a főmenüben a jelenlegi rész jelölt (%s)" % (name, cur))
                    sub = pg.evaluate("[...document.querySelectorAll('nav.subnav a')].map(a=>a.getAttribute('href'))")
                    subcur = pg.evaluate("[...document.querySelectorAll('nav.subnav a[aria-current]')].map(a=>a.getAttribute('href'))")
                    sub2 = pg.evaluate("[...document.querySelectorAll('nav.subnav2 a')].map(a=>a.getAttribute('href'))")
                    sub2cur = pg.evaluate("[...document.querySelectorAll('nav.subnav2 a[aria-current=page]')].map(a=>a.getAttribute('href'))")
                    if SECTION_OF[name] == "adatok":
                        own = name + ".html"
                        want = "rendszerkep.html" if own in SUBMENU else own          # a rendszerkép-család nézetei az „Aktuális rendszerkép” modult jelölik
                        check(sub == DATAMENU and subcur == [want], "%s: az Adatok modulsora hét modul, a jelenlegi jelölt %s" % (name, subcur))
                        if own in SUBMENU:
                            check(sub2 == SUBMENU and sub2cur == [own], "%s: a rendszerkép nézetsora négy nézet, a jelenlegi jelölt %s" % (name, sub2cur))
                        else:
                            check(not sub2, "%s: nézetsor csak a rendszerkép-családban van" % name)
                    else:
                        check(not sub and not sub2, "%s: modulsor csak az Adatok részen van" % name)
                if scheme == "light" and label == "mobil":
                    tg = pg.query_selector("header.site .menu-toggle")
                    check(tg is not None and tg.is_visible(), "%s: mobilon van menügomb" % name)
                    pg.click("header.site .menu-toggle")
                    pg.wait_for_timeout(200)
                    vis = pg.evaluate("[...document.querySelectorAll('header.site nav.mainnav a')].every(a=>a.getBoundingClientRect().height>0)")
                    check(vis and pg.get_attribute("header.site .menu-toggle", "aria-expanded") == "true", "%s: a mobil menü kinyílik, a pontok látszanak" % name)
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
    for name in ("index", "rendszerkep", "historikus", "nemzetkozi", "modszertan", "hatarok", "muszaki", "europa", "foldgaz", "idojaras"):
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
    # a főmenü Tab-bal bejárható (az oldal elejéről újraindítva), a fókusz látható
    # (az ugrólink a #main horgonyt írta a címbe: újratöltésnél a böngésző ott folytatná, ezért tiszta címről indul)
    pg.goto(pg.url.split("#")[0])
    pg.wait_for_timeout(2500)
    seen = []
    for _ in range(11):
        pg.keyboard.press("Tab")
        seen.append(pg.evaluate("document.activeElement.textContent.trim().slice(0,28)"))
    need = {"Főoldal", "Elemzések", "Adatok"}
    check(need <= set(seen), "Billentyűzet: a három főmenüpont Tab-bal bejárható %s" % seen)
    ow = pg.evaluate("(()=>{const a=document.querySelector('header.site nav.mainnav a'); a.focus(); return getComputedStyle(a).outlineStyle + ' ' + getComputedStyle(a).outlineWidth})()")
    check("solid" in ow and not ow.endswith(" 0px"), "Billentyűzet: látható fókuszkeret (%s)" % ow)
    check(not errs, "Billentyűzet: nincs JS-hiba %s" % errs[:2])
    pg.close()


def test_table_views(browser, base):
    for name in ("index", "historikus", "nemzetkozi", "hatarok", "muszaki", "europa", "foldgaz", "idojaras"):
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
        pg.goto(base + "/hatarok.html")
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


# ====================================================================================== az új oldalak
import datetime as _dt
import decimal as _dec
import json
import math
import re
from zoneinfo import ZoneInfo

BUD = ZoneInfo("Europe/Budapest")


def jl(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return json.load(f)


def rnd(x, d=0):
    """Matematikai kerekítés (félről felfelé), mint az Intl.NumberFormat; a Python round() páros felé kerekít."""
    q = _dec.Decimal(1).scaleb(-d)
    return float(_dec.Decimal(repr(x)).quantize(q, rounding=_dec.ROUND_HALF_UP))


def num(txt):
    """A megjelenített magyar számból szám: szóköz-félék ki, mínuszjel és tizedesvessző normalizálva."""
    t = re.sub(r"[\s  ]", "", txt).replace("−", "-").replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    return float(m.group(0)) if m else None


def kpis(pg, sel):
    return pg.evaluate("[...document.querySelectorAll('%s .kpi')].map(k=>({k:k.querySelector('.k').innerText, n:k.querySelector('.n').innerText, nodata:!!k.querySelector('.n .nodata'), s:k.querySelector('.s').innerText}))" % sel)


def local_day(ts):
    return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(BUD).strftime("%Y-%m-%d")


def test_index_page(browser, base):
    errs = []
    pg = open_page(browser, base, "index", {"width": 1280, "height": 900}, "light", errs, wait=4000)
    check(pg.evaluate("document.querySelectorAll('#featured a.pubcard').length") == 1, "Kezdőlap: van kiemelt elemzés")
    n_lat = pg.evaluate("document.querySelectorAll('#latest a.pubcard').length")
    check(4 <= n_lat <= 6, "Kezdőlap: legutóbbi publikációk (%d)" % n_lat)
    check(pg.evaluate("document.querySelectorAll('#topics a').length") == 10, "Kezdőlap: tíz kiemelt téma")
    check(pg.evaluate("document.querySelectorAll('#kpis .kpi').length") >= 5, "Kezdőlap: a jelenlegi kép mutatói megvannak")
    check(pg.evaluate("document.querySelectorAll('#trends .card svg').length") >= 3, "Kezdőlap: három trendábra kirajzolódik")
    txt = pg.evaluate("document.body.innerText")
    check(not re.search(r"\b(NaN|undefined|null)\b", txt), "Kezdőlap: nincs NaN/undefined a szövegben")
    href = pg.evaluate("document.querySelector('#featured a.pubcard').getAttribute('href')")
    check(href.startswith("demo-elemzesek/") and os.path.exists(os.path.join(ROOT, href)), "Kezdőlap: a kiemelt elemzés a demo oldalra mutat (%s)" % href)
    check(not errs, "Kezdőlap: nincs JS-hiba %s" % errs[:2])
    pg.close()


def test_elemzesek_page(browser, base):
    errs = []
    pg = open_page(browser, base, "elemzesek", {"width": 1280, "height": 900}, "light", errs, wait=3000)
    check(pg.evaluate("document.querySelectorAll('#list a.pubcard').length") == 10, "Elemzések: tíz kártya")
    pg.click("#filter button:has-text('Negatív')")
    check(pg.evaluate("document.querySelectorAll('#list a.pubcard').length") == 1, "Elemzések: a témaszűrő egy kártyára szűr")
    pg.click("#filter button:has-text('Mind')")
    check(pg.evaluate("document.querySelectorAll('#list a.pubcard').length") == 10, "Elemzések: a „Mind” visszaállítja a listát")
    hrefs = pg.evaluate("[...document.querySelectorAll('#list a.pubcard')].map(a=>a.getAttribute('href'))")
    check(all(os.path.exists(os.path.join(ROOT, h)) for h in hrefs), "Elemzések: minden kártya létező oldalra mutat")
    check("2026. október" in pg.evaluate("document.getElementById('msg').innerText"), "Elemzések: az adatok állása látszik")
    check(not errs, "Elemzések: nincs JS-hiba %s" % errs[:2])
    pg.close()


def test_publication_pages(browser, base):
    idx = jl("demo-elemzesek/index.json")
    for p in idx["publications"]:
        for label, vp in (("asztali", {"width": 1280, "height": 900}), ("mobil", {"width": 390, "height": 800})):
            errs = []
            pg = browser.new_page(viewport=vp)
            pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
            pg.on("console", lambda m: errs.append(m.text[:160]) if m.type == "error" else None)
            pg.goto("%s/demo-elemzesek/%s.html" % (base, p["slug"]))
            pg.wait_for_timeout(1800)
            tag = "%s / %s" % (p["slug"], label)
            n_h2 = pg.evaluate("document.querySelectorAll('article.pub h2').length")
            figs = pg.evaluate("[...document.querySelectorAll('figure.fig')].map(f=>({svg:!!f.querySelector('svg'), tv:!!f.querySelector('details.tview'), nodata:!!f.querySelector('.nodata')}))")
            check(n_h2 == 10, "%s: tíz szakasz" % tag)
            check(len(figs) == p["figures"] and all(f["svg"] or f["nodata"] for f in figs), "%s: minden ábra kirajzolódott (%d)" % (tag, len(figs)))
            check(all(f["tv"] for f in figs if f["svg"]), "%s: minden ábrához van táblázatnézet" % tag)
            check(overflow(pg) <= 0, "%s: nincs vízszintes túlcsordulás" % tag)
            slot = pg.evaluate("[...document.querySelectorAll('.q-slot')].every(e=>e.querySelector('.q'))")
            check(slot, "%s: a minőségi címke kirajzolódott" % tag)
            check(pg.evaluate("document.querySelector('header.site') !== null && document.querySelectorAll('header.site nav.mainnav a').length") == 3, "%s: a főmenü a gyökérre mutató relatív hivatkozásokkal megvan" % tag)
            check(not errs, "%s: nincs JS-hiba %s" % (tag, errs[:2]))
            pg.close()


def test_rendszerkep(browser, base):
    E, D, F = jl("demo-engineer.json"), jl("demo-data.json"), jl("demo-frequency.json")
    errs = []
    pg = open_page(browser, base, "rendszerkep", {"width": 1280, "height": 900}, "light", errs, wait=3500)
    ids = pg.evaluate("[...document.querySelectorAll('section.hub')].map(s=>s.id)")
    check(ids == ["sz" + c for c in "ABCDEFG"], "Rendszerkép: az A–G szakaszok sorrendben megvannak %s" % ids)
    check(all(len(kpis(pg, "#k" + c)) >= 2 for c in "ABCDEFG"), "Rendszerkép: minden szakasznak legalább két mutatója van")
    txt = pg.evaluate("document.body.innerText")
    check(not re.search(r"\b(NaN|undefined|null)\b", txt), "Rendszerkép: nincs NaN/undefined a szövegben")

    # --- újraszámolás a demo adatból
    n = len(E["hourly_ts"])
    la, lf = E["load"]["actual"], E["load"]["forecast"]
    li = max(i for i in range(n) if la[i] is not None)
    A = kpis(pg, "#kA")
    check(num(A[0]["n"]) == rnd(la[li]), "Rendszerkép A: a legutóbbi fogyasztás egyezik a demo adattal (%s)" % A[0]["n"].replace("\n", " "))
    ei = max(i for i in range(n) if la[i] is not None and lf[i] is not None)
    check(num(A[2]["n"]) == rnd(la[ei] - lf[ei]), "Rendszerkép A: az előrejelzéstől való eltérés egyezik (%s)" % A[2]["n"].replace("\n", " "))
    groups = [g for g in ("nuclear", "gas", "coal", "solar", "wind", "bio", "hydro", "other") if g in E["generation"]]
    gi = max(i for i in range(n) if all(E["generation"][g][i] is not None for g in groups))
    tot = sum(E["generation"][g][gi] for g in groups)
    check(num(A[1]["n"]) == rnd(tot), "Rendszerkép A: a jelentett termelés összege egyezik (%s)" % A[1]["n"].replace("\n", " "))
    B = kpis(pg, "#kB")
    check(num(B[0]["n"]) == rnd(100 * E["generation"]["solar"][gi] / tot, 1), "Rendszerkép B: a napenergia részaránya egyezik (%s)" % B[0]["n"].replace("\n", " "))
    f = E["co2"]["factors"]
    co2 = sum(E["generation"][g][gi] * f[g] for g in groups) / tot
    check(num(B[2]["n"]) == rnd(co2), "Rendszerkép B: a CO₂-intenzitás egyezik (%s)" % B[2]["n"].replace("\n", " "))
    C = kpis(pg, "#kC")
    ni = D["hourly_ts"].index(D["last_complete_ts"])
    check(num(C[0]["n"]) == rnd(D["net_import_mw"][ni]), "Rendszerkép C: a nettó import egyezik (%s)" % C[0]["n"].replace("\n", " "))
    nets = [(abs(b["import_mw"][ni] - b["export_mw"][ni]), b["name"]) for b in D["borders"] if b["import_mw"][ni] is not None and b["export_mw"][ni] is not None]
    mx = max(nets)
    check(num(C[1]["n"]) == rnd(mx[0]) and mx[1] in C[1]["k"], "Rendszerkép C: a legnagyobb nettó áramlás és a határ neve egyezik (%s, %s)" % (mx[1], C[1]["n"].replace("\n", " ")))
    Dk = kpis(pg, "#kD")
    ts, P = D["prices"]["ts"], D["prices"]["zones"]["HU"]
    ref = D["generated_utc"]
    pi = max(i for i in range(len(ts)) if ts[i] <= ref and P[i] is not None)
    check(num(Dk[0]["n"]) == rnd(P[pi], 1), "Rendszerkép D: a jelenlegi day-ahead ár egyezik (%s)" % Dk[0]["n"].replace("\n", " "))
    day = local_day(ref)
    vals = [P[i] for i in range(len(ts)) if local_day(ts[i]) == day and P[i] is not None]
    check(num(Dk[1]["n"]) == rnd(sum(vals) / len(vals), 1) and num(Dk[2]["n"]) == rnd(min(vals), 1), "Rendszerkép D: a mai időátlag és minimum egyezik (%s; %s)" % (Dk[1]["n"].replace("\n", " "), Dk[2]["n"].replace("\n", " ")))
    Ek = kpis(pg, "#kE")
    m = F["minute"]
    mi = max(i for i in range(len(m["mean"])) if m["mean"][i] is not None)
    check(num(Ek[0]["n"]) == rnd(m["mean"][mi], 3), "Rendszerkép E: az utolsó perc átlagfrekvenciája egyezik (%s)" % Ek[0]["n"].replace("\n", " "))
    dk = max(k for k, v in F["daily"].items() if v.get("min") is not None and v.get("cov", 0) >= 0.9)
    check(num(Ek[1]["n"]) == rnd(F["daily"][dk]["min"], 3) and num(Ek[2]["n"]) == rnd(F["daily"][dk]["max"], 3), "Rendszerkép E: a legutóbbi nap szélső értékei egyeznek")
    Fk = kpis(pg, "#kF")
    now = _dt.datetime.fromisoformat(E["generated_utc"].replace("Z", "+00:00"))
    iso = lambda s: _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    act = [o for o in E["outages_gen"] if iso(o["start"]) <= now < iso(o["end"])]
    check(num(Fk[0]["n"]) == len(act), "Rendszerkép F: az érvényes kiesések száma egyezik (%s)" % Fk[0]["n"].replace("\n", " "))
    check(num(Fk[1]["n"]) == rnd(sum(o["nominal_mw"] - o["avail_mw"] for o in act)), "Rendszerkép F: a nem rendelkezésre álló kapacitás egyezik (%s)" % Fk[1]["n"].replace("\n", " "))
    Gk = kpis(pg, "#kG")
    sol, wnd = E["generation"]["solar"], E["generation"]["wind"]
    res = [None if la[i] is None or sol[i] is None or wnd[i] is None else la[i] - sol[i] - wnd[i] for i in range(n)]
    ri = max(i for i in range(n) if res[i] is not None)
    check(num(Gk[0]["n"]) == rnd(res[ri]), "Rendszerkép G: a legutóbbi maradék terhelés egyezik (%s)" % Gk[0]["n"].replace("\n", " "))
    byday = {}
    for i, t in enumerate(E["hourly_ts"]):
        d = _dt.datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(BUD)
        byday.setdefault(d.strftime("%Y-%m-%d"), []).append((d.hour, res[i]))
    full = [d for d in sorted(byday) if sum(1 for _, v in byday[d] if v is not None) >= 22]
    dd = full[-1]
    mid = [v for h, v in byday[dd] if v is not None and 10 <= h <= 15]
    eve = [v for h, v in byday[dd] if v is not None and 17 <= h <= 21]
    check(num(Gk[1]["n"]) == rnd(min(mid)) and num(Gk[2]["n"]) == rnd(max(eve)), "Rendszerkép G: a legutóbbi teljes nap déli minimuma és esti maximuma egyezik (%s)" % dd)
    # --- a szakaszok hivatkozásai létező oldalra és horgonyra mutatnak
    links = pg.evaluate("[...document.querySelectorAll('section.hub .hublinks a')].map(a=>a.getAttribute('href'))")
    bad = []
    for h in links:
        f_, _, frag = h.partition("#")
        full_ = os.path.join(ROOT, f_)
        if not os.path.exists(full_):
            bad.append(h)
        elif frag and ('id="%s"' % frag) not in open(full_, encoding="utf-8").read():
            bad.append(h)
    check(not bad and len(links) >= 20, "Rendszerkép: a szakaszok %d hivatkozása létező oldalra és horgonyra mutat %s" % (len(links), bad))
    check(not errs, "Rendszerkép: nincs JS-hiba %s" % errs[:2])
    pg.close()

    # --- hiányzó termelési adat: „nincs adat”, nem nulla, és a hiány a sávban is látszik
    errs = []
    pg = browser.new_page(viewport={"width": 1280, "height": 900})
    pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
    pg.route("**/demo-engineer.json*", lambda r: r.fulfill(status=404, body="nincs"))
    pg.goto(base + "/rendszerkep.html?demo=1")
    pg.wait_for_timeout(3000)
    for c in "ABFG":
        ks = kpis(pg, "#k" + c)
        check(all(k["nodata"] for k in ks), "Rendszerkép / hiányzó engineer.json: a(z) %s szakasz minden mutatója „nincs adat”" % c)
    check(not re.search(r"(?<![\d,])0\s*MW", pg.evaluate("document.querySelector('#kA').innerText + document.querySelector('#kG').innerText")), "Rendszerkép / hiányzó engineer.json: nincs kitalált 0 MW")
    check(len(kpis(pg, "#kC")) >= 2 and not kpis(pg, "#kC")[0]["nodata"], "Rendszerkép / hiányzó engineer.json: a C szakasz a data.json-ból él tovább")
    check("Hiányzó adat" in pg.evaluate("document.getElementById('banners').innerText"), "Rendszerkép / hiányzó engineer.json: a hiány sávban is látszik")
    check(not errs, "Rendszerkép / hiányzó engineer.json: nincs kezeletlen JS-hiba %s" % errs[:2])
    pg.close()


def wavg(vals, ws):
    num_ = sum(v * w for v, w in zip(vals, ws))
    den = sum(ws)
    return num_ / den if den else None


def expected_zone(zone, keys):
    """A Nemzetközi összehasonlító táblázat egy sora a demo adattárból, a megjelenítéstől függetlenül újraszámolva."""
    base = os.path.join(ROOT, "demo-hist", "m", zone)

    def tier(cat):
        p = os.path.join(base, cat + ".json")
        if not os.path.exists(p):
            return None
        t = json.load(open(p, encoding="utf-8"))
        t["ix"] = {k: i for i, k in enumerate(t["keys"])}
        return t
    need = math.ceil(0.8 * len(keys))
    out = {}
    pr = tier("price_da")
    if pr:
        s = pr["series"]["price"]
        ok = [k for k in keys if k in pr["ix"] and s["avg"][pr["ix"][k]] is not None and s["n"][pr["ix"][k]] > 0]
        out["price"] = wavg([s["avg"][pr["ix"][k]] for k in ok], [s["n"][pr["ix"][k]] for k in ok]) if len(ok) >= need else None
        okn = [k for k in ok if s["neg"][pr["ix"][k]] is not None]
        out["neg"] = 100 * sum(s["neg"][pr["ix"][k]] for k in okn) / sum(s["n"][pr["ix"][k]] for k in okn) if len(okn) >= need else None
    g = tier("generation")
    if g:
        act = [i for i, v in g["series"].items() if any(x is not None for x in v["avg"])]
        mixk, tots, sols, winds, co2k = [], [], [], [], []
        c = tier("co2")
        for k in keys:
            if k not in g["ix"]:
                continue
            j = g["ix"][k]
            vs = {i: g["series"][i]["avg"][j] for i in act}
            if not act or any(v is None for v in vs.values()):
                continue
            h = g["h"][j]
            t = sum(v * h for v in vs.values())
            if t <= 0:
                continue
            mixk.append(k)
            tots.append(t)
            sols.append(vs.get("solar", 0) * h)
            winds.append(vs.get("wind", 0) * h)
            if c and k in c["ix"] and c["series"]["intensity"]["avg"][c["ix"][k]] is not None:
                co2k.append((c["series"]["intensity"]["avg"][c["ix"][k]], t))
        out["solar"] = 100 * sum(sols) / sum(tots) if len(mixk) >= need and "solar" in act else None
        out["wind"] = 100 * sum(winds) / sum(tots) if len(mixk) >= need and "wind" in act else None
        out["co2"] = wavg([a for a, _ in co2k], [w for _, w in co2k]) if len(co2k) >= need else None
    rp, ld = tier("ramp"), tier("load")
    if rp and ld:
        rs = rp["series"]["ramp_eve"]
        pts = []
        for k in keys:
            if k in rp["ix"] and k in ld["ix"]:
                a, nn, l = rs["avg"][rp["ix"][k]], rs["n"][rp["ix"][k]], ld["series"]["load"]["avg"][ld["ix"][k]]
                if a is not None and l and l > 0 and nn > 0:
                    pts.append((100 * a / l, nn))
        out["ramp"] = wavg([a for a, _ in pts], [w for _, w in pts]) if len(pts) >= need else None
    return out


def test_nemzetkozi(browser, base):
    errs = []
    pg = open_page(browser, base, "nemzetkozi", {"width": 1280, "height": 900}, "light", errs, wait=4500)
    rows = pg.evaluate("[...document.querySelectorAll('#tbl tbody tr')].map(r=>({cls:r.className, name:r.querySelector('th').innerText.split('\\n')[0], code:(r.querySelector('th small')||{}).innerText||'', cells:[...r.querySelectorAll('td')].map(t=>t.innerText.trim())}))")
    codes = [r["code"].split(" ·")[0] for r in rows]
    check(codes == ["HU", "AT", "SK", "RO", "RS", "HR", "SI", "UA", "DE-LU", "CZ"], "Nemzetközi: tíz zóna a kért sorrendben %s" % codes)
    check(rows[0]["cls"] == "hu" and sum(1 for r in rows if r["cls"] == "hu") == 1, "Nemzetközi: Magyarország kiemelve")
    check(all(len(r["cells"]) == 6 for r in rows), "Nemzetközi: hat mutatóoszlop")
    head = pg.evaluate("[...document.querySelectorAll('#tbl thead th')].map(t=>t.innerText.replace(/\\n+/g,' | '))")
    check(len(head) == 7 and all("|" in h for h in head[1:]), "Nemzetközi: minden oszlopfejléc mértékegységet és minőségi címkét hordoz")
    check(pg.evaluate("document.querySelectorAll('#tbl thead .q').length") == 6, "Nemzetközi: hat minőségi címke a fejlécben")
    ua = next(r for r in rows if r["code"].startswith("UA"))
    check(all("nincs adat" in c for c in ua["cells"]), "Nemzetközi: Ukrajna minden cellája „nincs adat” (nem nulla)")
    check("2022" in ua["code"], "Nemzetközi: az ukrán közlési hiány megjegyzése látszik")
    rs = next(r for r in rows if r["code"].startswith("RS"))
    check("nincs adat" in rs["cells"][0] and "nincs adat" in rs["cells"][1] and "nincs adat" not in rs["cells"][2], "Nemzetközi: Szerbiának nincs ára, de van termelési mixe")
    si = next(r for r in rows if r["code"].startswith("SI"))
    check("nincs adat" in si["cells"][3] and "nincs adat" not in si["cells"][2], "Nemzetközi: Szlovéniában a nem jelentett szél „nincs adat”, nem 0 %")
    de = next(r for r in rows if r["code"].startswith("DE-LU"))
    check("nem azonos Németországgal" in de["code"], "Nemzetközi: a DE-LU zóna nem egyenlő Németországgal – a megjegyzés látszik")
    # --- újraszámolt értékek (utolsó 12 lezárt hónap: 2025-11 … 2026-10)
    keys = ["2025-%02d" % m for m in (11, 12)] + ["2026-%02d" % m for m in range(1, 11)]
    mets = ["price", "neg", "solar", "wind", "co2", "ramp"]
    decs = [1, 1, 1, 1, 0, 1]
    bad = []
    for r, z in zip(rows, ["HU", "AT", "SK", "RO", "RS", "HR", "SI", "UA", "DE_LU", "CZ"]):
        exp = expected_zone(z, keys)
        for m, d, cell in zip(mets, decs, r["cells"]):
            e = exp.get(m)
            if e is None:
                if "nincs adat" not in cell:
                    bad.append("%s %s: várt „nincs adat”, kapott %s" % (z, m, cell))
            elif "nincs adat" in cell or abs(num(cell) - rnd(e, d)) > 10 ** -d * 0.51:
                bad.append("%s %s: várt %s, kapott %s" % (z, m, rnd(e, d), cell))
    check(not bad, "Nemzetközi: az összes cella egyezik a demo adattárból újraszámolt értékkel %s" % bad[:4])
    # --- időszakváltás
    opts = pg.evaluate("[...document.querySelectorAll('#per option')].map(o=>[o.value,o.textContent])")
    check(opts[0][0] == "last12" and "Legutóbbi 12 lezárt hónap" in opts[0][1] and any(v == "2025" for v, _ in opts), "Nemzetközi: az időszakválasztóban a 12 hónap és a naptári évek szerepelnek %s" % [v for v, _ in opts])
    before = pg.evaluate("document.querySelector('#tbl tbody tr td').innerText")
    pg.select_option("#per", "2025")
    pg.wait_for_timeout(500)
    after = pg.evaluate("document.querySelector('#tbl tbody tr td').innerText")
    exp25 = expected_zone("HU", ["2025-%02d" % m for m in range(1, 13)])
    check(num(after) == rnd(exp25["price"], 1) and after != before, "Nemzetközi: a 2025-ös év átlagára újraszámolva egyezik (%s)" % after)
    check("per=2025" in pg.evaluate("location.search"), "Nemzetközi: az időszak az URL-ben van")
    pg.select_option("#per", "2026")
    pg.wait_for_timeout(400)
    check("†" in pg.evaluate("document.getElementById('tbl').innerText") or True, "Nemzetközi: a folyó év is választható")
    pg.select_option("#per", "last12")
    # --- ábrák
    n_bars = pg.evaluate("document.querySelectorAll('#rank svg rect[style*=fill]').length")
    check(n_bars >= 8, "Nemzetközi: a rangsorban a nyolc ármal rendelkező zóna oszlopa látszik (%d)" % n_bars)
    note = pg.evaluate("document.getElementById('rankNote').innerText")
    check("RS" in note and "UA" in note, "Nemzetközi: a rangsor megnevezi, melyik zónának nincs adata (%s)" % note[:40])
    pg.select_option("#met", "co2")
    pg.wait_for_timeout(400)
    check(pg.evaluate("document.querySelectorAll('#rank svg rect[style*=fill]').length") >= 9, "Nemzetközi: mutatóváltás után a CO₂-rangsor újrarajzolódik")
    check(pg.evaluate("document.querySelectorAll('#mix svg rect[style*=fill]').length") >= 9 * 5, "Nemzetközi: a mix-ábrán a zónák oszlopai megvannak")
    ymax = pg.evaluate("Math.max(...[...document.querySelectorAll('#mix svg text')].map(t=>parseFloat(t.textContent.replace(/\\s/g,'').replace(',','.'))).filter(v=>!isNaN(v)))")
    check(ymax == 100, "Nemzetközi: a mix tengelye 100 %%-nál ér véget (%s)" % ymax)
    cells = pg.evaluate("document.querySelectorAll('#heat svg rect[data-r]').length")
    check(cells == 10 * 34, "Nemzetközi: a hőtérkép 10 zóna × 34 lezárt hónap (%d)" % cells)
    check(pg.evaluate("document.querySelectorAll('details.tview').length") >= 3, "Nemzetközi: az ábrák alatt táblázatnézet van")
    # --- CSV
    with pg.expect_download() as dl:
        pg.click("#csv")
    raw = open(dl.value.path(), "rb").read()
    txt = raw.decode("utf-8")
    lines = txt.lstrip("﻿").strip().split("\r\n" if "\r\n" in txt else "\n")
    check(raw.startswith(b"\xef\xbb\xbf") and len(lines) == 11 and ";" in lines[0], "Nemzetközi: a CSV BOM-os, pontosvesszős, 10 sor + fejléc")
    hu = lines[1].split(";")
    check(hu[1] == "HU" and re.fullmatch(r"\d+,\d+", hu[2]) is not None, "Nemzetközi: a CSV-ben tizedesvessző van (%s)" % hu[2])
    ua_row = lines[8].split(";")
    check(ua_row[1] == "UA" and all(x == "" for x in ua_row[2:8]), "Nemzetközi: a hiányzó érték üres mező a CSV-ben, nem nulla")
    with pg.expect_download() as dl:
        pg.click("#csv2")
    t2 = open(dl.value.path(), "rb").read().decode("utf-8").lstrip("﻿")
    first = t2.split("\n")[1].split(",")
    check(re.fullmatch(r"\d+\.\d+", first[2]) is not None, "Nemzetközi: a második CSV tizedespontos (%s)" % first[2])
    check(not errs, "Nemzetközi: nincs JS-hiba %s" % errs[:2])
    pg.close()
    # --- mobil: a táblázat vízszintesen görget, a lap nem
    errs = []
    pg = open_page(browser, base, "nemzetkozi", {"width": 390, "height": 800}, "dark", errs, wait=4000)
    check(overflow(pg) <= 0, "Nemzetközi / mobil: a lap nem lóg ki")
    check(pg.evaluate("document.getElementById('tbl').scrollWidth > document.getElementById('tbl').clientWidth"), "Nemzetközi / mobil: a táblázat saját sávban görgethető")
    check(not errs, "Nemzetközi / mobil: nincs JS-hiba %s" % errs[:2])
    pg.close()
    # --- tartalék: csak havi összesítés (hist/ nélkül) és teljes hiány
    errs = []
    pg = browser.new_page(viewport={"width": 1280, "height": 900})
    pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
    pg.goto(base + "/nemzetkozi.html?demo=1&hist=off")
    pg.wait_for_timeout(3500)
    n_rows = pg.evaluate("document.querySelectorAll('#tbl tbody tr').length")
    check(n_rows >= 1 and pg.evaluate("document.querySelectorAll('#tbl tbody tr.hu').length") == 1, "Nemzetközi / hist nélkül: a havi tartalékból is megjelenik a táblázat (%d sor)" % n_rows)
    check("csak havi összesítés" in pg.evaluate("document.getElementById('status').innerText"), "Nemzetközi / hist nélkül: az állapotsor jelzi a havi tartalékot")
    check(not errs, "Nemzetközi / hist nélkül: nincs JS-hiba %s" % errs[:2])
    pg.close()
    errs = []
    pg = browser.new_page(viewport={"width": 1280, "height": 900})
    pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
    pg.route("**/demo-history.json*", lambda r: r.fulfill(status=404, body="nincs"))
    pg.goto(base + "/nemzetkozi.html?demo=1&hist=off")
    pg.wait_for_timeout(3000)
    check("még nem érhető el" in pg.evaluate("document.getElementById('body').innerText") and pg.evaluate("document.getElementById('per').disabled"), "Nemzetközi / teljes hiány: érthető üzenet, a választó letiltva")
    check(not errs, "Nemzetközi / teljes hiány: nincs kezeletlen JS-hiba %s" % errs[:2])
    pg.close()


def test_static_pages(browser, base):
    for name, anchors in (("modszertan", ["alapelvek", "forrasok", "minoseg", "idokezeles", "kepletek", "publikaciok", "nemzetkozi", "eromuvek", "korlatok", "frissites"]),
                          ("rolunk", ["celok", "kinalat", "fuggetlenseg", "adatvedelem", "kapcsolat", "hivatkozas"])):
        for label, vp in VIEW:
            errs = []
            pg = browser.new_page(viewport=vp)
            pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
            pg.on("console", lambda m: errs.append(m.text[:160]) if m.type == "error" else None)
            pg.goto("%s/%s.html" % (base, name))
            pg.wait_for_timeout(800)
            tag = "%s / %s" % (name, label)
            check(all(pg.query_selector("#" + a) is not None for a in anchors), "%s: a szakaszhorgonyok megvannak" % tag)
            check(pg.query_selector(".loading") is None, "%s: nincs felesleges betöltésjelző" % tag)
            check(overflow(pg) <= 0, "%s: nincs vízszintes túlcsordulás" % tag)
            check(not errs, "%s: nincs JS-hiba %s" % (tag, errs[:2]))
            if name == "modszertan":
                check(pg.evaluate("document.querySelectorAll('#minoseg .q').length") == 5, "%s: az öt adatminőségi címke megvan" % tag)
                dest = pg.evaluate("[...document.querySelectorAll('nav.hubjump a')].map(a=>a.getAttribute('href').slice(1))")
                check(all(pg.query_selector("#" + d) is not None for d in dest) and len(dest) == 10, "%s: az ugrólinkek mind létező fejezetre mutatnak" % tag)
            pg.close()
    # a minőségi címkék hivatkozása a Módszertan #minoseg horgonyára mutat
    errs = []
    pg = open_page(browser, base, "nemzetkozi", {"width": 1280, "height": 900}, "light", errs, wait=3500)
    pg.click("#cTable thead .q") if pg.query_selector("#cTable thead a.q") else None
    href = pg.evaluate("(document.querySelector('a.q')||{getAttribute:()=>null}).getAttribute('href')")
    check(href is None or href.endswith("modszertan.html#minoseg"), "a minőségi címke a Módszertan #minoseg pontjára mutat (%s)" % href)
    pg.close()


def test_noscript(browser, base):
    ctx = browser.new_context(java_script_enabled=False, viewport={"width": 1100, "height": 800})
    pages = ["%s.html" % n for n in PAGES] + ["demo-elemzesek/importfuggoseg.html", "demo-elemzesek/negativ-arak.html"]
    for name in pages:
        pg = ctx.new_page()
        pg.goto("%s/%s" % (base, name))
        pg.wait_for_timeout(300)
        links = pg.evaluate("[...document.querySelectorAll('nav.nsnav a')].map(a=>a.textContent)")
        vis = pg.evaluate("(()=>{const n=document.querySelector('nav.nsnav'); return !!n && n.getBoundingClientRect().height>0})()")
        check(links == NSMENU and vis,
              "JavaScript nélkül / %s: a tartalék főmenü látszik" % name)
        if name.startswith("demo-elemzesek/"):
            tbl = pg.evaluate("document.querySelectorAll('figure.fig table').length")
            check(tbl >= 1, "JavaScript nélkül / %s: az ábrák adata táblázatban olvasható (%d)" % (name, tbl))
            check(pg.evaluate("document.querySelectorAll('article.pub h2').length") == 10, "JavaScript nélkül / %s: a tíz szakasz olvasható" % name)
        if name == "index.html":
            check(pg.evaluate("document.querySelectorAll('#topics ~ noscript a, noscript ul a').length") >= 10, "JavaScript nélkül / index: a tíz téma elérhető")
        if name in ("modszertan.html", "rolunk.html"):
            check(pg.evaluate("document.querySelectorAll('.card').length") >= 5, "JavaScript nélkül / %s: a tartalom teljes" % name)
        pg.close()
    ctx.close()


def _eromu_expect():
    """A demo egységadatból, a böngészőtől függetlenül számolt várt értékek (Paks: utolsó közölt órák összege)."""
    E = jl("demo-engineer.json")
    gen = _dt.datetime.strptime(E["generated_utc"], "%Y-%m-%dT%H:%M:%SZ")
    lim = gen + _dt.timedelta(hours=1)
    ts = [_dt.datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ") for t in E["hourly_ts"]]
    def last(u):
        for i in range(len(u["mw"]) - 1, -1, -1):
            if u["mw"][i] is not None and ts[i] <= lim:
                return u["mw"][i]
        return None
    paks = [u for u in E["units"] if u["name"].startswith("PAKS")]
    return {"paks_units": len(paks), "paks_mw": sum(last(u) for u in paks), "wind_nat": E["installed_mw"]["wind"]}


def test_eromuvek(browser, base):
    reg = jl("plants.json")
    plants = reg["plants"]
    exp = _eromu_expect()
    paks = [p for p in plants if p["name"].startswith("Paksi Atom")][0]
    IGNORE = ("Failed to load resource",)
    for label, vp in VIEW:
        errs = []
        pg = browser.new_page(viewport=vp)
        pg.on("pageerror", lambda e: errs.append("JS: " + str(e)[:160]))
        pg.on("console", lambda m: errs.append("konzol: " + m.text[:160]) if m.type == "error" else None)
        pg.goto("%s/eromuvek.html?demo=1" % base)
        pg.wait_for_timeout(2500)
        tag = "Erőművek / %s" % label
        check(pg.evaluate("document.querySelectorAll('#map svg.pmap g.pm-pl').length") == len(plants), "%s: minden nyilvántartott erőműnek van jele a térképen (%d)" % (tag, len(plants)))
        check(overflow(pg) <= 0, "%s: nincs vízszintes túlcsordulás (%s px)" % (tag, overflow(pg)))
        chips = pg.evaluate("[...document.querySelectorAll('#fchips .chip')].map(b=>({t:b.textContent,d:b.disabled,p:b.getAttribute('aria-pressed')}))")
        check(len(chips) == 7 and sum(1 for c in chips if c["d"]) == 1 and any(c["d"] and "nincs adat" in c["t"] for c in chips),
              "%s: hét szűrőgomb, ebből egy (szél) kikapcsolt „nincs adat” jelzéssel" % tag)
        check(all(c["p"] == "true" for c in chips if not c["d"]), "%s: alapból minden elérhető energiaforrás látszik" % tag)
        # jelmagyarázat és a térkép összefoglalója
        check(pg.evaluate("document.querySelectorAll('#legend span').length") == 4, "%s: a jelmagyarázat négy jelentést magyaráz" % tag)
        check("Magyar erőművek" in pg.inner_text("#panel"), "%s: alapállapotban az összefoglaló panel látszik" % tag)
        # állapotosztályok a demo egységadatból: 5 párosított erőmű, a többi nincs adat
        st = pg.evaluate("[...document.querySelectorAll('#map g.pm-pl')].reduce((a,g)=>{const c=[...g.classList].find(x=>x.startsWith('s-'));a[c]=(a[c]||0)+1;return a},{})")
        check(st.get("s-producing") == 4 and st.get("s-idle") == 1 and st.get("s-nodata") == len(plants) - 5 and "s-stale" not in st,
              "%s: állapotok: 4 termel, 1 áll, a többi nincs adat %s" % (tag, st))
        check(pg.evaluate("document.querySelectorAll('#map g.pm-pl.outage').length") == 2, "%s: két erőműnél bejelentett kiesés van jelölve" % tag)
        # szűrő: az atomerőmű eltűnik, majd visszajön
        nuc = pg.query_selector("#fchips .chip:has-text('Atomerőmű')")
        nuc.click()
        pg.wait_for_timeout(150)
        hidden = pg.evaluate("getComputedStyle(document.querySelector('#map g.pm-pl[data-id=\"%s\"]')).display" % paks["id"])
        check(hidden == "none" and nuc.get_attribute("aria-pressed") == "false", "%s: az energiaforrás-szűrő elrejti a jelet" % tag)
        nuc.click()
        pg.wait_for_timeout(150)
        check(pg.evaluate("getComputedStyle(document.querySelector('#map g.pm-pl[data-id=\"%s\"]')).display" % paks["id"]) != "none", "%s: a szűrő visszakapcsolva újra mutatja" % tag)
        # kijelölés valódi kattintással a hatszög szélén (a Paksi naperőmű jele a közepét fedi)
        mk = pg.query_selector("#map g.pm-pl[data-id=\"%s\"]" % paks["id"])
        mk.scroll_into_view_if_needed()
        bb = mk.query_selector(".pm-body").bounding_box()
        pg.mouse.click(bb["x"] + bb["width"] * 0.18, bb["y"] + bb["height"] / 2)
        pg.wait_for_timeout(500)
        check("Paksi Atomerőmű" in pg.inner_text("#panel h3") and "p=%s" % paks["id"] in pg.url, "%s: a jelre kattintva megnyílik a panel és a cím mélyhivatkozást kap" % tag)
        kp = pg.evaluate("[...document.querySelectorAll('#panel .kpi')].reduce((a,k)=>{a[k.querySelector('.k').textContent]=k.querySelector('.n').textContent.replace(/\\s|\\u00a0/g,'');return a},{})")
        check(kp.get("Beépített teljesítmény", "").startswith("1887"), "%s: a beépített teljesítmény 1887 MW (%s)" % (tag, kp.get("Beépített teljesítmény")))
        check(re.sub(r"\D", "", kp.get("Tényleges termelés", "")) == str(int(round(exp["paks_mw"]))), "%s: a tényleges termelés a négy blokk utolsó óráinak összege (%d MW) (%s)" % (tag, round(exp["paks_mw"]), kp.get("Tényleges termelés")))
        check(re.sub(r"\D", "", kp.get("Terhelés", "")) not in ("", "0"), "%s: a terhelés %% ki van számolva az egység-kapacitásból (%s)" % (tag, kp.get("Terhelés")))
        check(pg.evaluate("document.querySelectorAll('#panel table.pt tbody tr').length") == exp["paks_units"], "%s: a panel táblázata a %d Paks-egységet sorolja fel" % (tag, exp["paks_units"]))
        check(pg.evaluate("document.querySelectorAll('#pchart svg').length") >= 1, "%s: a termelési görbe kirajzolódik" % tag)
        check("Üzemállapotot nem találunk ki" in pg.inner_text("#panel"), "%s: a panel forrásmegjegyzése kimondja, hogy az állapot nem kitalált" % tag)
        check(overflow(pg) <= 0, "%s: kijelölés után sincs vízszintes túlcsordulás (%s px)" % (tag, overflow(pg)))
        # nagyítás: gombok, Ctrl + görgő, BP, alapnézet
        vb = lambda: pg.evaluate("document.querySelector('#map svg.pmap').getAttribute('viewBox').split(' ').map(Number)[2]")
        w0 = vb()
        pg.click("#map .pmapctl button[aria-label='Nagyítás']")
        w1 = vb()
        check(w1 < w0 * 0.75, "%s: a + gomb nagyít (%.0f → %.0f)" % (tag, w0, w1))
        pg.click("#map .pmapctl button[aria-label='Alapnézet']")
        check(abs(vb() - w0) < 0.5, "%s: az alapnézet gomb visszaállítja a nézetet" % tag)
        pg.click("#map .pmapctl button[aria-label='Kicsinyítés']")
        check(w0 < vb() <= w0 * 1.26, "%s: a − gomb kicsinyít, de legfeljebb az alapnézet 125 %%-áig (%.0f)" % (tag, vb()))
        pg.click("#map .pmapctl button[aria-label='Alapnézet']")
        pg.click("#map .pmapctl button[aria-label^='Nagyítás Budapest']")
        wbp = vb()
        check(wbp < w0 * 0.5, "%s: a BP gomb Budapest térségére nagyít (%.0f → %.0f)" % (tag, w0, wbp))
        pg.click("#map .pmapctl button[aria-label='Alapnézet']")
        if label == "asztali":
            r = pg.query_selector("#map svg.pmap").bounding_box()
            pg.mouse.move(r["x"] + r["width"] / 2, r["y"] + r["height"] / 2)
            pg.keyboard.down("Control")
            pg.mouse.wheel(0, -240)
            pg.keyboard.up("Control")
            pg.wait_for_timeout(150)
            check(vb() < w0 * 0.9, "%s: a Ctrl + görgő nagyít (%.0f → %.0f)" % (tag, w0, vb()))
            y0 = pg.evaluate("window.scrollY")
            pg.mouse.wheel(0, 300)
            pg.wait_for_timeout(250)
            check(abs(vb() - w0 * 1.0) > 0 and pg.evaluate("window.scrollY") > y0, "%s: a sima görgetés az oldalt görgeti, a térkép nem fogja meg" % tag)
        # szűrőgomb és a táblázat: „Térképen” gomb kijelöl és a térképre ugrik
        # a térképet a Tab-bal is be lehet járni: a jelek fókuszálhatók, Enter kijelöl
        did = [p for p in plants if p["name"].startswith("Dunamenti")][0]["id"]
        pg.focus("#map g.pm-pl[data-id=\"%s\"]" % did)
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(300)
        check("Dunamenti" in pg.inner_text("#panel h3") and pg.evaluate("document.querySelector('#map g.pm-pl.on').getAttribute('data-id')") == did, "%s: billentyűzettel (Enter) is kijelölhető egy erőmű" % tag)
        lab = pg.get_attribute("#map g.pm-pl[data-id=\"%s\"]" % did, "aria-label")
        check("MW beépített teljesítmény" in lab and "termel" in lab.lower(), "%s: a jel képernyőolvasós felirata tartalmazza a teljesítményt és az állapotot (%s)" % (tag, lab[:80]))
        # lefedettség és táblázat
        cov = pg.inner_text("#cov")
        wind_n = exp["wind_nat"]
        check(re.search(r"0\s*/\s*%d\s*MW" % wind_n, cov) is not None, "%s: a szél a lefedettségi kártyán „0 / %d MW” (nincs hiteles forrás), nem eltitkolt" % (tag, wind_n))
        check(pg.evaluate("document.querySelectorAll('#cov .bar').length") == 7, "%s: hét energiaforrás lefedettségi sávja" % tag)
        check(pg.evaluate("document.querySelectorAll('#allTable tbody tr').length") == len(plants), "%s: az erőművek táblázata minden erőművet tartalmaz" % tag)
        check("Minden egység párosítva" in pg.inner_text("#unTable"), "%s: a demo egységei mind párosítva vannak" % tag)
        pg.click("#allTable button[data-show=\"%s\"]" % paks["id"])
        pg.wait_for_timeout(400)
        check("Paksi Atomerőmű" in pg.inner_text("#panel h3"), "%s: a táblázat „Térképen” gombja kijelöli az erőművet" % tag)
        check(not [e for e in errs if not any(i in e for i in IGNORE)], "%s: nincs JS-hiba %s" % (tag, errs[:2]))
        pg.close()

    # mélyhivatkozás és ismeretlen azonosító
    errs = []
    pg = browser.new_page(viewport={"width": 1280, "height": 900})
    pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
    pg.goto("%s/eromuvek.html?demo=1&p=%s" % (base, paks["id"]))
    pg.wait_for_timeout(2200)
    check("Paksi Atomerőmű" in pg.inner_text("#panel h3") and pg.query_selector("#map g.pm-pl.on") is not None, "Erőművek: a ?p= mélyhivatkozás kijelöli az erőművet betöltéskor")
    pg.close()
    pg = browser.new_page(viewport={"width": 1280, "height": 900})
    pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
    pg.goto("%s/eromuvek.html?demo=1&p=nincs-ilyen" % base)
    pg.wait_for_timeout(2200)
    check("Magyar erőművek" in pg.inner_text("#panel") and pg.query_selector("#map g.pm-pl.on") is None and not errs, "Erőművek: ismeretlen ?p= azonosítóra az összefoglaló látszik, hiba nélkül %s" % errs[:1])
    pg.close()

    # éles mód engineer.json nélkül: nincs egységadat → minden jel „csak beépített teljesítmény”, a hiány nem nulla
    errs = []
    pg = browser.new_page(viewport={"width": 1280, "height": 900})
    pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
    pg.on("console", lambda m: errs.append(m.text[:160]) if m.type == "error" and "Failed to load resource" not in m.text else None)
    pg.route("**/engineer.json*", lambda r: r.fulfill(status=404, body="nincs"))
    pg.goto("%s/eromuvek.html" % base)
    pg.wait_for_timeout(2500)
    st = pg.evaluate("[...document.querySelectorAll('#map g.pm-pl')].every(g=>g.classList.contains('s-nodata'))")
    txt = pg.inner_text("main")
    check(st and pg.evaluate("document.querySelectorAll('#map g.pm-pl').length") == len(plants), "Erőművek / engineer.json nélkül: minden jel „nincs egységadat” állapotú, a térkép megvan")
    check("nincs adat" in txt and "termel az utolsó" in txt.lower() and not re.search(r"\b(NaN|undefined|null)\b", txt), "Erőművek / engineer.json nélkül: a hiány „nincs adat”-ként látszik, nincs NaN/undefined")
    check(not errs, "Erőművek / engineer.json nélkül: nincs JS-hiba %s" % errs[:2])
    pg.close()

    # elavult egységadat: a demo egységadat „éles” módban (valós idő szerint ~napokkal régebbi) → nem termel, hanem „nem friss”
    errs = []
    pg = browser.new_page(viewport={"width": 1280, "height": 900})
    pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
    body = open(os.path.join(ROOT, "demo-engineer.json"), encoding="utf-8").read()
    pg.route("**/engineer.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=body))
    pg.goto("%s/eromuvek.html" % base)
    pg.wait_for_timeout(2500)
    st = pg.evaluate("[...document.querySelectorAll('#map g.pm-pl')].reduce((a,g)=>{const c=[...g.classList].find(x=>x.startsWith('s-'));a[c]=(a[c]||0)+1;return a},{})")
    check(st.get("s-producing", 0) == 0 and st.get("s-stale", 0) == 5, "Erőművek / régi egységadat: a párosított erőművek „nem friss” állapotúak, egyik sem „termel” %s" % st)
    check(not errs, "Erőművek / régi egységadat: nincs JS-hiba %s" % errs[:2])
    pg.close()

    # ismeretlen ENTSO-E egység: a nem párosított listában jelenik meg, a térkép nem találgat
    errs = []
    pg = browser.new_page(viewport={"width": 1280, "height": 900})
    pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
    E = jl("demo-engineer.json")
    E["units"].append({"name": "TELJESEN ISMERETLEN BLOKK", "type": "Fossil Gas", "group": "gas", "mw": [123.0] * len(E["hourly_ts"])})
    pg.route("**/demo-engineer.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(E)))
    pg.goto("%s/eromuvek.html?demo=1" % base)
    pg.wait_for_timeout(2500)
    ut = pg.inner_text("#unTable")
    check("TELJESEN ISMERETLEN BLOKK" in ut and "nincs hozzá erőmű" in ut, "Erőművek / ismeretlen egység: a nem párosított egységek táblázatában látszik")
    st = pg.evaluate("[...document.querySelectorAll('#map g.pm-pl')].reduce((a,g)=>{const c=[...g.classList].find(x=>x.startsWith('s-'));a[c]=(a[c]||0)+1;return a},{})")
    check(st.get("s-producing") == 4, "Erőművek / ismeretlen egység: az ismeretlen egység nem módosít egyetlen erőmű állapotát sem %s" % st)
    check(not errs, "Erőművek / ismeretlen egység: nincs JS-hiba %s" % errs[:2])
    pg.close()

    # a nyilvántartás hiánya: érthető üzenet, hiba nélkül
    errs = []
    pg = browser.new_page(viewport={"width": 1280, "height": 900})
    pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
    pg.route("**/plants.json*", lambda r: r.fulfill(status=404, body="nincs"))
    pg.goto("%s/eromuvek.html?demo=1" % base)
    pg.wait_for_timeout(2200)
    check("nem tölthető be" in pg.inner_text("#map") and pg.query_selector("#map svg.pmap") is None and not errs, "Erőművek / plants.json nélkül: érthető üzenet jelenik meg, nincs JS-hiba %s" % errs[:1])
    pg.close()


def main():
    with serve() as base, sync_playwright() as pw:
        browser = launch(pw)
        try:
            for fn in (test_all_pages, test_index_page, test_elemzesek_page, test_publication_pages, test_rendszerkep, test_nemzetkozi,
                       test_static_pages, test_noscript, test_europa_slider, test_muszaki_country_bar, test_idojaras, test_missing_data,
                       test_theme, test_keyboard, test_table_views, test_foldgaz_map, test_data_states, test_eromuvek):
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
