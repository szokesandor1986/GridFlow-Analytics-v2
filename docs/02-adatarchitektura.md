# 2. szakasz – Adatarchitektúra-terv (javaslat, jóváhagyásra)

Ez a terv javaslat: a döntési pontokat a végén sorolom fel, a megvalósítás ezek után indul. Minden szám becslés, amelyet az első visszatöltés valódi mérete felülír.

## 1. Alapelvek

1. **Négy réteg, külön felelősséggel**: gyűjtés → tárolás → feldolgozás → megjelenítés. A frontend csak a kész, particionált fájlokat olvassa; sem API-kulcsot, sem nyers letöltést nem tartalmaz.
2. **A nyers adat időbélyege mindig UTC**, szabályos rácson tárolva. A helyi (budapesti) idő csak megjelenítéskor és a napi/heti/havi csoportosításkor számít. Így a nyári és téli időszámítás váltása nem sérti az adatot: a 23 és 25 órás napokat a csoportosítás kezeli.
3. **Hiányzó adat `null`, soha nem nulla.** Minden összesítés rögzíti, hány elemi értékből készült (`n`, lefedettség).
4. **Mértékegység és forrás minden sorozatnál rögzítve**, az aggregálási szabály is a sorozat leírásában van, nem a kódban rejtve.
5. **A meglévő fájlok és API-kapcsolatok megmaradnak.** A `history.json` (havi) tovább él; az új tár mellé épül.

## 2. Tárolási formátum

**Döntés a böngészős olvasásra: partícionált, oszlopos JSON, UTC rácson.** A Parquet a háttérfeldolgozásban jó, de a böngészőben külön WebAssembly-olvasót igényelne (új külső függőség); a GitHub Pages az ismétlődő számokat tartalmazó JSON-t átviteli tömörítéssel (gzip) szolgálja ki, a mérete így elfogadható.

Könyvtárszerkezet a `data` ágon, és ugyanígy a közzétett oldalon:

```
hist/
  manifest.json                  # a teljes tár indexe (lásd lent), kicsi, mindig friss
  catalog.json                   # sorozatleírások: kategória, mértékegység, aggregálás, forrás, minőség
  h/{ZONA}/{ÉV}/{kategória}.json # óránkénti (UTC rács), zóna × év × kategória
  q/{ZONA}/{ÉV}/{kategória}.json # 15 perces, csak ahol a forrás natív 15 perces és kértük
  d/{ZONA}.json                  # napi összesítés az összes évre (helyi nap), kicsi
  m/{ZONA}.json                  # havi összesítés (a jelenlegi history.json mezői + újak)
  y/{ZONA}.json                  # éves összesítés
```

Egy óránkénti partíció:

```json
{
  "schema": 1, "zone": "HU", "category": "generation", "year": 2024,
  "t0": 1704067200, "step": 3600, "n": 8784,          // UTC epoch másodperc, a rács szabályos
  "unit": "MW", "agg": "mean", "source": "ENTSO-E A75",
  "series": { "nuclear": [1812, 1809, null, ...], "solar": [0, 0, ...], ... },
  "quality": { "nuclear": "final", "solar": "final" },
  "generated_utc": "2026-11-27T04:30:00Z", "coverage": { "nuclear": 0.998 }
}
```

- `t0` + `step` + index adja az időt, nincs külön időbélyeg-tömb (fele méret).
- Szökőév: 8784 pont; a rács UTC-ben mindig szabályos, a DST miatti hiányzó/ismétlődő helyi óra nem jelenik meg tárolási hibaként.
- Az értékek egész MW-ra, ár esetén egy tizedesre kerekítve (a forrás pontossága ennyit tesz lehetővé).
- A `manifest.json` minden fájlhoz tartalmaz tartalmi hash-t és időszak-lefedettséget; a frontend `?v=<hash>` alapján kéri a fájlt, így a lezárt évek fájljait a böngésző tartósan gyorsítótárazza, és csak a folyó év fájlja töltődik újra.

**Kategóriák** (a kért A–G csoportokkal): `generation` (termelés típusonként), `load` (terhelés tény), `load_forecast` (előrejelzés, a hiba a kettőből számolható), `price_da` (day-ahead ár), `flow_physical` és `flow_scheduled` (határonként, MW), `net_import` (számított, MW), `balancing` (szabályozási energia), `outages` (kiesések: tervezett és nem tervezett, MW), `installed` (beépített teljesítmény, éves), `frequency` (külső forrás, percadatból napi mutatók), `co2` (számított).

**Zónák**: a kért kör HU, AT, SK, RO, RS, HR, SI, UA, DE_LU, CZ. A **bidding zone és az ország külön azonosító**: a kulcs mindig a zóna ENTSO-E kódja (DE_LU, IT_NORD, DK_1…), az ország megjelenítési csoport. A `catalog.json` rögzíti a zóna–ország hozzárendelést, és az összehasonlító nézet csak azonos definíciójú sorozatot állít egymás mellé (például a németországi termelés zónája DE_LU, nem „Németország”).

