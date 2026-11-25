# GridFlow Analytics v2 – határkeresztező villamosenergia-áramlás, Magyarország

> **Ez a v2.** A korábbi (v1) repó változatlan marad; ez a mappa egy külön repóba (javasolt név: `GridFlow-Analytics-v2`) másolható. A v1-hez képest az adatgyűjtők, a JSON-mezők és a számítások **nem változtak**; a változás a megjelenésben, a hozzáférhetőségben és a közös kódban van. Az alábbi rész a v2 újdonságait írja le, utána a v1 leírása következik (a beüzemelés, az adatforrások és a számítások azonosak).

## Mi változott a v2-ben

- **Közös alap (`assets/gf.css`, `assets/gf.js`).** A színek, a kártyák, a navigáció, a gombok, a táblázatok, a hint- és állapotelemek közös stílusfájlba kerültek (a 30+ azonos szabály nem másolódik oldalanként). A közös kód: téma, adatállapot, betöltésjelző, táblázatnézet, adatbetöltés. Az oldalspecifikus CSS/JS továbbra is az oldalban van; a rajzoló segédfüggvények (`nice`, `el`, `css`) még oldalanként másolatok (lásd „Ami nincs kész”).
- **Téma.** Rendszerbeállítást követ, és a navigáció végén kézi váltó is van (automatikus / világos / sötét); a választás a böngészőben megmarad, az ábrák váltáskor újrarajzolódnak.
- **Adatállapot minden oldalon.** A fejléc alatt címke mutatja, hogy az adat *valós*, *demo*, *elavult* vagy *részben hiányos*, szöveggel és jellel (nem csak színnel), és mikor frissült. A sáv kizárólag a ténylegesen betöltött fájlból készül: elavult, ha az adatgyűjtés a küszöbnél régebben futott (3 óra; a gáznál 36 óra), a demo adat piros „DEMO ADAT” sávot kap, a hiányzó fájl „Hiányzó adat” sávot. Nincs „élő” jelzés: az ENTSO-E adata nem valós idejű, ezt az oldal ki is írja.
- **Első látogatóknak.** Az Áttekintés „Mit látok?” része rövid magyar fogalomtárat ad (nettó import/export, day-ahead ár és hogy nem a pillanatnyi vagy kiegyenlítő ár, az ENTSO-E késése, MW és MWh); az összecsukott/kinyitott állapotot megjegyzi a böngésző.
- **Hozzáférhetőség (cél: WCAG 2.2 AA).** Ugrólink („Ugrás a tartalomra”), látható fókuszkeret minden vezérlőn, `main` célpont, kontrasztosabb másodlagos szöveg és demo-sáv (a világos téma halvány szürkéje 3,5:1-ről 5,1:1-re, a demo-sáv 3,9:1-ről 5,6:1-re), `prefers-reduced-motion` és kényszerített színek kezelése. Minden idősoros és havi ábra szöveges összefoglalót (`aria-label`: utolsó, legkisebb, legnagyobb érték sorozatonként) és az ábra alatt lenyitható **„Adatok táblázatban”** nézetet kap, ugyanazokkal az értékekkel (hiányzó adat: „nincs adat”, nem nulla). A tooltipek mellett így nem csak egérrel érhető el az információ; az érintés `pointerdown` alapon működik. Az Időjárás oldal ábrái nyílgombokkal is bejárhatók. 320 px szélességen és 200 %-os szövegnagyításnál nincs vízszintes görgetés (táblázatok saját görgetősávban).
- **Betöltés és gyorsítótár.** Betöltés közben „Adatok betöltése…” jelzés látszik, hibánál érthető üzenet. Az adatfájlokat a böngésző feltételes kéréssel (`no-cache`: ETag / Last-Modified) frissíti, nincs `?t=` időbélyeg, ezért változatlan fájlnál 304 válasz jön, a teljes fájl nem töltődik újra; a térképgeometria (`europe-geo.json`, `hu-geo.json`) a böngésző gyorsítótárát használja.
- **Hivatkozások.** Minden belső hivatkozás és fájlút relatív, a projekt `/<repó>/` alútvonala alatt működik (tesztelve).
- **Hibajavítás.** A Földgáz oldal magyar határpont-térképén egy nem létező változóra hivatkozó sor megállította a térkép kirajzolását (Budapest-jelölés nélkül maradt, a hiba a betöltés közben némán elnyelődött); ez javítva.
- **Telepítési változatok.** Az `update.yml` a közzétételbe az `assets/` mappát is másolja. A saját szerveres telepítő (`deploy/install.sh`) és a tárhely-feltöltő (`deploy/upload_ftps.py`, `github-actions-tarhely.yml.example`) szintén kezeli az `assets/` mappát, és már mind az öt oldalt másolja; a feltöltő alkönyvtárat is létrehoz (helyi, TLS-es tesztkiszolgálóval kipróbálva, valódi szolgáltatóval nem).
- **Nem változott:** a nettó import/export előjel-konvenciója (+ import, − export), a mértékegységek, a számítások, az adatgyűjtők és a JSON-mezők, a workflow-k ütemezése. A tesztek mind megvannak, és új böngészős próbák is bekerültek.

