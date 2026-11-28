"""Böngészős teszt a Historikus adatok oldalhoz (Playwright, demo adattárral: demo-hist/ és demo-history.json).

Mit ellenőriz:
  - alapnézet: nincs JavaScript- vagy konzolhiba, van ábra, cím, minőségsor, forrássor, letölthető CSV,
  - kategóriánként és országonként: a felbontás-választó csak olyat kínál, ami az adatból tényleg elérhető,
  - az óránkénti nézet a nyári/téli időszámítás váltónapjain 23, illetve 25 pontot ad,
  - összehasonlítás: előző év, egyéni másik időszak, évek egymás fölött (több sorozat, jelmagyarázat),
  - további nézetek: hőtérkép (hónap × év, napszak × hónap), szórásdiagram,
  - a nézet az URL-ből visszaállítható,
  - tartalék üzemmód: ha nincs hist/, a havi history.json-ból dolgozik, és ezt kiírja,
  - mobilon és sötét módban nincs hiba és nincs vízszintes túlcsordulás.

Futtatás (a projekt mappájából):  python -I tests/test_historikus.py
Ha a Playwright nincs telepítve, a teszt kihagyja magát (kilépési kód 0).
"""
import contextlib
import csv
import functools
import http.server
import io
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
    srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield "http://127.0.0.1:%d" % srv.server_address[1]
    finally:
        srv.shutdown()


def launch(pw):
    path = os.environ.get("CHROME_PATH") or ("/usr/bin/google-chrome" if os.path.exists("/usr/bin/google-chrome") else None)
    return pw.chromium.launch(executable_path=path, args=["--no-sandbox"]) if path else pw.chromium.launch(args=["--no-sandbox"])


class Page:
    """Egy megnyitott oldal hibagyűjtéssel és rövid segédekkel."""

    def __init__(self, browser, url, width=1280, scheme="light"):
        self.errs = []
        self.pg = browser.new_page(viewport={"width": width, "height": 900}, color_scheme=scheme, accept_downloads=True)
        self.pg.on("pageerror", lambda e: self.errs.append("js: " + str(e)[:160]))
        self.pg.on("console", lambda m: self.errs.append("konzol: " + m.text[:160]) if m.type == "error" else None)
        self.pg.on("requestfailed", lambda r: self.errs.append("kérés: " + r.url[-60:]) if "favicon" not in r.url else None)
        self.pg.goto(url)
        self.settle()

    def settle(self, ms=450):
        self.pg.wait_for_function("document.querySelector('#mainSub') && document.querySelector('#mainSub').textContent.length > 0 || document.querySelector('#chart .nodata')", timeout=15000)
        self.pg.wait_for_timeout(ms)

    def sel(self, id, value):
        self.pg.select_option("#" + id, value)
        self.settle()

    def date(self, id, value):
        self.pg.fill("#" + id, value)
        self.pg.dispatch_event("#" + id, "change")
        self.settle()

    def opts(self, id):
        return self.pg.eval_on_selector_all("#%s option" % id, "o => o.map(x => x.value)")

    def val(self, id):
        return self.pg.input_value("#" + id)

    def chips(self, host="#chart"):
        return self.pg.eval_on_selector_all(host + " .chip", "c => c.map(x => x.textContent.trim())")

    def has_svg(self, host="#chart"):
        """Van kirajzolt adat: legalább egy hosszú vonalpálya, vagy sok téglalap/pont (oszlop, hőtérkép, szórás)."""
        return self.pg.evaluate(
            "h => { const r = document.querySelector(h); if (!r) return false;"
            " const long = [...r.querySelectorAll('svg path')].some(p => (p.getAttribute('d') || '').length > 40);"
            " return long || r.querySelectorAll('svg rect').length > 5 || r.querySelectorAll('svg circle').length > 5; }", host)

    def table_rows(self, host="#chart"):
        """A táblázatnézet (details.tview) az ábra testvéreleme; kinyitjuk, és megszámoljuk a sorokat."""
        self.pg.evaluate("h => { const d = document.querySelector(h + ' ~ details.tview'); if (d) d.open = true; }", host)
        self.pg.wait_for_timeout(250)
        return self.pg.eval_on_selector_all(host + " ~ details.tview table tbody tr", "r => r.length")

    def overflow(self):
        return self.pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")

    def close(self):
        self.pg.close()


