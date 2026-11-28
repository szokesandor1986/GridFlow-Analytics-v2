# 1. szakasz – Audit (2026. november 27.)

Az audit három forrásra épül: a helyi forráskódra (v1 + v2), az élő repó `data` ágára (valódi `history.json` és `gas.json`, kiolvasva), és a workflow-k fájljaira. Az élő oldalakat és az ENTSO-E API-t a munkakörnyezetből nem értem el, ezért az „élő” adatok (óránkénti pillanatkép, frekvencia, HUPX, JAO, időjárás) tartalmát csak a kódból és a demo fájlokból ismerem.

## 1. Fő megállapítás: ami van, az havi összesítés, nem többéves idősor

A rendszer valóban több évre visszamenő ENTSO-E adatot tart, de **kizárólag havi összesítésben**. A nyers óránkénti (vagy 15 perces) adat a letöltés után eldobódik, mert a `history.py` csak a havi rekordot őrzi meg. Ezért a kért „Historikus adatok” modul napi, heti, órás vagy 15 perces felbontásban **ma nem tud kiszolgálni** semmit a régi időszakból; ahhoz új adattár és visszatöltés (backfill) kell. Ez az új fejlesztés fő technikai kockázata.

## 2. Adatleltár

### 2.1 Historikus adat (`history.json`, a `data` ágon)

| Tulajdonság | Érték (az élő fájlból) |
|---|---|
| Időszak | 2019-01 – 2026-11, 95 hónap; 2019–2025 lezárt év, 2026-11 részleges |
| Felbontás | havi (helyi, budapesti hónapok); az éves rekord csak a terhelési tartamgörbét és a beépített teljesítményt tartalmazza |
| Méret | 156 kB (28 kB tömörítve) |
| Frissítés | hetente (hétfő 04:23 UTC), a folyó évet; a lezárt éveket nem tölti újra |
| Forrás | ENTSO-E Transparency Platform; a CO₂ tényezők IPCC AR5 életciklus-mediánok |
| Zónák | 18: HU, AT, SK, RO, HR, SI, RS, CZ, DE_LU, PL, BG, IT_NORD, FR, CH, NL, BE, ES, GR (csak ár-adat, lásd lent) |

Mit tartalmaz egy havi rekord:

- **Magyar termelés** típusonként (GWh): `nuclear, gas, coal, bio, hydro, solar, wind, other`; a nap csúcsteljesítménye (`solar_peak`, MW).
- **Fogyasztás**: energia (`load_gwh`), átlag, csúcs, minimum (MW).
- **Maradék terhelés**: déli minimum (`res_min_mid`) és az esti rámpa 99. percentilise (`ramp_p99`, MW/h).
- **Day-ahead ár** (HU): átlag, minimum, maximum, szórás, negatív órák száma, déli és esti átlagár, érvényes órák száma (`n`).
- **Határkeresztező**: nettó import határonként (AT, SK, UA, RO, RS, HR, SI; GWh) és összesen (`imp_gwh`).
- **18 zóna ára**: havi átlagár, negatív órák, korreláció a magyar árral, azonos árú órák aránya – **csak ár**, termelési mix vagy fogyasztás a szomszédokra nincs.
- **Éves**: terhelési tartamgörbe (21 kvantilis), beépített teljesítmény típusonként.

Ismert hiányok a tényleges fájlban:

- 2019-01 – 2019-07: a nap-csúcsteljesítmény (`solar_peak`) nincs; a termelés néhány típusa hiányos; a maradékterhelés-mutatók (`res_min_mid`) 2019 első hét hónapjában, a `ramp_p99` 2019 első nyolc hónapjában nincsenek. Ez az ENTSO-E akkori adatlefedettségéből ered; ezeket üresen, nem nullaként kell kezelni.
- Szlovénia határárama (`border.SI`) 95-ből 42 hónapban hiányzik.
- Az ENTSO-E nem jelöli a végleges és az előzetes adatot; a rendszer a hónapot „részlegesnek” jelöli, ha nincs teljes lefedettség.
- A 2026-11 hónap részleges (565 az érvényes ár-óra a lehetséges ~720-ból).

### 2.2 Élő (rövid távú) adatok

