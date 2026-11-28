# 3. szakasz – UX/UI dizájnrendszer és információs architektúra

Jóváhagyott kiindulás: a v2 repó továbbfejlesztése, két ág párhuzamosan (új oldalszerkezet + visszatöltő). A meglévő, működő V1 diagramok és a V2 térkép megmaradnak; az új szerkezet köréjük épül.

## 1. Szerkezet (hét menüpont)

| Menüpont | Fájl | Tartalom |
|---|---|---|
| Kezdőlap | `index.html` | főcím és alcím, kiemelt elemzés, legfrissebb publikációk, a rendszer jelenlegi képe (élő számok), történeti trendek (havi adatból), kiemelt témák, módszertan és források |
| Elemzések | `elemzesek.html`, `elemzesek/<téma>.html` | a tíz téma publikációi rögzített szerkezetben; témaszűrő |
| Rendszerkép | `rendszerkep.html` + részletes nézetek | A–G szekciók élő összefoglalóval; a részletes nézetek a meglévő oldalak: `muszaki.html`, `hatarok.html`, `europa.html`, `idojaras.html`, `foldgaz.html` |
| Historikus adatok | `historikus.html` | ország, kategória, időszak, felbontás, összehasonlítás; letölthető adat |
| Nemzetközi összehasonlítás | `nemzetkozi.html` | AT, SK, RO, RS, HR, SI, UA, DE (DE_LU zóna), CZ; csak összevethető definíciók |
| Módszertan | `modszertan.html` | adatforrások, képletek, aggregálás, minőségi címkék, korlátok |
| Rólunk | `rolunk.html` | célok, függetlenség, kapcsolat, licenc és hivatkozás |

A régi „Határok" oldal (`index.html`) tartalma `hatarok.html` néven él tovább (a Rendszerkép C és D szekciójának részletes nézete), így semmi nem vész el; a régi `index.html` helyére a Kezdőlap kerül.

**Rendszerkép szekciók és a részletes nézetük**

| Szekció | Tartalom | Részletes nézet |
|---|---|---|
| A. Termelés és fogyasztás | terhelés, termelés, előrejelzési hiba | `muszaki.html#cGen`, `#cLoad` |
| B. Termelési mix és megújulók | típusonkénti termelés, nap- és szélrészarány, CO₂ | `muszaki.html#cGen`, `europa.html#cMix`, `idojaras.html` |
| C. Határkeresztező áramlások | fizikai és menetrendezett áramlás, NTC | `hatarok.html`, `muszaki.html#cFlow`, `europa.html#cFmap` |
| D. Árak | day-ahead zónaárak, negatív árak | `hatarok.html`, `europa.html#cZone` |
| E. Stabilitás és frekvencia | frekvencia percenként, napi mutatók, eloszlás | `muszaki.html#fq_cMin` |
| F. Erőművi rendelkezésre állás | blokkszintű termelés, kiesések, HUPX | `muszaki.html#cUnits`, `#cOut` |
| G. Terhelési folyamatok és esti rámpa | maradék terhelés, esti rámpa, kacsagörbe | `muszaki.html#cRes`, `europa.html#cDuck` |
| (kapcsolódó) Földgáz | tározók, LNG, határpontok | `foldgaz.html` |

## 2. Vizuális identitás

- **Jelmondat:** „Safety first. Power always." – a fejlécben és a Rólunk oldalon, díszítés nélkül.
- **Színek (világos):** mélykék `#0a2342` (fejléc, jelmondat-sáv), sötétkék `#134074` (hivatkozás, aktív elem), fehér `#ffffff`, világosszürke `#f3f5f7` (oldalháttér), türkiz `#0e9aa7` (kiemelő vonal, jelzés), zöld `#2f8f5b` (megújuló, rendben), visszafogott narancs `#c9741f` (figyelmeztetés, ár). Sötét módban saját, külön lépések (mélykék háttér, világos türkiz kiemelés), nem automatikus színfordítás.
- **Diagramszínek:** a validált, színtévesztés-biztos kategóriaskála (`--c1…--c8`) változatlan marad; a márka színei a keretet adják, a sorozatok azonosítását nem veszik át. Az állapotszínek (zöld, narancs, piros) mellett mindig jel és szöveg áll.
- **Betű:** rendszerbetű (nincs külső betűtípus, nincs külső kérés). Címek: félkövér, szűkebb betűköz; a publikációk törzsszövege 17–18 px, 68 karakteres sorhosszal (magazinszerű olvasás).
- **Elrendezés:** 1100 px-es oszlop; a publikációknál 720 px-es szövegoszlop + szélesebb ábrák. Mobilon egy oszlop, az ábrák vízszintesen nem görgetnek, a táblázat igen.

## 3. Közös komponensek

1. **Fejléc és navigáció** (`GF.shell`): márkanév, jelmondat, hét menüpont, téma-váltó; az aktuális menüpont `aria-current`. A Rendszerkép részletes nézetein második sor: Áttekintés · Határok és árak · Rendszerállapot · Európai piac · Időjárás · Földgáz.
2. **Adatminőségi címke** (`GF.q`): Végleges · Előzetes · Becsült · Számított · Hiányzó. Jel + szöveg, soha nem csak szín. Meghatározása a Módszertanban; a címke a Módszertan megfelelő pontjára mutat.
3. **Forrássor** minden kártyán (`data-src`), és a hist adatnál a minőségi címke + utolsó adat időpontja.
4. **Adatállapot** (valós / demo / elavult / hiányos): ugyanaz, mint a v2-ben.
5. **Ábra + táblázatnézet + CSV**: minden ábrához lenyitható táblázat; a Historikus modulban CSV-letöltés.
6. **Publikációs sablon**: lásd lent.
7. **Számkártya** (kezdőlap, rendszerkép): érték, mértékegység, időpont, minőségi címke.

## 4. Publikációs sablon (rögzített szerkezet)

Minden elemzés ugyanezt a tíz részt tartalmazza, ebben a sorrendben: **Kérdés · Rövid összefoglaló · Adatok · Módszer · Elemzés · Ábrák · Értelmezés · Következtetések · Korlátok · Források.** A számokat a `publish.py` az adatból számolja építéskor (nem kézzel beírt szám), a szöveg a számított értékekből áll össze; ha egy adat hiányzik, a publikáció ezt a „Korlátok" részben kimondja, és nem tölti ki becsléssel.

A tíz téma: (1) importfüggőség, (2) napenergia részaránya, (3) napenergia és esti rámpa, (4) negatív HUPX-árak, (5) szomszédos zónák árai, (6) termelési mix átalakulása, (7) megújulók és szabályozás, (8) kiesések és importigény, (9) CO₂-intenzitás, (10) szezonális fogyasztás- és termelési trendek.

## 5. Hozzáférhetőség és teljesítmény

Billentyűzetes használat, látható fókusz, ugrólink, szöveges összefoglaló és táblázat minden ábrán, kontraszt WCAG AA, `prefers-reduced-motion` és `forced-colors` figyelembevétele; ezek a v2 alapjai, az új oldalak ezeket öröklik. Az oldalak relatív útvonalakat használnak (alkönyvtárban is működnek); minden adatfájlt a `manifest.json` hash-e alapján, tartósan gyorsítótárazva kér a böngésző.

## 6. Ami nem része ennek a körnek

Valós idejű jelzés; kereskedelmi funkciók; külső betűtípus, analitika vagy hirdetés; fizetős vagy hitelesítést kérő külső szolgáltatás (ilyet csak előzetes jóváhagyással vezetek be).