## 3. Méretbecslés

Alap: 10 zóna × 8 év (2019–2026) × kb. 25 óránkénti sorozat × ~8 760 óra ≈ 17,5 millió érték.

| Tárolási mód | Becsült méret (tömörítés előtt) | Átvitel (gzip) |
|---|---|---|
| Óránkénti JSON, egész/1 tizedes értékek | ~70–100 MB | ~15–25 MB összesen |
| 15 perces, csak HU utolsó 2 év (~12 sorozat) | ~12 MB | ~3 MB |
| Napi összesítés, 10 zóna, minden év | ~5 MB | ~1 MB |

A felhasználó **soha nem tölti le az egészet**: egy ország, egy év, egy kategória óránkénti fájlja várhatóan 80–250 kB (gzip: 20–60 kB). A napi és havi összesítő néhány száz kB. Az oldal és a közzétételi csomag így a GitHub Pages 1 GB-os határa alatt marad, de az óránkénti tár kb. 70–100 MB-ra növeli a közzétételi artifactot (lásd a döntési pontokat).

## 4. Feldolgozás és aggregálás szabályai

A `aggregate.py` (új) a sorozat `agg` leírása szerint számol, nem egységesen:

| Mennyiség | Mértékegység | Idő szerinti összevonás | Megjegyzés |
|---|---|---|---|
| Termelés, terhelés, áramlás, nettó import | MW (teljesítmény) | átlag; a minimum és a maximum külön mezőben | az energia = átlag × a periódus tényleges órái; hiányzó órák nem nullák |
| Energiamennyiség (GWh) | MWh | **összeg** | csak ott, ahol a forrás energiát ad; teljesítményből számolt energiánál az órák száma a tényleges, nem 24 |
| Day-ahead ár | €/MWh | időátlag (egyenlő súly); a terhelés-súlyozott átlag külön számított mutató | a negatív órák száma és hossza külön, nem az átlagból |
| Frekvencia | Hz | átlag, szórás, minimum, maximum, a ±50/±100 mHz-en kívüli idő aránya | a statisztika percadatból számolt; átlagos frekvencia önmagában félrevezető |
| CO₂-intenzitás | gCO₂eq/kWh | **termeléssel súlyozott átlag**, nem az intenzitások átlaga | termelésalapú; fogyasztásalapú csak ha az import zónánkénti intenzitása is ismert |
| Beépített teljesítmény | MW | éves állapot, nem átlagolható | |
| Kiesések | MW | átlag a periódusra; kezdet/vég időpontokkal | |

**Időkezelés.**

- A napi, heti, havi, éves csoportosítás **Europe/Budapest** helyi idő szerint történik minden zónára (egységes összevethetőség); a 23 és 25 órás napok a tényleges óraszámmal számolnak. A keleti zónák (RO, BG, GR, UA) helyi ideje egy órával eltér, ez az oldalon fel van tüntetve.
- A heti csoport ISO-hét (hétfő az első nap).
- Év/év összevetés: azonos naptári nap (február 29. kihagyva vagy külön jelölve), azonos hét, azonos hónap, azonos napszak (helyi idő szerinti óra). A szökőév a hónap/év óraszámában jelenik meg.
- **Lefedettség**: ha egy összevont periódusban az elemi értékek kevesebb mint 70 %-a áll rendelkezésre, az érték `null`, nem becsült.

**Minőségi állapot** (`quality`): a forrásrétegből minden sorozatnak van állapota.

| Állapot | Jelentés |
|---|---|
| `final` / „közölt” | az ENTSO-E közlése; az ENTSO-E nem jelöli a véglegességet, ezért a GridFlow konvenciója: a 90 napnál régebbi adat „közölt”, az újabb „előzetes” |
| `preliminary` | az utolsó 90 nap; később módosulhat |
| `calculated` | a GridFlow számolta (nettó import, CO₂, maradék terhelés, rámpa); a képlet a Módszertan oldalon és a `catalog.json`-ban |
| `estimated` | becsült érték (jelenleg csak az „egyéb” termelés CO₂-tényezője); mindig külön jelölve |
| `missing` | nincs adat; az idősorban `null` |

## 5. Frissítési folyamat

