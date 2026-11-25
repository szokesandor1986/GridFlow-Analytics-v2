"""A history.py tesztje kitalált, több évre visszanyúló klienssel, hálózat nélkül.  Futtatás:  python -I tests/test_history.py"""
import importlib.util
import json
import pathlib
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
cspec = importlib.util.spec_from_file_location("collector", ROOT / "collector.py")
col = importlib.util.module_from_spec(cspec)
cspec.loader.exec_module(col)
sys.modules["collector"] = col                      # a history.py ezt importálja
hspec = importlib.util.spec_from_file_location("history", ROOT / "history.py")
hist = importlib.util.module_from_spec(hspec)
hspec.loader.exec_module(hist)
from fake_history_client import FakeHistoryClient  # noqa: E402

NOW = pd.Timestamp("2026-11-23 14:20", tz="UTC")


def test_history():
    c = FakeHistoryClient(NOW)
    h = hist.collect_history(c, now=NOW, from_year=2024, workers=4)
    m = h["months"]
    assert "2024-01" in m and "2026-11" in m and m["2026-11"]["partial"] and not m["2026-07"]["partial"], sorted(m)[:3]
    assert h["years_complete"] == [2024, 2025] == h["years_done"], h["years_complete"]
    assert not any("ValueError" in e for e in h["errors"]) and not h["errors"], h["errors"]   # időzóna-hiba nélkül
    # a modell trendjei: a nap részaránya és a negatív órák száma nő
    assert m["2026-07"]["gen"]["solar"] > m["2024-07"]["gen"]["solar"] > 0
    assert m["2026-07"]["price"]["neg_h"] > m["2024-07"]["price"]["neg_h"]
    assert 0.9 < m["2026-07"]["z"]["AT"]["corr"] <= 1.0
    assert "RS" not in m["2026-07"]["z"] and "UA" not in m["2026-07"]["border"]
    ldc = h["annual"]["2025"]["ldc"]
    assert len(ldc) == 21 and ldc[0] > ldc[-1] and all(a >= b for a, b in zip(ldc, ldc[1:]))
    assert h["annual"]["2026"]["inst"]["solar"] > 1000
    json.dumps(h, allow_nan=False)
    print(f"1. havi összesítés rendben ({len(m)} hónap)")

    # második futás: csak a folyó évet tölti le újra
    c2 = FakeHistoryClient(NOW)
    h2 = hist.collect_history(c2, now=NOW, from_year=2024, existing=json.loads(json.dumps(h)), workers=4)
    assert {y for _, y in c2.calls} == {2026} and len(h2["months"]) == len(m)
    print("2. inkrementális frissítés rendben")


def test_broken_year():
    class Broken(FakeHistoryClient):
        def query_load(self, zone, start, end, **kw):
            if start.year == 2025:
                raise ConnectionError("x")
            return super().query_load(zone, start, end, **kw)

        def query_generation(self, zone, start, end, **kw):
            if start.year == 2025:
                raise ConnectionError("x")
            return super().query_generation(zone, start, end, **kw)
    h = hist.collect_history(Broken(NOW), now=NOW, from_year=2024, workers=4)
    assert 2025 not in h["years_complete"] and 2024 in h["years_complete"] and "2024-05" in h["months"], h["years_complete"]
    assert any("2025" in e for e in h["errors"]), h["errors"]
    print("3. hibás év nem rontja el a többit")


def test_incomplete_year_is_retried():
    """Ha egy lekérdezés hibázik, az év nem kerül a lezártak közé, és a következő futás újra letölti."""
    class OneZoneBroken(FakeHistoryClient):
        def query_day_ahead_prices(self, zone, start, end, **kw):
            if zone == "AT" and start.year == 2025:
                raise ConnectionError("megszakadt")
            return super().query_day_ahead_prices(zone, start, end, **kw)
    h = hist.collect_history(OneZoneBroken(NOW), now=NOW, from_year=2024, workers=4)
    assert h["years_complete"] == [2024], h["years_complete"]
    assert "2025-06" in h["months"] and any("2025" in e and "hiányos" in e for e in h["errors"]), h["errors"]
    assert any("ár AT 2025: ConnectionError (megszakadt)" in e for e in h["errors"]), h["errors"]
    c = FakeHistoryClient(NOW)
    h2 = hist.collect_history(c, now=NOW, from_year=2024, existing=json.loads(json.dumps(h)), workers=4)
    assert {y for _, y in c.calls} == {2025, 2026} and h2["years_complete"] == [2024, 2025], h2["years_complete"]
    # a régi (megbízhatatlan) years_done kulcsot nem vesszük figyelembe
    c = FakeHistoryClient(NOW)
    old = {"months": h["months"], "annual": h["annual"], "years_done": [2024, 2025]}
    hist.collect_history(c, now=NOW, from_year=2024, existing=old, workers=4)
    assert {y for _, y in c.calls} == {2024, 2025, 2026}
    print("5. hiányos év újrapróbálása rendben")


