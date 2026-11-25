"""A freq.py tesztje kitalált klienssel, hálózat nélkül.  Futtatás:  python -I tests/test_freq.py"""
import importlib.util
import json
import pathlib
import sys
from datetime import datetime, timezone

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
spec = importlib.util.spec_from_file_location("freq", ROOT / "freq.py")
fq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fq)
from fake_freq_client import EVENT, FakeEnergyCharts, series_for  # noqa: E402

NOW = datetime(2026, 11, 23, 13, 20, tzinfo=timezone.utc)
TODAY = NOW.date()
fast = fq.Throttle(gap=0)

# 1. kézzel ellenőrizhető statisztika: állandó 50,000 Hz, benne egy 50,060 Hz-es 100 s-os szakasz
t = np.arange(0, 86400, dtype=float)
f = np.full(len(t), 50.0)
f[1000:1100] = 50.06
s = fq.day_stats(t, f)
assert s["n"] == 86400 and s["cov"] == 1.0 and s["max"] == 50.06 and s["min"] == 50.0
assert abs(s["out50"] - 100 / 86400 * 100) < 0.001 and s["out100"] == 0.0, s
assert sum(s["hist"]) == 86400 and len(s["hist"]) == len(fq.HIST_LABELS) == 42
assert s["hist"][21] == 86400 - 100 and s["hist"][27] == 100        # 0..10 mHz és 60..70 mHz sáv
assert abs(s["dfdt"] - 6.0) < 0.01, s["dfdt"]                       # 60 mHz / 10 s = 6 mHz/s
print("1 OK  napi statisztika")

# 2. v2 és v1 válasz ugyanazt adja, a hibás értékek kimaradnak
h = FakeEnergyCharts(NOW)
js2 = h.get("https://x/v2/frequency", {"start": "2026-11-20T00:00Z", "end": "2026-11-20T00:09:59Z"})
js1 = h.get("https://x/frequency", {"start": "2026-11-20T00:00Z", "end": "2026-11-20T00:09:59Z"})
t2, f2 = fq.parse_series(js2)
t1, f1 = fq.parse_series(js1)
assert len(f2) == 600 and np.allclose(f1, f2) and np.allclose(t1, t2)
js2["data"][5]["values"]["frequency"] = None
js2["data"][6]["values"]["frequency"] = 12.0
assert len(fq.parse_series(js2)[1]) == 598
print("2 OK  v2 / v1 értelmezés")

# 3. teljes gyűjtés: mai, tegnapi és pótlandó napok, percsorozat
out, got = fq.collect(FakeEnergyCharts(NOW), None, TODAY, fast, max_fetch=5, keep_days=10)
assert got == 5 and len(out["daily"]) == 5, (got, sorted(out["daily"]))
assert str(TODAY) in out["daily"] and out["daily"][str(TODAY)]["cov"] < 0.6          # a mai nap csak 13:20-ig van
m = out["minute"]
assert len(m["mean"]) == 1440 and m["min"][-1] is not None and m["t0"].startswith("2026-11-22T13:2")
assert any("hiányzik" in n for n in out["notes"])
print("3 OK  gyűjtés:", sorted(out["daily"]))

# 4. második futás: csak a mai és a tegnapi + a hiányzók; a már megvalós napok nem kérdeződnek le újra
h2 = FakeEnergyCharts(NOW)
out2, got2 = fq.collect(h2, json.loads(json.dumps(out)), TODAY, fast, max_fetch=4, keep_days=10)
asked = sorted(p["start"][:10] for _, p in h2.calls)
assert asked[-1] == str(TODAY) and len(asked) == 4 and len(set(asked)) == 4, asked
assert len(out2["daily"]) == 7, len(out2["daily"])
assert not set(asked) & set(sorted(out["daily"])[:3]), "lezárt napot újra kért"
print("4 OK  inkrementális:", len(out2["daily"]), "nap")

# 5. a kitalált erőműkiesés látszik a statisztikában
ev = datetime.fromtimestamp(EVENT, tz=timezone.utc).date()
out3, _ = fq.collect(FakeEnergyCharts(NOW), None, ev, fast, max_fetch=2, keep_days=3)
d = out3["daily"][str(ev)]
assert d["min"] < 49.86 and d["min_ts"].startswith(str(ev) + "T08:14"), d
assert d["dfdt"] > 3, d["dfdt"]
print("5 OK  kilengés észlelve:", d["min"], "Hz", d["min_ts"], "df/dt", d["dfdt"], "mHz/s")

# 6. 429 -> Retry-After szerint újrapróbál; v1 tartalék; üres nap hibaként jelenik meg
o4, g4 = fq.collect(FakeEnergyCharts(NOW, rate_limit_first=True), None, TODAY, fast, max_fetch=1, keep_days=3)
assert g4 == 2 and not o4["errors"]      # a mai és a tegnapi nap mindig kérdezett
o5, g5 = fq.collect(FakeEnergyCharts(NOW, v1_only=True), None, TODAY, fast, max_fetch=1, keep_days=3)
assert g5 == 2
o6, g6 = fq.collect(FakeEnergyCharts(NOW, empty_days=[str(TODAY)]), None, TODAY, fast, max_fetch=2, keep_days=3)
assert any(str(TODAY) in e for e in o6["errors"]) and (TODAY - __import__("datetime").timedelta(days=1)).isoformat() in o6["daily"]
print("6 OK  429, v1 tartalék, üres nap")

print("MINDEN TESZT ÁTMENT")