## Beállítások az új repóban

1. Titkok (Settings → Secrets and variables → Actions): `ENTSOE_TOKEN` (kötelező), `GIE_API_KEY` (gáz), `HUPX_KEY` (HUPX kiesések, elhagyható). Kulcs nem kerül a kódba.
2. Pages: Settings → Pages → Source: *GitHub Actions*.
3. A `data` ág (a gáz- és a hosszú távú adat tárolója) az első futásokkal jön létre; a régi repó `data` ágát nem viszi át magától semmi. A `gas.json` a gáz-workflow, a `history.json` a heti hosszú távú workflow első sikeres futásáig hiányzik (az oldal ezt kiírja, nem nullát mutat); a frekvencia- és az időjárásfájl az új oldal első közzétételétől épül.
4. Az első futtatás: Actions → „Adatfrissítés és közzététel” → Run workflow.

## Ami nincs kész, vagy nem ellenőrzött

- A közös JS csak a téma, az adatállapot, a betöltés és a táblázatnézet; az ábrázoló segédfüggvények továbbra is oldalanként ismétlődnek.
- A hőtérképek, a földrajzi térképek és a frekvencia-hisztogram összefoglalója a meglévő szöveges `aria-label`; táblázatnézetet az idősoros és havi ábrák kaptak. A térképek értékei szövegesen a térkép feliratain és a táblázatokban is olvashatók.
- Az import/export színe (kék/piros) mellett a nyíl iránya, a szöveges felirat (import/export) és a táblázatnézet is megkülönbözteti az irányt; a nettó-import oszlopdiagram oszlopai szín mellett csak a táblázatnézetben és a tooltipben kapnak szöveges előjelet.
- A diagram-tooltipek billentyűzettel csak az Időjárás oldalon járhatók be; a többi oldalon a táblázatnézet a billentyűzetes megfelelő.
- Az Open-Meteo, a HUPX, a JAO és a fizikai-áramlás alapú nettó import élő működése éles futásig ellenőrizetlen (a sandbox nem éri el ezeket); demo adattal és kitalált klienssel tesztelt.
- A színkontraszt a szöveget érinti; az ábrák sárga/zöld sorozatszíne a világos háttéren a 3:1 alatt lehet, ezért minden ábrán szerepel jelmagyarázat és táblázatnézet.

---

Statikus oldal, amely az ENTSO-E Transparency Platform adataiból mutatja:

- a magyar határokon át mért fizikai áramlást (AT, SK, UA, RO, RS, HR, SI), határonként és nettó import/export bontásban,
- a day-ahead zónaárakat (HU és a szomszédos zónák),
- a nettó importot és a day-ahead árgörbét, az időablak 24 órától 7 napig állítható,
- egy sematikus Magyarország-vázlaton nyilakkal a határonkénti nettó áramlást.

A **Rendszerállapot** (korábban Mérnöki nézet) (`muszaki.html`) ezen túl, szintén ENTSO-E adatokból:

- termelés típusonként (halmozott diagram, a nettó import sraffozva a termelés fölött, a nettó export a nulla alatt, a fogyasztás vonala; összetétel-táblázat, kihasználtság a beépített teljesítményhez), termelés-alapú CO₂-intenzitás becslés és az országok összevetése,
- **ország- és időablak-választó**: a pillanatkép, a termelés, a CO₂, a fogyasztás, a maradék terhelés, a nap/szél, az eltérési ár és az SNSP bármely, a `countries.json`-ban szereplő országra (kb. 17 zóna), 24 órától 7 napig. A nettó import mindenhol a fizikai határkeresztező áramlás összege (a zóna külső határain, befelé mínusz kifelé; több zónából álló csoportnál, például DK, NO, SE, IE, a csoport külső határain), így a termelés, a fogyasztás és a nettó import mérlege kiegyenlített; a határonkénti áramlás, a blokkszintű termelés, a kiesések és az aFRR/mFRR csak Magyarországra készül,
- fogyasztás és day-ahead előrejelzése, az előrejelzési hiba,
- maradék terhelés (fogyasztás − nap − szél), legnagyobb óránkénti emelkedés, nap- és szélelőrejelzés a tényhez képest,
- határkeresztező fizikai és menetrendezett áramlás, a különbségük (hurok- és tranzitáramlás), NTC-kihasználtság, ahol van ilyen adat,
- blokkszintű termelés hőtérképen (100 MW feletti egységek),
- termelői és hálózati kiesések idővonala,
- eltérési ár, aktivált aFRR és mFRR energia, eltérési mennyiség,
- nem-szinkron részarány (SNSP) becslése és importfüggés.

Az **Európai piac** nézet (korábban Európa és trendek) (`europa.html`):

- az európai zónák (kb. 18) day-ahead ára hőtérképen és táblázatban, az árkülönbség a magyar zónához,
- több éves, havi összesítések 2019-től: termelési mix, a napenergia részaránya és csúcsa, negatív árú órák, déli és esti ár, a maradék terhelés déli minimuma és az esti rámpa, évi terhelési tartamgörbe, import határonként, a magyar ár konvergenciája a választott zónákhoz, éves összefoglaló.

Az **Időjárás** nézet (`idojaras.html`, adat: `weather.py` → `weather.json`): a magyar nap- és szélerőművek termelését alakító időjárás, az Open-Meteo ingyenes API-jából (kulcs nélkül, óránként): globális sugárzás (W/m²), szélsebesség 120 m magasságban (m/s), hőmérséklet, felhőzet, csapadék, az elmúlt 3 napra (a modell elemzése) és a következő 5 napra (előrejelzés). A magyar átlag hat település (Budapest, Győr, Pécs, Szeged, Debrecen, Miskolc) egyszerű átlaga, nem termeléssúlyozott. Az ábrákon legfeljebb négy további hely (a hat magyar település és hat szomszédos főváros) kapcsolható be összehasonlításra. A sugárzás és a szél ábrája alatt ugyanazon az időtengelyen látszik az ENTSO-E tényleges és előrejelzett nap-, illetve szél-termelése (MW) az `engineer.json`-ból. Az időablak ±1 nap, ±3 nap vagy a teljes tartomány; minden ábra billentyűzettel (nyílgombok) bejárható, és alatta táblázat is van (helyek, napi összesítés).

Egy Python szkript (`collector.py`) időnként lekéri az adatot, és négy fájlba írja: a `data.json` az áttekintő oldalé, az `engineer.json` a mérnöki nézeté (magyar adatok), a `countries.json` a mérnöki nézet országválasztójáé (más zónák fogyasztása, termelése, nettó pozíciója, eltérési ára), az `europe.json` az európai árakéi. Az alapértelmezett visszatekintés 168 óra (`--hours`), ebből választ az időablak; a blokkszintű termelés (a leglassabb lekérdezés) csak 72 órát kér. Az országadatok időkerete külön állítható (`--countries-budget`, alapból 420 s: a fizikai áramlásokhoz kb. 220 további lekérdezés kell), és `--skip-countries` kihagyja őket. A nettó importot a gyűjtő a szomszédos zónapárok fizikai áramlásából számolja (ENTSO-E 12.1.G). Az ENTSO-E day-ahead nettó pozíciója előjel nélkül érkezik (az `entsoe-py` abszolút értéket ad vissza), ezért nem használható; a gyűjtő csak diagnosztikaként számol egy korrelációt a menetrendi pozíció és a fizikai nettó import között (`netpos_corr`). Az órát csak akkor fogadja el, ha a határok legalább 70 %-ának adata megvan, a hiányos órák üresen maradnak, nem nullák. A lekérdezések párhuzamosan futnak (8 egyszerre), a fontosabbak elöl, minden résznek külön időkerete van (alapból 4 perc), amelynek lejártakor a hátralévő lekérdezések kimaradnak, és a hibák nem akadályozzák egymást. A több éves adatot egy másik szkript (`history.py`) gyűjti, hetente egyszer, külön workflow-ban (`.github/workflows/history.yml`): a hiányzó éveket 2 évenkénti csoportokban, párhuzamos futásokban tölti le, majd egy összefésülő lépés írja a havi összesítést a repó gyökerébe (`history.json`). Az évet csak akkor jelöli lezártnak, ha minden lekérdezése lefutott; a hiányos évet a következő futás újra próbálja. Az első futás után csak a folyó évet frissíti. A gyűjtő workflow-k (gáz, hosszú távú adat) az eredményt nem a `main` ágra, hanem egy külön `data` ágra mentik (`scripts/save_data.sh`), így nem ütköznek a kézi feltöltésekkel; az Adatfrissítés ezt tölti be közzétételkor (`scripts/load_data.sh`), és a mentés után a gyűjtő el is indítja. Az ENTSO-E token csak a szkriptben, a GitHub titkai között él, a böngészőbe nem kerül.

