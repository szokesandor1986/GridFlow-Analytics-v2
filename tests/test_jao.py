import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jao

class H:
    def __init__(s, fail=None): s.fail, s.calls = fail or {}, []
    def get(s, url, params=None, headers=None, timeout=1):
        s.calls.append((url, params)); k = url.rsplit("/", 1)[-1]
        st = s.fail.get(k)
        if st:
            e = RuntimeError(f"HTTP {st}"); e.status_code = st; e.retry_after = 1; raise e
        if k == "monitoring": return [{"page": "finalComputation", "status": "Received"}] * 20
        if k == "netPos": return {"data": [{"hub": "HU", "np": 1}], "rejected": False, "totalRows": 1}
        return {"data": [{"cnecName": "x", "ram": 1}] * 9, "rejected": False, "totalRows": 9, "lastModifiedOn": "t"}

ns = lambda s: None
h = H(); r = jao.probe(h, sleep=ns)
assert r["errors"] == [] and len(h.calls) == 4 and r["datasets"]["finalComputation"]["fields"] == ["cnecName", "ram"]
assert len(r["datasets"]["finalComputation"]["sample"]) == 3 and h.calls[0][1]["Take"] == 5 and len(r["monitoring"]) == 12
print("1 OK  három adathalmaz + monitoring, mezőnevek, minta")
h = H({"netPos": 404}); r = jao.probe(h, sleep=ns)
assert "netPos" not in r["datasets"] and r["errors"] and len(h.calls) == 4
print("2 OK  404: kihagyja, nem próbálja újra")
h = H({"maxExchanges": 429}); r = jao.probe(h, sleep=ns)
assert r["errors"] and sum(1 for c in h.calls if c[0].endswith("maxExchanges")) == 3
print("3 OK  429: háromszor próbálja")
print("MINDEN TESZT ÁTMENT")