def run(base, browser):
    u = base + "/historikus.html?demo=1"

    print("[alapnézet]")
    p = Page(browser, u)
    check(not p.errs, "nincs JS-, konzol- vagy kérési hiba: %s" % p.errs[:3])
    check(p.has_svg(), "az alapnézetben van ábra")
    check("Termelés" in p.pg.inner_text("#mainTitle"), "a cím a kategóriát és az országot mutatja: " + p.pg.inner_text("#mainTitle"))
    check("Minőség" in p.pg.inner_text("#qline") and "Utolsó adat" in p.pg.inner_text("#qline"), "a minőségsor és az utolsó adat látszik")
    check("Forrás:" in p.pg.inner_text("#srcline") and "MW" in p.pg.inner_text("#srcline"), "a forrássor a mértékegységet is kiírja")
    check(p.pg.inner_text("main").count("Forrás: ENTSO-E 16.1.B&C") == 1, "a forrás nem jelenik meg kétszer")
    check(len(p.chips()) == 8, "a termelés 8 sorozata kapcsolható: %d" % len(p.chips()))
    check(p.pg.locator(".banner.demo").count() == 1, "a demo adat sáv ki van írva")
    check(p.opts("res") and p.opts("res")[0] in ("m", "w", "d"), "12 hónaphoz havi/heti/napi felbontás kínálkozik: %s" % p.opts("res"))
    with p.pg.expect_download() as dl:
        p.pg.click("#csv")
    raw = open(dl.value.path(), encoding="utf-8").read()
    check(raw.startswith("\ufeff"), "a CSV UTF-8 BOM-mal kezdődik (az ékezetek az Excelben is jók)")
    rows = list(csv.reader(io.StringIO(raw.lstrip("\ufeff")), delimiter=";"))
    check(len(rows) > 5 and rows[0][0] == "kulcs" and "minőség" in rows[0] and "forrás" in rows[0], "az Excel-CSV fejléce: %s" % rows[0][:3])
    check(len(rows[0]) == 2 + 8 + 2, "a CSV oszlopai: kulcs, helyi idő, 8 sorozat, minőség, forrás (%d)" % len(rows[0]))
    check(all(len(r) == len(rows[0]) for r in rows), "a CSV minden sora azonos hosszú")
    check(dl.value.suggested_filename.startswith("gridflow_HU_generation_") and not dl.value.suggested_filename.endswith("_pont.csv"), "a CSV neve: " + dl.value.suggested_filename)
    nums = [c for r in rows[1:] for c in r[2:10] if c != ""]
    check(nums and all(("." not in c) and c.replace(",", "").replace("-", "").replace("−", "").isdigit() for c in nums), "az Excel-CSV számai tizedesvesszősek, pont nélkül (pl. %s)" % nums[:3])
    check(all(r[-1].startswith("ENTSO-E") for r in rows[1:]), "minden sorban ott a forrás")
    check(all(r[-2] in ("végleges", "előzetes", "számított", "becsült") for r in rows[1:]), "minden sorban ott a minőségi címke: %s" % sorted({r[-2] for r in rows[1:]}))
    with p.pg.expect_download() as dl2:
        p.pg.click("#csv2")
    raw2 = open(dl2.value.path(), encoding="utf-8").read().lstrip("\ufeff")
    rows2 = list(csv.reader(io.StringIO(raw2), delimiter=","))
    check(dl2.value.suggested_filename.endswith("_pont.csv") and len(rows2) == len(rows) and len(rows2[0]) == len(rows[0]), "a tizedespontos CSV ugyanannyi sor/oszlop: " + dl2.value.suggested_filename)
    nums2 = [c for r in rows2[1:] for c in r[2:10] if c != ""]
    check(nums2 and all(float(c) is not None for c in nums2), "a tizedespontos CSV számai gépileg olvashatók (pl. %s)" % nums2[:3])
    check(len(nums2) == len(nums), "a két CSV ugyanannyi értéket tartalmaz (%d)" % len(nums))
    p.close()

    print("[felbontások és mutatók]")
    p = Page(browser, u + "&zone=HU&cat=price_da&per=24h")
    r = p.opts("res")
    check("q" in r and "h" in r, "HU ár 24 órára: negyedórás és órás nézet is van: %s" % r)
    check(p.val("res") == "q", "24 órára alapból a negyedórás nézet: " + p.val("res"))
    check(p.has_svg(), "a negyedórás ábra kirajzolódik")
    check(p.table_rows() in (96, 97, 100, 92, 95), "24 óra negyedórás: ~96 sor a táblázatban: %d" % p.table_rows())
    p.sel("per", "7d")
    check("q" in p.opts("res") and "h" in p.opts("res"), "7 napra a negyedórás is és az órás is elérhető (14 napig): %s" % p.opts("res"))
    check(p.val("res") == "h", "7 napra alapból órás: " + p.val("res"))
    p.sel("per", "30d")
    check("q" not in p.opts("res") and "h" in p.opts("res"), "30 napra nincs negyedórás (túl sűrű), van órás: %s" % p.opts("res"))
    p.sel("per", "7d")
    check("neg" in p.opts("stat") and "energy" not in p.opts("stat"), "az ár mutatói: átlag + negatív órák száma, nincs energia: %s" % p.opts("stat"))
    p.sel("stat", "neg")
    check("óra" in p.pg.inner_text("#chart") or "Negatív" in p.pg.inner_text("#mainSub"), "a negatív árú órák száma mutató működik")
    p.sel("per", "12m")
    check(set(p.opts("res")) >= {"m", "w", "d"}, "12 hónapra havi/heti/napi: %s" % p.opts("res"))
    p.sel("res", "d")
    p.sel("stat", "max")
    check("Legnagyobb" in p.pg.inner_text("#mainSub"), "a legnagyobb érték mutató: " + p.pg.inner_text("#mainSub"))
    check(not p.errs, "nincs hiba: %s" % p.errs[:3])
    p.close()

    p = Page(browser, u + "&zone=HU&cat=generation&per=7d")
    check(p.val("res") == "h", "termelés 7 napra órás: " + p.val("res"))
    check("energy" in p.opts("stat"), "a termelésnél van energia (GWh) mutató")
    p.sel("stat", "energy")
    check("GWh" in p.pg.inner_text("#chart"), "az energia GWh-ban jelenik meg")
    p.close()

    p = Page(browser, u + "&zone=AT&cat=generation&per=7d")
    check(set(p.opts("res")) <= {"d", "w", "m", "y"}, "hourly nélküli zónánál nincs órás felbontás: %s" % p.opts("res"))
    check("óránkénti" in p.pg.inner_text("#msg").lower() or p.opts("res") == ["d"], "az óránkénti adat hiányát kiírja: " + p.pg.inner_text("#msg")[:80])
    p.close()

    print("[DST-váltónapok]")
    p = Page(browser, u + "&zone=HU&cat=load&per=custom&from=2026-03-29&to=2026-03-29&res=h")
    check(p.val("res") == "h", "egyéni napra órás felbontás: " + p.val("res"))
    check(p.table_rows() == 23, "2026-03-29 (tavaszi óraátállítás): 23 óra: %d" % p.table_rows())
    p.date("from", "2026-10-25")
    p.date("to", "2026-10-25")
    p.sel("res", "h")
    check(p.table_rows() == 25, "2026-10-25 (őszi óraátállítás): 25 óra: %d" % p.table_rows())
    p.date("from", "2026-06-10")
    p.date("to", "2026-06-10")
    p.sel("res", "h")
    check(p.table_rows() == 24, "átlagos nap: 24 óra: %d" % p.table_rows())
    p.close()

    print("[összehasonlítás]")
    p = Page(browser, u + "&zone=HU&cat=price_da&per=12m&res=m&cmp=yoy")
    check(not p.pg.is_visible("#serWrap"), "egysorozatú kategóriánál (ár) nincs értelmetlen sorozatválasztó")
    check(not p.pg.is_visible("#msWrap"), "egysorozatú kategóriánál a hőtérkép-sorozatválasztó is rejtett")
    chips = p.chips()
    check(len(chips) == 2, "előző évvel: két sorozat a jelmagyarázatban: %s" % chips)
    check(any("–" in c for c in chips), "a sorozatnevek az időszakot is tartalmazzák")
    check(p.has_svg() and not p.errs, "az összehasonlító ábra kirajzolódik, nincs hiba: %s" % p.errs[:3])
    p.sel("cmp", "custom")
    check(p.pg.is_visible("#cust2") and p.val("from2") != "", "egyéni összehasonlításnál a másik időszak dátumai kitöltődnek")
    check(len(p.chips()) == 2, "egyéni összehasonlítás: két sorozat")
    p.sel("cmp", "overlay")
    n = len(p.chips())
    check(n == 2 and all("/" in c for c in p.chips()), "évek egymás fölött, 12 hónapos (év határát átlépő) ablak: évpár-címkék (%s)" % p.chips())
    p.sel("per", "full")
    ch = p.chips()
    check(ch == ["2024", "2025", "2026"], "teljes időszaknál naptári évre szűkít, és minden év külön sorozat: %s" % ch)
    check("naptári évre" in p.pg.inner_text("#msg"), "kiírja a szűkítést: " + p.pg.inner_text("#msg")[:100])
    svgtxt = p.pg.eval_on_selector("#chart svg", "e => e.textContent")
    check("2024." not in svgtxt and "2025." not in svgtxt, "az átfedett x-tengelyen nincs évszám: " + svgtxt[:60])
    check(all(m in svgtxt for m in ("jan", "júl")), "az átfedett x-tengely hónapnevekkel jelenik meg")
    # az átfedésben a három év azonos x-helyeken van: a táblázatban minden sorban három érték (vagy 'nincs adat' a 2026 hátralévő hónapjaira)
    check(p.table_rows() == 12, "12 havi pont a közös x-tengelyen: %d" % p.table_rows())
    check(not p.errs, "nincs hiba az összehasonlításnál: %s" % p.errs[:3])
    p.close()

    p = Page(browser, u + "&zone=HU&cat=generation&per=12m&res=m")
    check(not p.pg.is_visible("#serWrap"), "összehasonlítás nélkül nem látszik a sorozatválasztó")
    p.sel("cmp", "yoy")
    check(p.pg.is_visible("#serWrap"), "többsorozatú kategóriánál az összehasonlításhoz sorozatot lehet választani")
    p.sel("ser", "solar")
    check("Napenergia" in "".join(p.chips()), "a választott sorozat az ábrán: %s" % p.chips())
    p.close()

    print("[kategóriák]")
    p = Page(browser, u)
    for cat in ["load", "load_forecast", "price_da", "flow_physical", "flow_scheduled", "net_import", "residual", "co2", "ramp"]:
        p.sel("cat", cat)
        check(p.has_svg() or p.pg.locator("#chart .nodata").count() > 0, "%s: ábra vagy adathiány-jelzés van" % cat)
    check(not p.errs, "kategóriaváltás közben nincs hiba: %s" % p.errs[:3])
    p.sel("cat", "flow_physical")
    check(len(p.chips()) == 7 or len(p.chips()) == 6, "a határkeresztező áramlás határonkénti sorozatai: %d" % len(p.chips()))
    p.close()

    print("[további nézetek]")
    p = Page(browser, u + "&zone=HU&cat=price_da")
    p.pg.select_option("#mview", "heatmy")
    p.pg.wait_for_timeout(500)
    check(p.has_svg("#more"), "hőtérkép: hónap × év")
    p.pg.select_option("#mview", "heathm")
    p.pg.wait_for_timeout(600)
    check(p.has_svg("#more") and "órá" in p.pg.inner_text("#morenote") + p.pg.inner_text("#more") or p.has_svg("#more"), "hőtérkép: napszak × hónap (HU 2026)")
    p.pg.select_option("#mview", "scatter")
    p.pg.wait_for_timeout(600)
    pts = p.pg.eval_on_selector_all("#more svg circle", "c => c.length")
    check(pts > 200, "szórásdiagram: sok pont (%d)" % pts)
    p.pg.select_option("#mx", "load:load")
    p.pg.wait_for_timeout(500)
    check(p.pg.eval_on_selector_all("#more svg circle", "c => c.length") > 200, "szórás a fogyasztással")
    p.close()

    p = Page(browser, u + "&zone=AT&cat=price_da")
    p.pg.select_option("#mview", "heathm")
    p.pg.wait_for_timeout(500)
    check("nincs óránkénti adat" in p.pg.inner_text("#more").lower() or "óránkénti adat" in p.pg.inner_text("#more"), "órás adat nélküli zónánál a hőtérkép érthetően jelzi a hiányt")
    p.pg.select_option("#mview", "scatter")
    p.pg.wait_for_timeout(500)
    check("óránkénti adat" in p.pg.inner_text("#more"), "órás adat nélkül a szórásdiagram sem rajzol félrevezetően")
    p.close()

    print("[URL-ből visszaállítás]")
    p = Page(browser, u + "&zone=HU&cat=price_da&per=30d&res=d&stat=max")
    check((p.val("zone"), p.val("cat"), p.val("per"), p.val("res"), p.val("stat")) == ("HU", "price_da", "30d", "d", "max"), "a beállítások az URL-ből jönnek")
    check("zone=HU" in p.pg.url and "cat=price_da" in p.pg.url, "a nézet az URL-be íródik")
    p.sel("cat", "load")
    check("cat=load" in p.pg.url, "a változtatás frissíti az URL-t")
    p.close()

    print("[tartalék üzemmód: nincs hist/]")
    p = Page(browser, u + "&hist=off")
    check("havi" in p.pg.inner_text("#msg").lower(), "kiírja, hogy csak havi összesítés van: " + p.pg.inner_text("#msg")[:90])
    check(set(p.opts("res")) <= {"m", "y"}, "csak havi/éves felbontás: %s" % p.opts("res"))
    check(p.has_svg(), "a havi tartalék is kirajzol")
    p.sel("per", "full")
    bad = [e for e in p.errs if "404" not in e]    # a hiányzó hist/ 404-e a tartalék működésének kiváltója, nem hiba
    check(not bad, "nincs hiba a tartalék módban (a várt 404-en kívül): %s" % bad[:3])
    p.close()

    print("[mobil és sötét mód]")
    for w, scheme in ((390, "light"), (390, "dark"), (1280, "dark")):
        p = Page(browser, u + "&cmp=yoy&zone=HU&cat=price_da", width=w, scheme=scheme)
        check(not p.errs, "%d px, %s: nincs hiba: %s" % (w, scheme, p.errs[:3]))
        check(p.overflow() <= 1, "%d px, %s: nincs vízszintes túlcsordulás (%d)" % (w, scheme, p.overflow()))
        check(p.has_svg(), "%d px, %s: van ábra" % (w, scheme))
        p.close()


def main():
    with serve() as base, sync_playwright() as pw:
        b = launch(pw)
        try:
            run(base, b)
        finally:
            b.close()
    print("\n" + ("Minden historikus-oldal teszt rendben." if not FAIL else "HIBÁK (%d):\n  - " % len(FAIL) + "\n  - ".join(FAIL)))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