## Beüzemelés GitHub Pages-en

1. **Token.** Az ENTSO-E fiókodban (My Account → Web API Security Token) generálj tokent. Ha nincs ilyen menüpont, a RESTful API hozzáférést a transparency@entsoe.eu címen kell kérni.
2. **Repó.** Hozz létre egy GitHub-repót, és töltsd fel ennek a mappának a tartalmát (a rejtett `.github` mappával együtt). A Pages ingyenesen nyilvános repóval működik.
3. **Titok.** Settings → Secrets and variables → Actions → New repository secret. Név: `ENTSOE_TOKEN`, érték: a token.
4. **Pages.** Settings → Pages → Source: *GitHub Actions*.
5. **Első futtatás.** Actions → „Adatfrissítés és közzététel" → Run workflow. Sikeres futás után az oldal a `https://<felhasználó>.github.io/<repó>/` címen elérhető, utána 20 percenként frissül.

A workflow nem commitol, minden futás új közzétételt készít, így a repó előzménye nem hízik.

## Beüzemelés saját szerveren (GitHub helyett)

Debian vagy Ubuntu alapú gépre (bérelt VPS, vagy Raspberry Pi OS) való. Az 1–2 magos, 1 GB memóriás gép bőven elég.

1. Másold fel a projekt mappáját a szerverre (például `scp -r hu-hatar-aramlas felhasznalo@szerver:`).
2. Futtasd rootként: `sudo ./deploy/install.sh` (IP-címen, HTTP-n), vagy `sudo ./deploy/install.sh adat.pelda.hu` (saját tartománnyal, HTTPS-sel). Tartománynál az A rekord előbb mutasson a szerverre, és a 80-as meg a 443-as port legyen nyitva.
3. A telepítő bekéri az ENTSO-E tokent (nem látszik a képernyőn), `600` jogosultsággal az `/etc/hu-aramlas.env` fájlba menti, majd beállítja a Caddy webszervert és egy systemd időzítőt, ami 15 percenként lefuttatja a gyűjtőt.
4. Ellenőrzés: `systemctl list-timers hu-aramlas.timer`, napló: `journalctl -u hu-aramlas.service -n 50`.

Otthoni gépnél a tartományos HTTPS-hez port-továbbítás kell a routeren; ha ezt nem szeretnéd, a Cloudflare Tunnel használható helyette. Ez a mappa nem tartalmazza a beállítását.

## Beüzemelés webtárhelyen (Rackhost és hasonlók)

Ez a legegyszerűbb út, ha már van vagy venni akarsz egy sima webtárhelyet. A tárhelyen nem kell Python, cron vagy SSH: csak a `index.html`, a `muszaki.html`, a két demo fájl (`demo-data.json`, `demo-engineer.json`) és a `data.json` meg az `engineer.json` kerül rá. Az adatot továbbra is a GitHub gyűjti, és minden futás végén FTPS-en feltölti.

1. Hozz létre egy GitHub-repót a projekttel, és vedd fel a titkot: `ENTSOE_TOKEN` (lásd fent).
2. Kérdezd meg a szolgáltatótól, vagy nézd meg a tárhely adminisztrációs felületén: mi az FTP-szerver címe, van-e **FTPS** (FTP TLS-sel) támogatás, és melyik mappából szolgálja ki a weboldalt (gyakran `public_html` vagy `www`). Egy külön FTP-felhasználót érdemes erre a célra létrehozni.
3. Vedd fel a titkokat: `FTP_HOST`, `FTP_USER`, `FTP_PASS`, és ha kell, `FTP_DIR` (pl. `/public_html`).
4. Másold a `deploy/github-actions-tarhely.yml.example` fájlt a `.github/workflows/update.yml` helyére (felülírva az eredetit), majd az Actions fülön indítsd el kézzel a workflow-t.

