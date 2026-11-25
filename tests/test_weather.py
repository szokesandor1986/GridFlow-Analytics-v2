"""A weather.py tesztje kitalált klienssel, hálózat nélkül.  Futtatás:  python -I tests/test_weather.py"""
import importlib.util
import json
import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
spec = importlib.util.spec_from_file_location("weather", ROOT / "weather.py")
wx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wx)
from fake_weather_client import FakeOpenMeteo  # noqa: E402

NOW = datetime(2026, 11, 23, 12, 20, tzinfo=timezone.utc)

# 1. normál futás: minden hely, minden változó, egységes időrács, nincs hiba
h = FakeOpenMeteo(NOW)
d = wx.collect(h, now=NOW)
assert len(d["places"]) == len(wx.PLACES) == 12 and d["errors"] == [], d["errors"]
assert len(d["ts"]) == (3 + 5) * 24 and d["ts"][0] == "2026-11-20T00:00:00Z", (len(d["ts"]), d["ts"][0])
assert all(set(p["hourly"]) == set(wx.VARS) and all(len(v) == len(d["ts"]) for v in p["hourly"].values()) for p in d["places"])
url, params = h.calls[0]
assert len(h.calls) == 1 and params["timeformat"] == "unixtime" and params["wind_speed_unit"] == "ms" and params["timezone"] == "UTC"
assert params["latitude"].count(",") == 11
print("1 OK  lekérés és felépítés")

# 2. a magyar átlag a hat magyar hely átlaga; a szomszédok nincsenek benne
hu = d["hu"]["temperature_2m"]
i = 40
vals = [p["hourly"]["temperature_2m"][i] for p in d["places"] if p["group"] == "hu"]
assert len(vals) == 6 and abs(hu[i] - sum(vals) / 6) < 0.06, (hu[i], vals)
print("2 OK  magyar átlag")

# 3. fizikai ésszerűség: éjjel nincs sugárzás, nappal van; a csapadék nem negatív; szél pozitív
rad = d["hu"]["shortwave_radiation"]
assert rad[0] == 0 and max(rad) > 150, (rad[0], max(rad))
assert min(d["hu"]["precipitation"]) >= 0 and min(d["hu"]["wind_speed_120m"]) > 0
print("3 OK  ésszerűség")

# 4. hiba esetén kivétel (a main() ilyenkor a meglévő fájlt nem bántja)
try:
    wx.collect(FakeOpenMeteo(NOW, fail=True), now=NOW)
    raise SystemExit("hibát kellett volna dobnia")
except RuntimeError:
    pass
# hiányzó változó: a hely megmarad, a hiba bekerül a naplóba
d2 = wx.collect(FakeOpenMeteo(NOW, drop_var="cloud_cover"), now=NOW)
assert any("cloud_cover" in e for e in d2["errors"]) and "cloud_cover" not in d2["places"][0]["hourly"]
# hiányzó (null) érték nem rontja az átlagot
items = FakeOpenMeteo(NOW).get("x", {"latitude": ",".join(f"{p[4]}" for p in wx.PLACES), "longitude": ",".join(f"{p[5]}" for p in wx.PLACES), "past_days": 3, "forecast_days": 5})
items[0]["hourly"]["temperature_2m"][10] = None
d3 = wx.build(items, wx.PLACES, NOW)
assert d3["hu"]["temperature_2m"][10] is not None and d3["places"][0]["hourly"]["temperature_2m"][10] is None
json.dumps(d, allow_nan=False)
print("4 OK  hibakezelés")

# 5. main(): sikertelen lekérés nem írja felül a meglévő fájlt
import tempfile, os  # noqa: E402
tmp = pathlib.Path(tempfile.mkdtemp()) / "weather.json"
tmp.write_text('{"keep":1}', encoding="utf-8")
orig = wx.Http
wx.Http = lambda: FakeOpenMeteo(NOW, fail=True)
sys.argv = ["weather.py", "--out", str(tmp)]
assert wx.main() == 0 and json.loads(tmp.read_text(encoding="utf-8")) == {"keep": 1}
wx.Http = lambda: FakeOpenMeteo(NOW)
assert wx.main() == 0 and json.loads(tmp.read_text(encoding="utf-8"))["source"] == "Open-Meteo.com"
wx.Http = orig
print("5 OK  main(): a hiba nem rontja a meglévő fájlt")
print("MINDEN TESZT ÁTMENT")
