"""Az erőművi nyilvántartás (plants.json) és építője (build_plants.py) tesztje – hálózat nélkül.

Ellenőrzi:
  - a plants.json szerkezetét, az azonosítók egyediségét, a koordináták magyarországi tartományát, a források ellenőrző összegét,
  - hogy a párosító tövek ékezet nélküli kisbetűs ASCII szövegek, és nincs két erőmű azonos tövvel (különben kétértelmű lenne a párosítás),
  - hogy a nyilvántartás nem tartalmaz kitalált elemet: minden erőműnek van forrása, azonosítója a forrásban, és szélerőmű sincs (nincs hiteles forrás),
  - hogy a build() csak a magyarországi, szerkesztett listán szereplő, teljes adatú sorokat veszi át (szintetikus CSV-kkel).

Futtatás:  python -I tests/test_plants.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)           # -I módban sem kerül be automatikusan; a build_plants a gyökérben van
FAIL = []


def check(ok, msg):
    print(("  ok   " if ok else "  HIBA ") + msg)
    if not ok:
        FAIL.append(msg)


def main():
    with open(os.path.join(ROOT, "plants.json"), encoding="utf-8") as f:
        d = json.load(f)
    plants = d["plants"]

    print("[plants.json]")
    check(d.get("schema") == 1 and isinstance(d.get("note"), str) and "tájékoztató" in d["note"], "a séma és a „tájékoztató” megjegyzés megvan")
    check(len(plants) == 22, "22 erőmű (%d)" % len(plants))
    check(len({p["id"] for p in plants}) == len(plants), "az azonosítók egyediek")
    need = {"id", "name", "name_src", "fuel", "capacity_mw", "lat", "lon", "match", "src"}
    check(all(need <= set(p) for p in plants), "minden erőműnek megvannak a kötelező mezői")
    check(all(p["fuel"] in d["fuels"] for p in plants), "minden erőmű energiaforrása ismert csoport")
    check(all(isinstance(p["capacity_mw"], (int, float)) and p["capacity_mw"] > 0 for p in plants), "a beépített teljesítmény pozitív szám")
    check(all(45.7 <= p["lat"] <= 48.6 and 16.0 <= p["lon"] <= 22.9 for p in plants), "minden koordináta Magyarország befoglaló téglalapján belül van")
    check(abs(sum(p["capacity_mw"] for p in plants) - 6338) < 5, "az összteljesítmény ≈ 6338 MW (%.0f)" % sum(p["capacity_mw"] for p in plants))
    check(not any(p["fuel"] == "wind" for p in plants), "nincs szélerőmű (nincs hozzá hiteles, koordinátás nyílt forrás) – nem találtunk ki egyet sem")
    check(all(p["src"].get("db") and p["src"].get("id") for p in plants), "minden erőműnek van forrásadatbázisa és forrásazonosítója")
    check({p["src"]["db"] for p in plants} <= {s["name"] for s in d["sources"]}, "minden erőmű forrása szerepel a források listájában")
    check(all(s["license"] == "CC BY 4.0" and re.fullmatch(r"[0-9a-f]{64}", s["sha256"]) and s["url"].startswith("https://") for s in d["sources"]),
          "a források: CC BY 4.0, sha256 ellenőrző összeggel, hivatkozható URL-lel")
    stems = [t for p in plants for t in p["match"]]
    check(all(re.fullmatch(r"[a-z0-9 ]+", t) for t in stems), "a párosító tövek ékezet nélküli kisbetűs ASCII szövegek")
    check(len(stems) == len(set(stems)), "két erőműnek nincs azonos párosító töve")
    # egyik tő sem lehet másik tőnek a része (különben egy ENTSO-E név két erőműre illeszkedne)
    nested = [(a, b) for a in stems for b in stems if a != b and a in b]
    check(not nested, "nincs egymásba ágyazott tő %s" % nested[:3])
    check(all(not p["src"].get("capacity_year") or 1990 <= p["src"]["capacity_year"] <= 2030 for p in plants), "a közölt adatév hihető tartományban van")
    solar_named = [p for p in plants if p["fuel"] == "solar"]
    check(all(p["match"] == [] for p in solar_named), "a naperőműveknek nincs névpárosítása (az ENTSO-E egységadatban 100 MW alatt nem szerepelnek)")

    print("[build_plants.build]")
    import build_plants as B
    gppd_head = "country,gppd_idnr,name,primary_fuel,capacity_mw,latitude,longitude,commissioning_year,owner,source,geolocation_source,year_of_capacity_data\n"
    gppd = gppd_head + "\n".join([
        "HUN,WRI1020246,Paks,Nuclear,1886.8,46.5739,18.8536,1982,,ENTSOE,WRI,",
        "HUN,WRI9999999,Kitalalt,Gas,300,47.0,19.0,,,X,WRI,",                      # nincs a szerkesztett listában -> kimarad
        "HUN,WRI1020248,Matra,Coal,,47.8,19.9,,,ENTSOE,WRI,",                       # hiányzó teljesítmény -> kimarad
        "HUN,WRI1020247,Tiszai,Gas,864,,,,,ENTSOE,WRI,",                            # hiányzó koordináta -> kimarad
        "AUT,WRI1020249,Dunamenti,Gas,840,47.3,19.0,,,ENTSOE,WRI,",                 # nem magyar -> kimarad
        "HUN,WRI1020250,Gonyu,Wind,426.6,47.7,17.8,,,ENTSOE,WRI,",                  # a szerkesztett listán szerepel, ezért bekerül (a tüzelőanyag-leképezés ismeri a szelet)
    ])
    jrc_head = "id,name,country_code,lat,lon,installed_capacity_MW,type\n"
    jrc = jrc_head + "\n".join([
        "H1188,Kiskore hungary power plant,HU,47.5,20.5,28,HDAM",
        "H0001,Valami,HU,47.0,19.0,10,HDAM",                                         # nincs a listán -> kimarad
        "H3403,Tiszalok hungary power plant,AT,47.0,21.0,13.5,HROR",                 # nem HU -> kimarad
        "H3404,Ikervar hungary power plant,HU,,16.9,1.8,HROR",                       # hiányzó koordináta -> kimarad
    ])
    out = B.build(gppd.encode("utf-8"), jrc.encode("utf-8"))
    ids = [p["id"] for p in out]
    check(set(ids) == {"WRI1020246", "WRI1020250", "JRC-H1188"}, "csak a magyarországi, listán szereplő, teljes adatú sorok kerülnek be %s" % ids)
    check(ids == sorted(ids, key=lambda i: -[p for p in out if p["id"] == i][0]["capacity_mw"]), "az erőművek teljesítmény szerint csökkenő sorrendben vannak")
    pk = [p for p in out if p["id"] == "WRI1020246"][0]
    check(pk["name"] == "Paksi Atomerőmű" and pk["fuel"] == "nuclear" and pk["match"] == ["paks"] and pk["commissioned"] == 1982, "a Paks sor a szerkesztett névvel és tövvel épül")
    check(pk["src"]["db"] == "WRI Global Power Plant Database" and pk["src"]["capacity_basis"] == "ENTSOE", "a forrás és a kapacitás-alap megőrződik")
    hy = [p for p in out if p["id"] == "JRC-H1188"][0]
    check(hy["fuel"] == "hydro" and hy["src"]["db"] == "JRC Hydropower database" and hy["capacity_mw"] == 28, "a JRC vízerőmű vízerőműként, a forrás jelölésével épül")

    print("\n%s" % ("MINDEN OK" if not FAIL else "%d HIBA:\n  - " % len(FAIL) + "\n  - ".join(FAIL)))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
