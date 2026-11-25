"""Szintetikus DEMO adat az oldalak előnézetéhez. NEM valós mérés.

A collector.py saját függvényein át készül, egy kitalált ENTSO-E klienssel (tests/fake_client.py),
ezért a séma pontosan megegyezik az éles fájlokéval. A kimenetben "demo": true.

Használat:  python -I tests/make_demo.py            (a projekt mappájába: demo-data.json, demo-engineer.json)
"""
import importlib.util
import json
import pathlib
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
spec = importlib.util.spec_from_file_location("collector", ROOT / "collector.py")
col = importlib.util.module_from_spec(spec)
spec.loader.exec_module(col)
from fake_client import FakeClient  # noqa: E402

NOW = pd.Timestamp("2026-11-23 13:20", tz="Europe/Budapest").tz_convert("UTC")
client = FakeClient(NOW)

main = col.collect(client, now=NOW, hours=168)
main["demo"] = True
main["source"] = "DEMO – szintetikus adat, nem valós mérés"
col.write_json(str(ROOT / "demo-data.json"), main)

eng = col.collect_engineer(client, now=NOW, hours=168, main=main)
eng["demo"] = True
eng["source"] = "DEMO – szintetikus adat, nem valós mérés"
col.write_json(str(ROOT / "demo-engineer.json"), eng)

eu = col.collect_europe(client, now=NOW)
eu["demo"] = True
eu["source"] = "DEMO – szintetikus adat, nem valós mérés"
col.write_json(str(ROOT / "demo-europe.json"), eu)

cn = col.collect_countries(client, now=NOW, hours=168)
# a kitalált kliens minden zónára ugyanazt a mintát adja; a demóban az erőműpark-összetételt zónánként eltoljuk,
# hogy a CO2-összevetés és az országváltás látványa valósághűbb legyen
TILT = {"FR": {"nuclear": 5.0, "gas": 0.3, "coal": 0.05}, "DE_LU": {"coal": 6.0, "wind": 9.0, "nuclear": 0.0, "solar": 3.0},
        "PL": {"coal": 14.0, "nuclear": 0.0, "gas": 0.4}, "CH": {"hydro": 40.0, "nuclear": 3.0, "gas": 0.0, "coal": 0.0},
        "AT": {"hydro": 25.0, "nuclear": 0.0, "coal": 0.0}, "SK": {"nuclear": 4.0, "coal": 0.6}, "CZ": {"coal": 5.0, "nuclear": 3.0},
        "RO": {"hydro": 18.0, "coal": 3.0, "nuclear": 2.0, "wind": 6.0}, "ES": {"wind": 12.0, "solar": 6.0, "nuclear": 2.0, "gas": 1.2},
        "HR": {"hydro": 10.0, "nuclear": 0.0, "coal": 0.2}, "SI": {"hydro": 8.0, "nuclear": 4.0}, "BG": {"coal": 6.0, "nuclear": 3.0},
        "NL": {"gas": 2.2, "wind": 5.0, "nuclear": 0.0, "coal": 0.5}, "BE": {"nuclear": 4.0, "gas": 1.5, "wind": 3.0}}
for z, rec in cn["zones"].items():
    for g, m in TILT.get(z, {}).items():
        if g in rec.get("generation", {}):
            rec["generation"][g] = [None if v is None else round(v * m, 2) for v in rec["generation"][g]]
cn["demo"] = True
cn["source"] = "DEMO – szintetikus adat, nem valós mérés"
col.write_json(str(ROOT / "demo-countries.json"), cn)
print("országok:", len(cn["zones"]), "| hibák:", len(cn["errors"]))

