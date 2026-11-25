"""A gas.py tesztje kitalált klienssel, hálózat nélkül.  Futtatás:  python -I tests/test_gas.py"""
import importlib.util
import json
import pathlib
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
spec = importlib.util.spec_from_file_location("gas", ROOT / "gas.py")
gas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gas)
from fake_gas_client import FakeHttp  # noqa: E402

TODAY = date(2026, 11, 23)
FROM = "2023-10-01"          # a teszthez rövidebb (a valódi alapérték 2021-10-01)
fast = gas.Throttle(gap=0)


def run(http, existing=None, key="demo"):
    return gas.collect(http, key, existing, today=TODAY, from_date=FROM, throttle=fast, budget_s=60)


# 1. alapfutás
h = FakeHttp(TODAY)
out = run(h)
a, f = out["agsi"], out["flows"]
assert a and f, out["errors"]
assert a["dates"][0] == FROM and a["dates"][-1] == "2026-11-22", (a["dates"][0], a["dates"][-1])
assert len(a["dates"]) == len(set(a["dates"]))
assert set(a["series"]) == {"EU", *gas.AGSI_COUNTRIES}, set(a["series"])
hu = a["series"]["HU"]
assert set(hu) == set(gas.FULL_FIELDS) and set(a["series"]["AT"]) == set(gas.LITE_FIELDS)
assert all(len(v) == len(a["dates"]) for s in a["series"].values() for v in s.values())
assert 0 < hu["full"][-1] < 100 and hu["wgv"][-1] == 67.0
assert [x["name"] for x in a["facilities"]][:2] == ["MFGT (DEMO)", "HEXUM (DEMO)"], a["facilities"]
# lapozás: ~1150 nap / 300 = 4 oldal / sorozat
assert sum(1 for u, p in h.calls if "agsi" in u and p.get("country") == "HU") == 4
print("1 OK  tározó:", len(a["dates"]), "nap, HU töltöttség", hu["full"][-1], "%")

# 2. határpontok: csak a magyar oldal, 6 pont, GWh/nap
assert len(f["points"]) == 6, [p["id"] for p in f["points"]]
assert {p["country"] for p in f["points"]} == {"AT", "SK", "RO", "HR", "RS", "UA"}
assert all("OTHER" not in p["id"] for p in f["points"])
rs = next(p for p in f["points"] if p["country"] == "RS")
assert rs["side"] == "entry" and 40 < rs["gwh"][-1] < 250, rs["gwh"][-1]      # kWh/d -> GWh/nap átváltás
assert len(f["days"]) >= 399 and all(len(p["gwh"]) == len(f["days"]) for p in f["points"])
print("2 OK  pontok:", [p["label"] for p in f["points"]])

# 3. inkrementális második futás: csak az utolsó napok kérdeződnek le
h2 = FakeHttp(TODAY)
out2 = run(h2, existing=json.loads(json.dumps(out)))
calls_hu = [p for u, p in h2.calls if "agsi" in u and p.get("country") == "HU"]
assert len(calls_hu) == 1 and calls_hu[0]["from"] >= "2026-11-01", calls_hu
assert out2["agsi"]["dates"] == a["dates"] and out2["agsi"]["series"]["HU"]["full"] == hu["full"]
print("3 OK  inkrementális: 1 oldal / ország")

# 4. kulcs nélkül: nincs tározó, de az áramlás megvan
out3 = run(FakeHttp(TODAY), key="")
assert out3["agsi"] is None and out3["flows"] and any("GIE_API_KEY" in e for e in out3["errors"])
assert out3["lng"] is None                    # kulcs nélkül az ALSI-t sem hívjuk
print("4 OK  kulcs nélkül")

# 5. hibás kulcs: érthető kilépés
try:
    run(FakeHttp(TODAY, key="jo"), key="rossz")
    raise AssertionError("nem lépett ki")
except SystemExit as e:
    assert "GIE_API_KEY" in str(e)
print("5 OK  hibás kulcs")

# 6. ENTSOG leáll: a tározó marad, az előző áramlási adat megmarad
out4 = run(FakeHttp(TODAY, fail_entsog=True), existing=out)
assert out4["agsi"] and out4["flows"] == out["flows"] and any("ENTSOG" in e for e in out4["errors"])
assert any("előző futás" in n for n in out4["notes"])
print("6 OK  ENTSOG-hiba után megmarad a régi áramlás")

