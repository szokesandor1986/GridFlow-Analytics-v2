import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hupx
from fake_hupx_client import FakeHupx

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
nosleep = lambda s: None


def ok(n, msg): print(f"{n} OK  {msg}")


f = FakeHupx(now=NOW)
r = hupx.collect(f, "k", now=NOW, sleep=nosleep)
assert r["errors"] == [], r["errors"]
assert f.calls == 3 and r["pages"] == 3, f.calls              # 8 elem / 3 = 3 oldal
assert f.last_params[0]["energyTypes"] == "ELECTRICITY" and f.last_params[0]["status"] == "ACTIVE"
assert "cursor" not in f.last_params[0] and f.last_params[1]["cursor"] == "3"
assert f.last_params[0]["eventFrom"] == "2026-11-17" and f.last_params[0]["eventTo"] == "2027-01-08"
ok(1, "lapozás nextCursorral, szűrők")
assert r["count"] == 6, r["count"]                           # duplikátum és a GWh/d elem kiesik
names = [o["name"] for o in r["items"]]
assert len(set(names)) == len(names) and "DEMO egység 5" not in names
o = next(x for x in r["items"] if x["name"] == "DEMO egység 4")
assert o["open_end"] and o["end"] is None
o1 = next(x for x in r["items"] if x["name"] == "DEMO egység 1")
assert o1["planned"] and o1["avail_mw"] == 125 and o1["nominal_mw"] == 250 and o1["reason_hu"] == "Tervezett karbantartás"
assert next(x for x in r["items"] if x["name"] == "DEMO egység 3")["planned"] is False
ok(2, "átalakítás: duplikátum, nem MW egység, nyitott vég, tervezett/nem tervezett")
f = FakeHupx(now=NOW, fail_500=2)
r = hupx.collect(f, "k", now=NOW, sleep=nosleep)
assert r["errors"] == [] and r["count"] == 6
ok(3, "átmeneti 500 után újrapróbálás")
f = FakeHupx(now=NOW, fail_500=99)
r = hupx.collect(f, "k", now=NOW, sleep=nosleep)
assert r["pages"] == 0 and r["errors"] and f.calls == 3
ok(4, "tartós 500: 3 próba, hibaüzenet")
f = FakeHupx(now=NOW, key="jo")
r = hupx.collect(f, "rossz", now=NOW, sleep=nosleep)
assert r["pages"] == 0 and f.calls == 1 and "401" in r["errors"][0]
ok(5, "401: nem próbálkozik újra")
print("MINDEN TESZT ÁTMENT")