sys.modules["collector"] = col
hspec = importlib.util.spec_from_file_location("history", ROOT / "history.py")
hist = importlib.util.module_from_spec(hspec)
hspec.loader.exec_module(hist)
from fake_history_client import FakeHistoryClient  # noqa: E402
h = hist.collect_history(FakeHistoryClient(NOW), now=NOW, from_year=2019, workers=8)
h["demo"] = True
h["source"] = "DEMO – szintetikus adat, nem valós mérés"
col.write_json(str(ROOT / "demo-history.json"), h)
print("europe zónák:", sorted(eu["zones"]), "| history hónapok:", len(h["months"]))

print("ok | utolsó teljes óra:", main["last_complete_ts"], "| fő hibák:", main["errors"], "| mérnöki hibák:", eng["errors"])
print("modulok:", {k: v for k, v in eng["modules"].items()})

# gáz fül: kitalált AGSI+/ENTSOG kliens
from datetime import date as _date  # noqa: E402
gspec = importlib.util.spec_from_file_location("gas", ROOT / "gas.py")
gas = importlib.util.module_from_spec(gspec)
gspec.loader.exec_module(gas)
from fake_gas_client import FakeHttp  # noqa: E402
g = gas.collect(FakeHttp(_date(2026, 11, 23)), "demo", None, today=_date(2026, 11, 23), throttle=gas.Throttle(gap=0))
g["demo"] = True
g["source"] = "DEMO – szintetikus adat, nem valós mérés"
(ROOT / "demo-gas.json").write_text(json.dumps(g, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print("gáz: napok", len(g["agsi"]["dates"]), "| pontok", len(g["flows"]["points"]), "| hibák", g["errors"])

# frekvencia fül: kitalált Energy-Charts kliens (60 nap, mai nap 13:20 UTC-ig)
from datetime import datetime as _dt, timezone as _tz  # noqa: E402
fspec = importlib.util.spec_from_file_location("freq", ROOT / "freq.py")
fq = importlib.util.module_from_spec(fspec)
fspec.loader.exec_module(fq)
from fake_freq_client import FakeEnergyCharts  # noqa: E402
_now = _dt(2026, 11, 23, 13, 20, tzinfo=_tz.utc)
fr, _ = fq.collect(FakeEnergyCharts(_now), None, _now.date(), fq.Throttle(gap=0), max_fetch=60, keep_days=60)
fr["demo"] = True
fr["source"] = "DEMO – szintetikus adat, nem valós mérés"
(ROOT / "demo-frequency.json").write_text(json.dumps(fr, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print("frekvencia: napok", len(fr["daily"]), "| hibák", fr["errors"])

# HUPX IIP (REMIT) kiesések: kitalált kliens
hspec = importlib.util.spec_from_file_location("hupx", ROOT / "hupx.py")
hx = importlib.util.module_from_spec(hspec)
hspec.loader.exec_module(hx)
from fake_hupx_client import FakeHupx  # noqa: E402
_hn = _dt(2026, 11, 23, 13, 20, tzinfo=_tz.utc)
hj = hx.collect(FakeHupx(n=9, page=4, now=_hn), "k", now=_hn)
hj["demo"] = True
hj["source"] = "DEMO – szintetikus adat, nem valós közlemény"
(ROOT / "demo-hupx.json").write_text(json.dumps(hj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print("hupx: kiesések", hj["count"], "| hibák", hj["errors"])

# ---- időjárás (Open-Meteo formátumú, kitalált)
wspec = importlib.util.spec_from_file_location("weather", ROOT / "weather.py")
wx = importlib.util.module_from_spec(wspec)
wspec.loader.exec_module(wx)
from fake_weather_client import FakeOpenMeteo  # noqa: E402
wd = wx.collect(FakeOpenMeteo(pd.Timestamp("2026-11-23 12:20", tz="UTC").to_pydatetime()), now=pd.Timestamp("2026-11-23 12:20", tz="UTC").to_pydatetime())
wd["demo"] = True
wd["source"] = "DEMO – szintetikus adat, nem valós időjárás"
wx.write_json(str(ROOT / "demo-weather.json"), wd)
print("időjárás: helyek", len(wd["places"]), "| hibák", wd["errors"])