# 7. egy ország kiesik: a többi megvan
out5 = run(FakeHttp(TODAY, fail_agsi_country=("AT",)))
assert "AT" not in out5["agsi"]["series"] and "HU" in out5["agsi"]["series"]
print("7 OK  egy ország hibája nem visz el mindent")

# 8. tartalék felderítés: ha az operatorpointdirections nem elérhető, az interconnections is elég
out6 = run(FakeHttp(TODAY, no_opd=True))
assert out6["flows"] and len(out6["flows"]["points"]) == 6
assert not any("Belső" in p["label"] for p in out["flows"]["points"])   # belső (nem határ) pont kimarad
print("8 OK  tartalék felderítés")

# 9. LNG (ALSI): EU + országok + terminálok, GWh és GWh/nap
L = out["lng"]
assert L, out["errors"]
assert L["dates"][0] == FROM and L["dates"][-1] == "2026-11-22" and len(L["dates"]) == len(set(L["dates"]))
assert set(L["series"]) >= {"EU", "ES", "HR", "PL", "GR", "IT", "GB"}, set(L["series"])
assert all(set(s) == set(gas.LNG_FIELDS) and len(s["inv"]) == len(L["dates"]) for s in L["series"].values())
assert L["names"]["HR"] == "Horvátország" and L["names"]["EU"] == "EU összesen"
assert len(L["fac"]) == 21 and len(L["fac_dates"]) == gas.LNG_FAC_DAYS, (len(L["fac"]), len(L["fac_dates"]))
assert all(len(x["inv"]) == len(L["fac_dates"]) == len(x["send"]) for x in L["fac"])
krk = next(x for x in L["fac"] if x["country"] == "HR")
assert krk["type"] == "FSRU" and krk["lat"] == 45.22 and krk["lon"] == 14.57 and krk["company"].startswith("LNG Croatia")
assert krk["latest"]["date"] == "2026-11-22" and krk["latest"]["dtmi"] > krk["latest"]["inv"] > 0
# a terminálok összege = az EU-s országos adat (GB nélkül) az utolsó napra
eu_send = sum(x["send"][-1] for x in L["fac"] if x["country"] != "GB")
assert abs(eu_send - L["series"]["EU"]["send"][-1]) < 1.5, (eu_send, L["series"]["EU"]["send"][-1])
assert L["fac"][0]["latest"]["dtmi"] >= L["fac"][-1]["latest"]["dtmi"]          # DTMI szerint csökkenő sorrend
print("9 OK  LNG:", len(L["series"]), "sorozat,", len(L["fac"]), "terminál, EU kiadás", L["series"]["EU"]["send"][-1], "GWh/nap")

# 10. LNG inkrementális: országonként egy oldal, ugyanaz az eredmény
h3 = FakeHttp(TODAY)
out7 = run(h3, existing=json.loads(json.dumps(out)))
al = [p for u, p in h3.calls if "alsi" in u]
assert len(al) == len(L["series"]), len(al)      # EU + minden ország, mind 1 oldal
assert all(p["from"] >= "2026-11-01" for p in al), al[:3]
assert out7["lng"]["dates"] == L["dates"] and out7["lng"]["series"]["EU"]["send"] == L["series"]["EU"]["send"]
assert [x["inv"] for x in out7["lng"]["fac"]] == [x["inv"] for x in L["fac"]]
print("10 OK  LNG inkrementális:", len(al), "hívás")

# 11. ALSI leáll: a tározó és az áramlás marad, a régi LNG megmarad (jelezve); régi nélkül üres
out8 = run(FakeHttp(TODAY, fail_alsi=True), existing=out)
assert out8["agsi"] and out8["flows"] and out8["lng"] == out["lng"] and any("ALSI" in e for e in out8["errors"])
assert any("lng: most nem sikerült" in n for n in out8["notes"])
out9 = run(FakeHttp(TODAY, fail_alsi=True))
assert out9["lng"] is None and out9["agsi"] and out9["flows"]
print("11 OK  ALSI-hiba nem viszi el a többit")

# 12. az ALSI-kulcs elutasítva (403): nem áll le a futás, csak jelzi
out10 = run(FakeHttp(TODAY, alsi_key="mas"))
assert out10["agsi"] and out10["flows"] and out10["lng"] is None and any("ALSI" in e and "403" in e for e in out10["errors"]), out10["errors"]
print("12 OK  ALSI 403 -> figyelmeztetés, a futás megy tovább")

print("MINDEN TESZT ÁTMENT")