def test_skipped_year_not_done():
    """Időkeret-túllépésnél kimaradt lekérdezés → az év nem lezárt."""
    h = hist.collect_history(FakeHistoryClient(NOW), now=NOW, from_year=2024, workers=1, budget_s=0)
    assert h["years_complete"] == [] and not h["months"], (h["years_complete"], len(h["months"]))
    print("6. kimaradt lekérdezés nem zár le évet")


def test_plan_and_merge():
    base = {"years_complete": [2019, 2020, 2021, 2022]}
    assert hist.plan_groups(base, NOW, 2) == ["2026,2025", "2024,2023"], hist.plan_groups(base, NOW, 2)
    assert hist.plan_groups({"years_complete": list(range(2019, 2027))}, NOW, 2) == ["2026"]   # a folyó év mindig
    assert hist.plan_groups({}, NOW, 3, from_year=2024) == ["2026,2025,2024"]

    full = hist.collect_history(FakeHistoryClient(NOW), now=NOW, from_year=2024, workers=4)
    pa = hist.collect_history(FakeHistoryClient(NOW), now=NOW, from_year=2024, years=[2026, 2025], workers=4)
    pb = hist.collect_history(FakeHistoryClient(NOW), now=NOW, from_year=2024, years=[2024], workers=4)
    assert pa["part_years"] == [2026, 2025] and pb["part_years"] == [2024]
    old = {"months": {"2023-05": {"x": 1}}, "annual": {"2023": {"ldc": [1]}}, "years_complete": [2023]}
    out, notes = hist.merge_parts(old, [json.loads(json.dumps(pa)), json.loads(json.dumps(pb))], NOW)
    assert out["months"].keys() == full["months"].keys() | {"2023-05"}, set(full["months"]) ^ set(out["months"])
    assert out["months"]["2025-06"] == full["months"]["2025-06"] and out["annual"]["2023"] == {"ldc": [1]}
    assert out["years_complete"] == [2023, 2024, 2025] and out["annual"]["2026"]["inst"] == full["annual"]["2026"]["inst"]
    assert len(notes) == 2
    json.dumps(out, allow_nan=False)
    # hiányzó (összeomlott) rész: a régi adat megmarad
    out2, _ = hist.merge_parts({"months": out["months"], "annual": out["annual"], "years_complete": out["years_complete"]},
                               [json.loads(json.dumps(pb))], NOW)
    assert out2["months"]["2026-03"] == out["months"]["2026-03"]
    print("7. tervezés és összefésülés rendben")


def test_progress():
    saves = []
    h = hist.collect_history(FakeHistoryClient(NOW), now=NOW, from_year=2024, workers=4,
                             on_progress=lambda x: saves.append(json.loads(json.dumps(x))))
    assert len(saves) == 3, len(saves)                         # 2024, 2025, 2026: minden feldolgozott év után egy mentés
    assert all(x["schema"] == h["schema"] and x["months"] for x in saves)
    assert len(saves[0]["months"]) < len(saves[-1]["months"]) <= len(h["months"])
    assert any("még tart" in e for e in saves[0]["errors"]) and not any("még tart" in e for e in h["errors"])
    print("4. köztes mentés: évenként érvényes history.json")


if __name__ == "__main__":
    col.time.sleep = lambda s: None
    test_history()
    test_broken_year()
    test_incomplete_year_is_retried()
    test_skipped_year_not_done()
    test_plan_and_merge()
    test_progress()
    print("MINDEN TESZT ÁTMENT")