A feltöltő szkript (`deploy/upload_ftps.py`) kötelezően titkosítva és ellenőrzött tanúsítvánnyal csatlakozik. Ha a tárhely csak sima FTP-t tud, a szkript hibával leáll, és a jelszó nem megy ki titkosítatlanul. Ilyenkor kérj FTPS-t vagy válts szolgáltatót. A szkriptet helyi, TLS-es teszt FTP-szerverrel próbáltam ki (feltöltés, felülírás, rossz jelszó, nem ellenőrizhető tanúsítvány, hiányzó mappa), valódi szolgáltatóval nem.

Ha a tárhelyen van SSH, cron és Python 3, a gyűjtő közvetlenül ott is futhat: `pip install --user -r requirements.txt`, majd egy 15–20 percenként futó cron-feladat: `ENTSOE_TOKEN=... python collector.py --out /elérési/út/data.json`. Ez a változat nincs kipróbálva.

## Kipróbálás a gépeden

```
pip install -r requirements.txt
export ENTSOE_TOKEN="a-te-tokened"
python collector.py --out data.json
python -m http.server
```

Ezután a `http://localhost:8000` címen az éles adat látszik. A `http://localhost:8000/?demo=1` és a `http://localhost:8000/muszaki.html?demo=1` cím a mellékelt, szintetikus `demo-data.json` és `demo-engineer.json` fájlt tölti be, piros „DEMO ADAT" sávval. Ez csak a kinézet előnézete, nem valós mérés. A demo fájlokat a `python -I tests/make_demo.py` állítja elő.

A `tests/` mappa tesztjei kitalált klienssel ellenőrzik a gyűjtők számítását és hibatűrését (hálózat nélkül): `python -I tests/test_collector.py`, `test_gas.py`, `test_freq.py`, `test_history.py`, `test_hupx.py`, `test_jao.py`, `test_weather.py`. A `tests/test_collector.py` a nettó importot is ellenőrzi: a határonkénti fizikai áramlások összegével kell egyeznie.

A `tests/test_pages.py` böngészős próba (Playwright): mind az öt oldalt megnyitja a demo adattal asztali és mobil méretben, világos és sötét módban, és ellenőrzi, hogy nincs JavaScript-hiba, nincs vízszintes túlcsordulás, megjelenik a tartalom, a csúszka húzása közben nem tűnnek el a mutatógombok, a Rendszerállapot vezérlősávja nem takarja ki az oldalt, az Időjárás oldalon legfeljebb négy hely választható. A v2 próbái ezen felül: kézi témaváltó (megmarad újratöltés után), ugrólink és látható fókusz, minden ábrához összefoglaló és táblázatnézet, a Földgáz térkép teljes kirajzolása, az adatállapotok (friss, elavult, hiányzó fájl, demo) elfogott `data.json` válaszokkal, és a teljes oldalkészlet a `/GridFlow-Analytics-v2/` alútvonal alatt (a gyökér 404-et ad, így a gyökérre mutató hivatkozások kibuknak). Futtatás: `pip install playwright && playwright install chromium`, majd `python -I tests/test_pages.py` (telepített Chrome-mal: `CHROME_PATH=/usr/bin/google-chrome`). Ha a Playwright nincs telepítve, a teszt kihagyja magát. Az Actions nem futtatja, mert a böngésző letöltése lassítaná az óránkénti frissítést.