| Fájl | Tartalom | Ablak / felbontás | Frissítés |
|---|---|---|---|
| `data.json` | HU határáramlások, nettó import, day-ahead árak | 168 óra, óránkénti | 20 percenként |
| `engineer.json` | HU termelés típusonként, fogyasztás és előrejelzés, nap/szél előrejelzés, fizikai és menetrendezett áramlás, blokkszintű termelés, kiesések, kiegyenlítés, CO₂, beépített teljesítmény | ~8,5 nap, óránkénti | 20 percenként |
| `countries.json` | 57 zóna/ország: termelés, fogyasztás, nettó import (fizikai áramlásból), CO₂ | ~8,5 nap, óránkénti | 20 percenként |
| `europe.json` | zónaárak és áramlások az európai térképhez | 96 óra | 20 percenként |
| `frequency.json` | hálózati frekvencia (Fraunhofer ISE / energy-charts, CC BY 4.0), napi mutatók | 60 nap napi, 5 perces percadat | 20 percenként |
| `hupx.json` | HUPX közlemények (kiesések) | aktuális | 20 percenként |
| `weather.json` | Open-Meteo időjárás, 6 magyar hely + 6 szomszéd főváros | −3 / +5 nap, óránkénti | 20 percenként |
| `gas.json` | AGSI+ tározók, ALSI LNG, ENTSOG határpontok | 2021-10 – 2026-11-26 (1883 nap), napi | naponta kétszer |

Méret: `gas.json` 1,4 MB (340 kB tömörítve); a többi élő fájl a demo változatok alapján 0,05–1,2 MB.

**Felbontás.** Minden gyűjtő a nyers adatot óránkéntire átlagolja (`hourly_mean`); a 15 perces ENTSO-E adat sehol sem marad meg. A day-ahead ár 2025. október 1-je óta 15 perces elszámolási időszakú az európai day-ahead piacon, ezt a jelenlegi rendszer tudatosan nem kezeli (az órás átlag helyes, de a 15 perces ár nem érhető el).

### 2.3 Mi számított és mi közvetlen

| Mutató | Eredet |
|---|---|
| Termelés típusonként, fogyasztás, ár, fizikai és menetrendezett áramlás, kiesések, kiegyenlítési adat | közvetlen ENTSO-E közlés (óránkéntire átlagolva) |
| Nettó import | **számított**: a zóna külső határainak fizikai áramlás-összege (befelé mínusz kifelé); az óra csak akkor érvényes, ha a határok ≥70 %-ának van adata |
| Maradék terhelés, esti rámpa, SNSP, importfüggés, CO₂-intenzitás, éves tartamgörbe, korrelációk | **számított** a fenti adatokból |
| CO₂-intenzitás | termelésalapú; a tényezők IPCC AR5 életciklus-mediánok (fogyasztásalapú, import-korrigált nincs) |
| Frekvencia | külső forrás (nem ENTSO-E) |

## 3. Működő funkciók (megőrzendő)

A v1 és a v2 azonos adatszerkezeten fut; a v2 csak megjelenésben, hozzáférhetőségben és közös kódban tér el. Az alábbi nézetek mind működnek demo adattal (böngészős tesztekkel igazolva), az élő működés a megjegyzett kivételekkel igazolt:

- **Áttekintés**: magyar áramlási térkép, határonkénti áramlás, nettó import 48 óra, day-ahead zónaárak, „Mit látok?” bevezető, adatállapot.
- **Rendszerállapot (mérnöki)**: frekvencia (24 óra, napi mutatók, eloszlás, legnagyobb kilengések), termelés típusonként, fogyasztás tény és előrejelzés, maradék terhelés és esti rámpa, fizikai és menetrendezett határáramlás, blokkszintű termelés, kiesések (ENTSO-E és HUPX), rendszeregyensúly (aFRR/mFRR), SNSP és importfüggés, ország-/zónaválasztó (57 zóna), időablak és órás csúszka.
- **Európai piac**: európai zónatérkép (7 mérőszám, időablak), áramlási térkép, havi termelés, nap térnyerése, árak összevetése, „kacsagörbe”, terhelési tartamgörbe, import/export határonként, éves összefoglaló.
- **Földgáz**: tározók töltöttsége, betáplálás/kivétel, LNG-terminálok, határpontok térkép, szomszédok és az EU.
- **Időjárás**: nap, szél, hőmérséklet, felhőzet és csapadék, ENTSO-E tény/előrejelzés mellette.
- Közös: PNG-mentés, nagyítható térképek, tooltip, táblázatnézet (v2), témaváltó, adatállapot.

Élő működésben **nem ellenőrzött**: az Open-Meteo lekérdezés, a HUPX, a JAO, az új zónák élő adata és a fizikai áramlásból számolt nettó import (a munkakörnyezet ezeket nem éri el; demo és kitalált klienses tesztek igazolják a logikát).