1. **Napi frissítés** (`hist-update.yml`, éjszakánként): az utolsó 14 nap újralekérése minden (zóna × kategória) párra (az ENTSO-E utólag javít), a folyó év partíciójainak újraírása, a napi/havi/éves összesítők újraszámolása, `manifest.json` frissítése.
2. **Visszatöltés** (`hist-backfill.yml`, kézi indítás és csoportos futás): zóna × év szerinti mátrix, ugyanazzal a mintával, mint a mostani `history.yml` (párhuzamos gépek, részeredmény artifact, összefésülés egy commitban). Ami nem sikerült, azt a következő futás újra próbálja. A `--plan` a hiányzó (zóna, év, kategória) hármasokat adja.
3. **Lezárt évek**: egy évnél régebbi partíciót csak kézi felülvizsgálat ír újra; a manifest hash-e változatlan marad, így a böngésző gyorsítótára érvényes.
4. **Közzététel**: a `data` ág `hist/` mappáját az `update.yml` a `dist/hist/` alá másolja (ugyanúgy, mint ma a `history.json`-t). A nagy, ritkán változó partíciók miatt a közzétételt érdemes csak akkor újrafuttatni, ha a `hist/` hash-e változott (a jelenlegi 20 perces élő futás nem érinti).
5. **Hibatűrés**: egy sorozat letöltési hibája nem állítja meg a futást; a hiány a `manifest.json`-ban és az oldal adatállapotában látszik.

A visszatöltés kb. 700–1 500 ENTSO-E kérést jelent; a percenkénti 400-as korlát mellett ez néhány perctől fél óráig tart gépenként. **A visszatöltést csak a felhasználó repójában lehet elindítani** (kell hozzá az `ENTSOE_TOKEN` titok); a munkakörnyezetből az ENTSO-E nem érhető el.

## 6. Lekérdezési logika a böngészőben

1. A `manifest.json` betöltése (kicsi) → kiderül, mely (zóna, kategória, év) elérhető és milyen lefedettséggel.
2. A felhasználó választása (ország, kategória, időszak, felbontás, összehasonlítás) → a szükséges partíciók listája:
   - **Napi, heti, havi, éves felbontás** és hosszú időszak: a `d/`, `m/`, `y/` összesítők (egy-egy kis fájl).
   - **Óránkénti** és legfeljebb néhány hónap: az érintett év(ek) `h/` partíciója.
   - **15 perces**: a `q/` partíció, csak ha létezik; különben a felület kiírja, hogy nincs natív 15 perces adat, nem interpolál.
3. A betöltött partíciók memóriában maradnak; a letöltés csak a hiányzó darabot kéri.
4. A kért felbontás finomabb is lehet a tárolt felbontásnál? Nem: a felület csak durvább vagy azonos felbontást kínál, és megmondja, ha a választott időszak egy része hiányos.
5. A letöltés gomb a megjelenített sorozatot CSV-ben adja (UTC és helyi idő oszlop, mértékegység, forrás, minőség).

## 7. Mi nem ígérhető

- **Valós idejű frissítés**: a GitHub Pages és az ENTSO-E késése miatt a legfrissebb adat 20 perc–néhány óra késésű; az oldal ezt kiírja. Nincs „élő” jelzés.
- **Napi, órás vagy 15 perces felbontás a 2019 óta tartó időszakra a visszatöltés lefutása előtt**: ma csak havi adat van.
- **Egyes adatkategóriák teljes időszaka**: az ENTSO-E nem minden zónára és évre közöl minden kategóriát (például Ukrajna adata a 2022 utáni időszakban nem teljes); a leltár az első visszatöltés után készül el a tényleges lefedettséggel.
- **Fogyasztásalapú CO₂-intenzitás**: csak az import zónánkénti intenzitásával számolható; első körben termelésalapú.

## 8. Döntési pontok (a megvalósítás előtt)

1. **Hol tárolódjon és hogyan szolgálódjon ki az óránkénti tár?** (a) a közzétett Pages-oldalon, a repóval együtt (ajánlott: nincs külső függőség, nincs költség, ~70–100 MB); (b) a `data` ágról külső CDN-en át (jsDelivr): kisebb Pages-csomag, de külső szolgáltatástól függ; (c) külső objektumtár: hitelesítés és esetleg költség, ezért nem javaslom.
2. **Mekkora mélységű és felbontású legyen a visszatöltés?** (a) 2019-től óránkénti adat 10 zónára, 15 perces csak HU utolsó 2 évre (ajánlott); (b) szűkebb: HU és 5 szomszéd, 2022-től; (c) csak napi összesítés a szomszédokra, óránkénti HU-ra.
3. **Hová épüljön?** A v2 repó továbbfejlesztése (ajánlott: a v2 a vizuális referencia, nincs újabb repó és Pages-beállítás) vagy külön v3 repó.
4. **Ütemezés.** A két fő rész párhuzamosan haladhat: (A) az új oldalszerkezet, dizájnrendszer, Kezdőlap, Rendszerkép és a Historikus modul a már meglévő, valódi havi adattal és az első publikációkkal; (B) a visszatöltő és az óránkénti tár, amelyet a felhasználó repójában kell elindítani és a tényleges lefedettséggel ellenőrizni.
