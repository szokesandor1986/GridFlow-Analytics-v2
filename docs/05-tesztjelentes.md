# 5. szakasz – Tesztjelentés és ismert korlátok

Ez a jelentés azt rögzíti, mit ellenőriztünk, mivel és milyen eredménnyel, és mit **nem** tudtunk ellenőrizni. A számok a demo adaton és kitalált klienseken futó tesztekből származnak; a valódi forrásokat (ENTSO-E, HUPX, JAO, Open-Meteo, GIE) a fejlesztői környezet nem éri el.

## 1. Összefoglaló

| Teszt | Mit fed le | Eredmény |
|---|---|---|
| `tests/test_site.py` | mind a 12 oldal szerkezete: cím, nyelv, menü, belső hivatkozások és horgonyok, noscript tartalék, kiegyensúlyozott HTML, nincs külső szkript vagy stíluslap, szóhasználat (nincs „áram” az energia értelmében) | 237 ellenőrzés, hibátlan |
| `tests/test_publish.py` | az elemzés-generátor: tízrészes szerkezet mind a 10 témánál, a közölt számok újraszámolása a `history.json`-ból, hiányzó adat, determinizmus (két futás azonos bájtokat ad), noscript táblázatok | 140 ellenőrzés, hibátlan |
| `tests/test_gfhist.js` | a Historikus adatréteg: óra/negyedóra/nap/hét/hónap/év rács, DST-napok (23 és 25 órás napok), szökőév, súlyozás, folyó időszak, havi tartalék, adat nélküli állapot | 8 próbacsoport, hibátlan |
| `tests/test_hist.py` | a visszatöltés és az összesítők: rács, hiány = üres (nem nulla), 70 %-os lefedettségi szabály, CO₂ termeléssel súlyozva, nettó import, maradék terhelés és rámpa-mutatók, manifest hash, újrafuttatás változatlan fájlokat ad, a tár nem tartalmaz kulcsot | 13 próbacsoport, hibátlan |
| `tests/test_historikus.py` | a Historikus adatok oldal böngészőben: időszak és felbontás, évek összevetése, CSV, hiány kezelése | 91 ellenőrzés, hibátlan |
| `tests/test_pages.py` | mind a 12 oldal Chrome-ban (Playwright): lásd 3. pont | 612 ellenőrzés, hibátlan |
| `test_collector/freq/hupx/jao/weather/gas/history.py` | az élő gyűjtők (változatlanok): hibatűrés, a hibás forrás nem rontja a meglévő fájlt | mind átment |

Futtatás: README, „Tesztek” szakasz. Az `update.yml` a böngésző nélküli teszteket (gyűjtők, `test_publish`, `test_site`, `test_gfhist`) minden közzététel előtt lefuttatja; a böngészős próbák kézzel futtatandók, mert a böngésző letöltése lassítaná a 20 percenkénti frissítést.

## 2. Ellenőrzött követelmények

| Követelmény | Hogyan ellenőrzött |
|---|---|
| Hét főmenüpont minden oldalon, a jelenlegi jelölt | `test_site`, `test_pages` (a menü a `gf.js`-ből jön; JavaScript nélkül a noscript tartalék ugyanazt a hetet adja) |
| Rendszerkép A–G szakasz, a meglévő nézetek megmaradtak | `test_pages::test_rendszerkep`: a mutatók a demo adatból újraszámolt értékkel egyeznek; hiányzó adatnál „nincs adat”, nem nulla; a részletes nézetek (Határok, Rendszerállapot, Európai piac, Időjárás, Földgáz) változatlanul működnek |
| Történeti tár, több év | `test_hist` + `test_gfhist`: óránkénti UTC rács, DST-napok, szökőév, folyó időszak nem ad félrevezető összesítőt |
| Nemzetközi összehasonlítás, csak azonos definíciójú mutatók | `test_pages::test_nemzetkozi`: a táblázat újraszámolt értékekkel egyezik, a hiányzó zóna „nincs adat”; a zóna (ajánlati zóna) nem ország: a szöveg és a címkék ezt kimondják |
| Adatminőségi címkék (végleges, előzetes, hiányzik, becsült, számított) | `test_site` (a Módszertan öt címkesora), `test_pages` (a címke kirajzolódik a Rendszerkép, a Nemzetközi és az elemzés-oldalakon) |
| 10 témájú publikációs rendszer, rögzített tízrészes szerkezet | `test_publish`: minden elemzésben megvan mind a tíz rész, a számok az adatból számoltak, hiányzó adatnál a rész kimarad vagy „nincs adat”, nem nulla |
| Nincs titok a böngészőben vagy a tárban | `test_hist` (13. pont): a tár nem tartalmaz kulcsot vagy tokent; kézi átnézés: a kulcsok csak a workflow-kban jelennek meg (`${{ secrets.… }}`), a HTML, JS és JSON fájlokban nincs kulcs- vagy token-mintázat; a böngésző nem hív külső szolgáltatást (`test_site`: nincs külső szkript/stíluslap) |
| GitHub Pages-kompatibilitás | `test_pages::test_subpath`: a teljes oldalkészlet a `/GridFlow-Analytics-v2/` alútvonal alatt betölt, a gyökér 404-et ad, így a gyökérre mutató hivatkozások kibuknának; nincs sikertelen kérés |
| Hozzáférhetőség | ugrólink, látható fókusz, Tab-bejárás, minden ábrához aria-összefoglaló és táblázatnézet, világos/sötét/automatikus téma, mobil és asztali nézet, nincs vízszintes túlcsordulás |
| Hibatűrés | hiányzó vagy elavult adatfájl, hiányzó zóna, üres `hist/`: érthető üzenet, nincs kezeletlen JS-hiba |
| Szóhasználat | „villamos energia”, „villamosenergia-rendszer”; az „áram” csak az elektromos áram (A) értelmében; mértékegységek: A, W, Wh |