## 4. Technikai korlátok

1. **GitHub Pages**: csak statikus fájl; nincs adatbázis, nincs szerveroldali lekérdezés. Az oldal mérete 1 GB, a közzétételi artifact is ennyire korlátos; a GitHub puha ajánlása óránként kb. 10 építés (jelenleg 3 óránként).
2. **ENTSO-E API**: tokenenként percenként 400 kérés; a legtöbb dokumentumtípus egy kérésben legfeljebb egy évet ad; a token titok (GitHub Secret), a munkakörnyezetből az API nem érhető el, ezért a visszatöltést a felhasználó repójában, GitHub Actions-ben lehet futtatni.
3. **A `data` ág** egyetlen commitba kényszerített (force-push) állapot, így nincs történet-növekedés; ez jó a nagy, gyakran változó fájloknak, de a nagy historikus adat minden pushnál újra feltöltődik.
4. **Közzététel**: minden telepítés a teljes `dist/` mappát feltölti; a jelenlegi ~5 MB-nál ez gyors, 30–50 MB-nál lassúbb, de járható.
5. **Böngésző**: egy 8 évnyi óránkénti, több zónás adat nem tölthető be egyben; részleges betöltés (zóna × év × kategória) szükséges.

## 5. Mit érdemes átvenni, mit újratervezni

**Átvenni változtatás nélkül:** az összes gyűjtő és teszt (`collector.py`, `gas.py`, `freq.py`, `hupx.py`, `jao.py`, `weather.py`, `history.py`), a `data` ágas tárolás és a workflow-k ütemezése, a nettó import fizikai-áramlás alapú számítása, az adatállapot-logika, a közös `assets/gf.css` és `assets/gf.js`, az ábrázoló kód (SVG, tooltip, PNG-mentés), a térképgeometria.

**Újratervezni:**

- **Navigáció és információs szerkezet**: öt eszközcentrikus fül (Határok, Rendszerállapot, Európai piac, Időjárás, Földgáz) → hét témacentrikus oldal (Kezdőlap, Elemzések, Rendszerkép, Historikus adatok, Nemzetközi összehasonlítás, Módszertan, Rólunk).
- **A historikus adattár**: havi összesítésről többfelbontású, particionált idősor-tárra (lásd a 2. szakaszt).
- **Publikációs réteg**: ma nincs; új, adatból épülő, ellenőrizhető elemzések.
- **Közös JS**: a rajzoló segédfüggvények oldalanként másolatok; a bővítés előtt érdemes modulba szervezni.

## 6. Az új követelmények és a jelenlegi adat találkozása

Mely kért kérdésre adható már ma **valódi** adat (havi felbontásban, 2019-től):

| Kérdés | Ma megválaszolható? | Forrás-mező |
|---|---|---|
| Az importfüggőség alakulása az elmúlt években | igen (havi, éves) | `imp_gwh`, `load_gwh` |
| A napelemes termelés növekedése, részarány | igen | `gen.solar`, `load_gwh`, `inst` |
| A termelési mix átalakulása | igen | `gen.*` |
| Negatív HUPX árak gyakorisága | igen (óraszám havonta) | `price.neg_h`; a hossz és az egymás utáni órák **nem** |
| Szomszédos zónaárak összevetése | igen (havi átlag, korreláció) | `z` |
| Esti rámpa és a nap kapcsolata | részben (havi p99, 2019 eleje nélkül) | `ramp_p99`, `res_min_mid`, `solar_peak` |
| Nyári és téli fogyasztási profil | részben (terhelési tartamgörbe, havi átlag/csúcs); **napszakos profil nem** | `ldc`, `load_*` |
| CO₂-intenzitás hosszú távú alakulása | igen (termelésalapú, a magyar termelésből) | `gen.*`, `co2.factors` |
| Napelemes többlet és export kapcsolata | **nem** (óránkénti adat kell) | – |
| Szabályozási igény trendje | **nem** (nincs historikus kiegyenlítési adat) | – |
| Erőművi kiesések és importigény | **nem** (nincs historikus kiesési adat) | – |
| Szomszédok termelési mixe, napszázaléka, CO₂-ja | **nem** (a 18 zónára csak ár van) | – |
| Hányszor és mennyi ideig volt negatív az ár | részben (óraszám igen, hossz nem) | `price.neg_h` |

Összegzés: a tíz kért publikációs téma közül **hat–hét valódi havi adatból már most megírható**; a többihez (óránkénti, szabályozási, kiesési, nemzetközi mix) új, visszatöltött adat kell.