Minden oldal alján látszik a verzióbélyeg (például „Oldalverzió: 2026-11-24 / 3"). Ha módosítás után a böngésző a régi oldalt mutatja, ezzel lehet ellenőrizni, melyik változat fut.

## Mit érdemes tudni az adatról

- **Nem valós idejű.** A fizikai áramlást az ENTSO-E a rendszerirányítók közlése után teszi közzé, jellemzően órás felbontásban és határonként eltérő késéssel. A fő szám az utolsó olyan óra, amelyre minden elérhető határ adata megvan, az értékek órás átlagok (MW).
- **Előjel.** Pozitív érték import (a szomszédból Magyarországra), negatív export. Egy határ nettó értéke az import és az export különbsége.
- **Az ár day-ahead ár.** A másnapi piac zónaára, nem a pillanatnyi, az intraday vagy a kiegyenlítő energia ára. Az SDAC 2025. október 1. óta 15 perces piaci időegységgel dolgozik, az oldal a forrás felbontását követi.
- **Hiányzó adat.** Egyes határokra vagy zónákra az ENTSO-E nem mindig közöl adatot (jellemzően UA, ritkábban RS ára). Ilyenkor az oldal ezt kiírja, nem pótol és nem becsül.
- **MAVIR.** A MAVIR saját adatait a mavir.hu adatközlő oldala publikálja. Hivatalos, nyilvános API-t nem találtam hozzá, ezért ez az oldal az ENTSO-E-re épül. A MAVIR saját közlése eltérhet ettől.
- **Elavulás.** Ha az adatgyűjtés három óránál régebben futott le, az oldal sárga figyelmeztetést mutat. Sikertelen futásnál az előző közzététel marad élő.
- **Ütemezés leállása.** A GitHub nyilvános repóban 60 nap repóaktivitás nélkül automatikusan kikapcsolja az ütemezett workflow-kat. Ilyenkor az Actions fülön egy kattintással újra lehet engedélyezni, vagy egy új commit is elég.
- **Rendszerállapot: származtatott értékek.** A maradék terhelés, a rámpa, az előrejelzési hiba, a nem menetrendezett áramlás (fizikai − menetrendezett), a CO₂-intenzitás és az SNSP az ENTSO-E közölt adataiból számolt érték, nem hivatalos rendszerirányítói mutató. A CO₂-tényezők az IPCC AR5 WG3 Annex III életciklus-mediánjai (egyéb: 700 g/kWh, becslés), és csak a hazai termelésre vonatkoznak, az importéra nem.
- **Rendszerállapot: ami hiányozhat.** Nem minden adatkör érhető el mindig a magyar zónára: a blokkszintű termelés, az eltérési adatok és a kiesések közlése változó lehet. Ha egy adatkör hiányzik, az oldal kiírja, és nem pótol. A Core régió határain nincs határonkénti nap előtti NTC (flow-based kapacitásszámítás, adata a JAO-n), ezért a kihasználtság-táblázat csak ott jelenik meg, ahol az ENTSO-E közöl NTC-t (jellemzően a szerb határ). A háztartási napelemek nagy része nem szerepel a közölt termelésben.
- **Az első éles futás után ellenőrizd.** A mérnöki lekérdezéseket kitalált klienssel próbáltam ki, valódi ENTSO-E válasszal még nem, ezért az oszlopnevek vagy időfelbontások apró eltéréseit az első éles futás mutatja meg. Az Actions napló kiírja, melyik adatkör van meg és melyik nem, az oldal alján pedig a „Részletek az adatgyűjtésről" megnyitható.
- **Forrásmegjelölés.** Az oldal láblécében szerepel az ENTSO-E Transparency Platform mint forrás. Nyilvános közzététel előtt érdemes elolvasni az ENTSO-E felhasználási feltételeit.

### Térkép, nagyítás, kiegyenlítés (3. kör)

- **Térkép** (`europa.html`): négyzetrácsos (tile-grid) térkép az európai zónákról, váltható mutatóval: a legutóbbi óra day-ahead ára, a különbség a magyar árhoz, a 12 havi átlagár, a negatív árú órák száma 12 hónapra, a termelés-alapú CO₂-intenzitás, a megújuló részarány és a nettó import/export. Az ár az `europe.json`-ból, a 12 havi mutatók a `history.json`-ból, a CO₂/részarány/import a `countries.json`-ból és a magyar zónára az `engineer.json`/`data.json`-ból számolódnak. A térkép betöltése nem lassítja az oldalt: az extra fájlok az első kirajzolás után töltődnek, és ha valamelyik hiányzik, csak az adott mutató tűnik el.
- **Nagyítás:** a Földgáz, a Rendszerállapot, a Határok és az Európai piac oldal grafikonjain egérrel végighúzott szakasz nagyít (a hozzá tartozó grafikonok együtt), dupla kattintás vagy a „Vissza az időablakra" gomb visszaállít. Érintőképernyőn az időablak-gombok és a ◀ ▶ léptetők használhatók.
- **Kiegyenlítés a Rendszerállapot nézetben:** (1) aFRR/mFRR aggregált ajánlatok és aktivált energia az ENTSO-E GL EB 12.3.E adatából (`query_aggregated_bids`, A24 dokumentumtípus; a régi 17.1.E közlés megszűnőben van, azért volt üres az aFRR/mFRR), az aktivált energia ára (17.1.F); (2) a **17.1.I pénzügyi mérleg** (a rendszerirányító havi kiadásai a tartalékokra és az aktivált kiegyenlítő energiára, valamint a nettó eltérés-elszámolási bevétel; havi, helyi pénznemben, a közlés kb. M+3 hónapig késik). Az A01/A02 irányjelölés megfeleltetése (kiadás/bevétel) feltevés; az első éles futás naplója kiírja a nyers szerkezetet, hogy ellenőrizhető legyen.

### Földgáz (`foldgaz.html`, `gas.py`)

A `gas.py` naponta kétszer fut (`.github/workflows/gas.yml`), és a repó gyökerébe írja a `gas.json` fájlt; a 20 perces közzétételi workflow ezt másolja az oldalra. Három forrást használ, egymástól függetlenül: a GIE ALSI platformot (az LNG-terminálok napi készlete GWh-ban, a kiadás a gázrendszerbe GWh/nap, a névleges legnagyobb készlet (DTMI) és referencia-kiadás (DTRS); EU összesen, országonként és terminálonként, a terminálok napi sorozata az utolsó 400 napra; ugyanaz a `GIE_API_KEY` kulcs és `x-key` fejléc, mint az AGSI+-nál; ha az ALSI nem elérhető vagy elutasítja a kulcsot, csak figyelmeztetés készül, a többi rész ettől még frissül), a GIE AGSI+ platformot (tározói töltöttség, tárolt mennyiség, betáplálás és kivétel; ingyenes személyes kulcs kell hozzá, a GitHub titkok közé `GIE_API_KEY` néven, a kulcs a `x-key` fejlécben megy, korlát: 60 hívás/perc) és az ENTSOG átláthatósági platform API-ját (a magyar határpontok fizikai áramlása, kulcs nem kell; a határpontokat a szkript futáskor az `/interconnections` végpontról deríti fel). A tározói adat inkrementális: a második futástól csak az utolsó ~2 hét töltődik újra. Ha az egyik forrás hibázik, a másik adata frissül, a hibás rész előző értéke marad (a `gas.json` `notes` mezője jelzi). A tesztet a `tests/test_gas.py` adja kitalált klienssel (`python -I tests/test_gas.py`), a demó pedig `europa.html?demo=1` címmel nyitható (`demo-gas.json`).


### Hálózati frekvencia a Rendszerállapot nézetben (`muszaki.html`, `freq.py`)

A `freq.py` az Energy-Charts API (Fraunhofer ISE) `/v2/frequency` végpontját használja: a kontinentális európai szinkronterület frekvenciája, 1 másodperces felbontásban, kulcs nélkül (CC BY 4.0, forrásmegjelölés: energy-charts.info). A nyers adatot nem tároljuk: napi (UTC) összesítés készül (átlag, szórás, minimum/maximum időponttal, a ±50 és ±100 mHz-es sávon kívül töltött idő, legnagyobb df/dt, 10 mHz-es hisztogram), plusz az utolsó 24 óra percenkénti min/átlag/max sorozata. A korlát 2 kérés/perc, ezért futásonként legfeljebb 3 nap kérődik (a mai, a tegnapi és egy hiányzó régebbi), a 60 napos visszamenőleges sorozat így néhány óra alatt töltődik fel. Az előző állapotot az `update.yml` az élő oldalról tölti le (`frequency.json`), ezért nincs külön workflow és nincs commit. A tesztet a `tests/test_freq.py` adja (`python -I tests/test_freq.py`), a demó `muszaki.html?demo=1` (`demo-frequency.json`).

## Európai áramlási térkép (4. kör)

- `europa.html`: valódi országhatáros térkép (`europe-geo.json`, Natural Earth alapú) két kártyával: zónatérkép (ár, CO₂ stb.) és **áramlási térkép**.
- Az áramlási térkép a 33 szomszédos zónapár fizikai határkeresztező áramlását (ENTSO-E 12.1.G) mutatja az elmúlt 48 órára; a nyíl vastagsága arányos a MW-tal, a zóna színe a térképen szereplő határok nettó pozíciója. Az óra csúszkával választható.
- Adat: `collector.py` → `collect_europe` → `europe.json` (`flow_ts`, `flows`). Ez kb. 68 további ENTSO-E lekérdezés, ezért a `collect_europe` időkeretét szükség esetén emeld.
- A fizikai áramlás nem a kereskedelmi menetrend; a nyilak egyenes vonalak a zónaközéppontok között, nem a tényleges vezetékek.

## HUPX kiesések (REMIT) és az idősáv-figyelmeztetés (5. kör)

- `hupx.py` a HUPX Inside Information Platformról (`iip.hupx.hu/api/v1/umm`, Bearer-kulcs) kéri le a villamosenergia-kiesések legfrissebb verzióit (7 nappal ezelőttől 45 napra előre), és `hupx.json`-t készít. A Mérnöki nézet "Kiesések a HUPX közlései szerint" kártyája ezt mutatja (Gantt-sáv és táblázat az okkal).
- **Kulcs:** GitHub → Settings → Secrets and variables → Actions → New repository secret, név: `HUPX_KEY`. Kulcs nélkül vagy hiba esetén a lépés kimarad, a kártya nem jelenik meg, a közzététel megtörténik.
- A HUPX feltételei szerint a HUPX-adat továbbhasznosítása szerződéshez kötött lehet; ezt a kulcshoz tartozó feltételek alapján ellenőrizd.
- A Határok és a Mérnöki nézet óránkénti idősáv-választója mellett figyelmeztetés jelenik meg, ha az éles adat rövidebb a választott ablaknál (ilyenkor a hosszabb ablakok ugyanazt mutatják).

## JAO (6. kör, felderítő lépés)

A `jao.py` az első futáskor egy órányi `finalComputation`, `netPos` és `maxExchanges` mintát kér le (kulcs nélkül), és a mezőneveket a workflow logjába ("JAO …: mezők = …") és a `jao_probe.json`-ba írja. A kiesés/terhelés (CNEC) fület ebből építjük a valódi szerkezetre.

## Térképek (7. kör)

- `hu-geo.json` (Natural Earth, a Magyarország körüli kivágás) adja a magyar térképet: Áttekintés (villamos energia: nyilak a határokon, a szomszéd színe a day-ahead árkülönbség) és Földgáz (határpontok, nap csúszkával).
- Az európai áramlási térképen vékony vonalak és ütközésmentes MW-értékek vannak.
- Az Áttekintés árgrafikonjának külön időablaka van (24 órától 60 napig); a gyűjtő az ársort 60 napra tölti le (`price_days`).
- Mobilon a magyar térkép oldalra görgethető, hogy a feliratok olvashatók maradjanak.

## Időjárás (8. kör, `idojaras.html`, `weather.py`)

- **Forrás:** Open-Meteo Forecast API (`api.open-meteo.com/v1/forecast`), kulcs nélkül. Az ingyenes használat **nem kereskedelmi célra** szól; a szolgáltatás adatai CC BY 4.0 licenc alatt állnak, a forrásmegjelölés („Open-Meteo.com") az oldal láblécében és az ábrák alatt szerepel. Kereskedelmi felhasználáshoz fizetős előfizetés kell, ezt az oldal üzleti célú használata előtt rendezni kell.
- **Változók:** `temperature_2m`, `wind_speed_120m` (m/s), `shortwave_radiation` (az előző óra átlaga, W/m²), `cloud_cover`, `precipitation` (az előző óra összege). Idő: UTC, `timeformat=unixtime`; az oldal helyi (budapesti) időben jeleníti meg.
- **Helyek:** 6 magyar település (az átlag ezekből) és 6 szomszédos főváros. Egy kéréssel kérdezi le mindet, a válasz helyenként egy lista. Az `update.yml` a közzététel előtt futtatja (`weather.py --out weather.json`), a hiba nem állítja meg a közzétételt; hibánál az oldal kiírja, hogy az időjárás elavult.
- **Pontosság:** a múltbeli rész modell-elemzés, nem helyszíni mérés; a magyar átlag egyszerű átlag, nem a beépített napelem- és szélerőmű-kapacitás szerint súlyozott. Az időjárás és a tényleges termelés kapcsolatát a leállások, a korlátozások és a háztartási napelemek (amelyek nem szerepelnek az ENTSO-E adatban) is torzítják.
- **Teszt:** `python -I tests/test_weather.py` kitalált klienssel (`tests/fake_weather_client.py`); a demó `idojaras.html?demo=1` (`demo-weather.json`, szintetikus adat, piros „DEMO ADAT" sávval). A valódi Open-Meteo válaszra az első éles futás derít fényt, a sandboxból nem volt elérhető.