## 3. Böngészős teljes oldalteszt

A `test_pages.py` mind a 12 oldalt megnyitja a demo adattal asztali és mobil méretben, világos és sötét módban. A futás során egy hibát találtunk, ami teszt-oldali volt (az ugrólink Enter-je a `#main` horgonyt írta a címbe, és az újratöltés onnan folytatta a Tab-bejárást); a tesztet javítottuk, a lap hibátlan.

Eredmény: **612 ellenőrzés, hibátlan** (`MINDEN OK`). Lefedett területek:

- minden oldal: nincs JS-hiba, nincs konzolhiba, nincs vízszintes túlcsordulás, a fő tartalom megjelent (asztali és mobil, világos és sötét);
- a hétpontos főmenü és a Rendszerkép hatpontos almenüje, a jelenlegi oldal jelölése, JavaScript nélkül a tartalék menü;
- Rendszerkép (A–G), Nemzetközi összehasonlítás, Módszertan, Rólunk, Elemzések és a tíz publikációs oldal tartalma és adatai;
- Európai piac (csúszka), Rendszerállapot (országsáv), Időjárás (legfeljebb négy település), Földgáz (térkép);
- téma (automatikus / világos / sötét, megmarad újratöltés után), billentyűzet és fókusz, ábra-összefoglalók és táblázatnézetek;
- adatállapotok (friss, elavult, hiányzó fájl, demo) és az alútvonal (`/GridFlow-Analytics-v2/`).

## 4. Ami nem ellenőrzött (őszintén)

1. **Valódi források.** A fejlesztői környezet nem éri el az ENTSO-E-t, a HUPX-ot, a JAO-t, az Open-Meteót és a GIE-t. A visszatöltés és az élő gyűjtés kitalált klienssel tesztelt; az első éles futás mutathat oszlopnév-, felbontás- vagy hiánymintázat-eltérést. Teendő az első visszatöltés után: a Historikus adatok állapotsorának és a Nemzetközi összehasonlítás hiányzó celláinak átnézése.
2. **A visszatöltés futásideje és az ENTSO-E sebességkorlátja.** 10 zóna, 2019-től, óránkénti adat: több futásra is szükség lehet. A visszatöltés folytatható (a már kész zóna-évet kihagyja), de a tényleges időt csak az éles futás mutatja.
3. **A `hist/` tár mérete.** Becslés 70–100 MB; a mérés a visszatöltés után lehetséges. A 20 percenkénti közzététel ezt minden futásnál feltölti, ezért a futás lassulhat; ha gond, ritkítható a közzététel.
4. **Nem minden kategória van a történeti tárban:** kiesések története, szabályozási energia (aFRR, mFRR) története, frekvencia története, nem magyar zónák beépített kapacitása. Emiatt a 7. és 8. elemzési téma részleges; ezek az élő ablakban (Rendszerállapot) látszanak.
5. **Ukrajna és Szerbia** ENTSO-E-közlése hiányos; a hiány üres marad, de a táblázat és a rangsor ennek megfelelően kevesebb mutatót ad ezeknél a zónáknál.
6. **A JAO CNEC fül** még nincs meg; a `jao.py` felderítő lépése a mezőneveket a logba írja.
7. **Licenc:** a saját szövegekre nincs licenc megadva; a külső adatok forrásainak feltételei érvényesek. Az Open-Meteo ingyenes API-ja csak nem kereskedelmi célra használható.
8. **Valódi böngészők:** a tesztek Chrome-ban futottak. Safari/Firefox nincs kipróbálva; az oldalak egyszerű JavaScriptet és SVG-t használnak, de ezt nem igazoltuk.
9. **Kapcsolat és szerzői megjelölés:** a kapcsolat a GitHub Issues; a Rólunk oldal szerzői sora általános. Ha név vagy e-mail kell, azt a tulajdonosnak kell megadnia.

## 5. A csomag tartalma

- Oldalak (12): `index`, `elemzesek`, `rendszerkep`, `historikus`, `nemzetkozi`, `modszertan`, `rolunk`, `hatarok`, `muszaki`, `europa`, `idojaras`, `foldgaz` (`.html`).
- Közös kód: `assets/` (`gf.js`, `gf.css`, `gfchart.js`, `gfhist.js`, `gfpub.js`, ikonok).
- Adatgyűjtés és feldolgozás: `collector.py`, `freq.py`, `weather.py`, `gas.py`, `hupx.py`, `jao.py`, `history.py`, `backfill.py`, `hist_store.py`, `aggregate.py`, `publish.py`.
- Workflow-k: `.github/workflows/` (`update`, `history`, `hist-backfill`, `hist-update`, `gas` és társaik), `deploy/` (saját szerveres és tárhelyes változatok).
- Demo adat: `demo-*.json`, `demo-hist/`, `demo-elemzesek/` (kitalált értékek, `?demo=1`).
- Tesztek: `tests/`.
- Dokumentáció: `README.md`, `docs/01–05`.
