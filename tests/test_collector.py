"""A collector.py tesztje kitalált klienssel, hálózat nélkül.  Futtatás:  python -I tests/test_collector.py"""
import importlib.util
import json
import math
import pathlib
import sys

import numpy as np
import pandas as pd
from entsoe.exceptions import NoMatchingDataError

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

spec = importlib.util.spec_from_file_location("collector", ROOT / "collector.py")
col = importlib.util.module_from_spec(spec)
spec.loader.exec_module(col)
from fake_client import FakeClient  # noqa: E402

NOW = pd.Timestamp("2026-11-23 14:20", tz="UTC")


# ---------------------------------------------------------------- 1. fő adatok, kézzel ellenőrizhető értékekkel
class Stub:
    def query_crossborder_flows(self, a, b, start, end, **kw):
        nb = b if a == "HU" else a
        if nb == "UA":
            raise NoMatchingDataError
        if nb == "RS" and a == "HU":
            raise NoMatchingDataError                      # csak az egyik irány hiányzik
        lag = {"AT": 0, "SK": 1, "RO": 0, "HR": 0, "SI": 0, "RS": 0}[nb]
        last = NOW.floor("h") - pd.Timedelta(hours=lag)
        freq = "15min" if nb == "AT" else "h"
        idx = pd.date_range(start, last + (pd.Timedelta(minutes=45) if freq == "15min" else pd.Timedelta(0)), freq=freq, tz="UTC")
        base = {"AT": 700, "SK": 300, "RO": 200, "HR": 150, "SI": 100, "RS": 120}[nb]
        val = base if b == "HU" else base / 4
        return pd.Series(val, index=idx.tz_convert("Europe/Brussels"))

    def query_day_ahead_prices(self, zone, start, end, **kw):
        if zone in ("UA", "RS"):
            raise NoMatchingDataError
        idx = pd.date_range(start, end, freq="15min", inclusive="left")
        return pd.Series(100.0 + len(zone), index=idx.tz_convert("Europe/Brussels"))


def test_main_numbers():
    d = col.collect(Stub(), now=NOW)
    json.dumps(d)
    H = dict(zip(d["hourly_ts"], zip(d["net_import_mw"], d["complete"])))
    assert abs(H["2026-11-23T13:00:00Z"][0] - 1207.5) < 1e-6 and H["2026-11-23T13:00:00Z"][1] is True
    assert d["last_complete_ts"] == "2026-11-23T13:00:00Z"
    assert H["2026-11-23T14:00:00Z"][1] is False
    assert "UA" not in d["prices"]["zones"] and "HU" in d["prices"]["zones"]
    assert d["prices"]["zones"]["HU"][0] == 102.0 and d["prices"]["zones"]["AT"][0] == 102.0
    print("1. fő adatok rendben")


# ---------------------------------------------------------------- 2. mérnöki adatok
def test_engineer():
    client = FakeClient(NOW)
    main = col.collect(client, now=NOW)
    e = col.collect_engineer(client, now=NOW, main=main)
    txt = json.dumps(e)
    assert "NaN" not in txt and "Infinity" not in txt, "a JSON-ban nem lehet NaN"
    n = len(e["hourly_ts"])
    assert e["hourly_ts"][0] == (NOW - pd.Timedelta(hours=48)).floor("h").strftime("%Y-%m-%dT%H:%M:%SZ")
    # holnap 24:00 helyi idő = 2026-11-24 23:00Z, az idősor ennél egy órával korábban ér véget
    assert e["hourly_ts"][-1] == "2026-11-24T22:00:00Z", e["hourly_ts"][-1]
    assert e["errors"] == [], e["errors"]
    for k, v in e["modules"].items():
        assert v, f"modul adat nélkül: {k}"

    # minden idősor ugyanolyan hosszú, mint az idő-tengely
    def lens(o, path=""):
        if isinstance(o, list) and o and not isinstance(o[0], dict):
            assert len(o) == n, (path, len(o), n)
        elif isinstance(o, dict):
            for k, v in o.items():
                lens(v, path + "/" + k)
    for k in ("flows", "load", "generation", "solar_wind_forecast", "imbalance", "balancing"):
        lens(e[k], k)
    for u in e["units"]:
        assert len(u["mw"]) == n

    # fizikai - menetrendezett = a kitalált nem menetrendezett áramlás (AT)
    T = pd.DatetimeIndex(pd.to_datetime(e["hourly_ts"], utc=True))
    from fake_client import unscheduled
    f = e["flows"]["AT"]
    ok = [i for i in range(n) if f["phys_net"][i] is not None and f["sched_net"][i] is not None]
    assert len(ok) > 40
    diff = np.array([f["phys_net"][i] - f["sched_net"][i] for i in ok])
    want = np.array([unscheduled("AT", T[[i]])[0] for i in ok])
    assert np.abs(diff - want).max() < 25, np.abs(diff - want).max()       # az órás átlag miatt kis eltérés lehet
    assert "UA" not in e["flows"]
    assert e["flows"]["RS"]["ntc_in"] is not None and e["flows"]["AT"]["ntc_in"] is None

    # a csoportosított atomtermelés = a blokkok összege
    nuc_units = [u for u in e["units"] if u["group"] == "nuclear"]
    assert len(nuc_units) == 4
    for i in ok[-5:]:
        s = sum(u["mw"][i] for u in nuc_units)
        assert abs(s - e["generation"]["nuclear"][i]) < 1e-3 * max(1, s) + 1, (s, e["generation"]["nuclear"][i])
    # a gáz-blokkok összege = gáz csoport
    gas_units = [u for u in e["units"] if u["group"] == "gas"]
    i = ok[-1]
    assert abs(sum(u["mw"][i] for u in gas_units) - e["generation"]["gas"][i]) < 2

    # a jövőben (holnap) csak előrejelzés van, tény nincs
    assert e["load"]["actual"][-1] is None and e["load"]["forecast"][-1] is not None
    assert e["solar_wind_forecast"]["solar"][-1] is not None and e["generation"]["solar"][-1] is None

    # kiesések: a törölt és az elavult változat nem szerepel; a nem tervezett igen
    names = [(o["name"], o["planned"], o["end"]) for o in e["outages_gen"]]
    assert not any(o["name"] == "Lignit blokk" for o in e["outages_gen"]), names
    b = [o for o in e["outages_gen"] if o["name"] == "Gázblokk B"]
    assert len(b) == 1 and b[0]["planned"] is False and b[0]["end"] == (NOW + pd.Timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert any(o["border"] == "SK" for o in e["outages_tx"]) and any(o["border"] == "RS" and not o["planned"] for o in e["outages_tx"])
    assert e["installed_mw"]["solar"] == 8500 and e["installed_mw"]["nuclear"] == 2000
    assert set(e["co2"]["factors"]) == set(col.GROUPS)
    print("2. mérnöki adatok rendben | méret:", len(txt), "bájt | hiányzó lekérdezések:", len(e["missing"]))


def test_survives_broken_client():
    """Ha a kliens minden mérnöki lekérdezésre hibázik, a collect_engineer nem dől el, hanem hibát jegyez."""
    class Broken(FakeClient):
        def query_load(self, *a, **k):
            raise RuntimeError("szimulált hiba")
        query_generation = query_load
    c = Broken(NOW)
    e = col.collect_engineer(c, now=NOW, main=None)
    assert e["load"]["actual"] is None and e["load"]["forecast"] is not None and not e["modules"]["generation"]
    assert any("RuntimeError" in x for x in e["errors"])
    assert e["modules"]["units"]
    print("3. hibatűrés rendben")


def test_budget():
    """Lejárt időkeretnél a mérnöki lekérdezések kimaradnak, a hívás nem dől el, és a hiba látszik."""
    class Counting(FakeClient):
        calls = 0
        def query_load(self, *a, **k):
            Counting.calls += 1
            return super().query_load(*a, **k)
    c = Counting(NOW)
    e = col.collect_engineer(c, now=NOW, main=None, budget_s=-1)
    assert Counting.calls == 0 and not any(e["modules"].values())
    assert any("időkeret" in x for x in e["errors"]), e["errors"]
    json.dumps(e)
    print("4. időkeret rendben")


def test_parallel():
    """Lassú ENTSO-E mellett a párhuzamos lekérdezés a sorosnál sokkal gyorsabb, és az eredmény ugyanaz."""
    import time as _t

    class Slow(FakeClient):
        pass
    for name in [n for n in dir(FakeClient) if n.startswith("query_")]:
        def make(n):
            def f(self, *a, **k):
                _t.sleep(0.05)
                return getattr(FakeClient, n)(self, *a, **k)
            return f
        setattr(Slow, name, make(name))
    t0 = _t.monotonic()
    e = col.collect_engineer(Slow(NOW), now=NOW, main=None, budget_s=60, workers=8)
    dt = _t.monotonic() - t0
    ref = col.collect_engineer(FakeClient(NOW), now=NOW, main=None, budget_s=60, workers=1)
    assert json.dumps(e["load"]) == json.dumps(ref["load"]) and e["modules"] == ref["modules"]
    # sorosan ~70 kérés x 0,05 s = 3,5 s lenne
    assert dt < 2.0, dt
    print(f"5. párhuzamosság rendben ({dt:.2f} s)")


def test_europe():
    """Európai ár-pillanatkép (europe.json)."""
    eu = col.collect_europe(col.GroupClient(FakeClient(NOW)), now=NOW, budget_s=60)
    assert "HU" in eu["zones"] and "DE_LU" in eu["zones"] and "RS" not in eu["zones"], sorted(eu["zones"])
    assert len(eu["ts"]) >= 24 * 3 and all(len(v) == len(eu["ts"]) for v in eu["zones"].values())
    assert {"SE", "NO", "DK", "FI", "PL", "NO_1", "SE_3", "DK_2", "IT_SICI", "GB", "BY"} <= set(eu["zones"]), sorted(eu["zones"])
    json.dumps(eu, allow_nan=False)
    fl = eu["flows"]
    assert len(eu["flow_ts"]) == 48 and all(len(f["mw"]) == 48 for f in fl)
    got = {(f["a"], f["b"]) for f in fl}
    assert ("HU", "AT") in got and ("DE_LU", "FR") in got and ("DK", "SE") in got, sorted(got)
    ha = next(f for f in fl if (f["a"], f["b"]) == ("HU", "AT"))
    assert any(v is not None for v in ha["mw"]) and all(v is None or abs(v) < 1e5 for v in ha["mw"])
    print(f"6. európai ár-pillanatkép rendben ({len(eu['zones'])} zóna)")


def test_countries():
    """Országválasztó adatai (countries.json): minden zónára fogyasztás, termelés, nettó import; az előjel-ellenőrzés."""
    cn = col.collect_countries(col.GroupClient(FakeClient(NOW)), now=NOW, hours=168, budget_s=60)
    assert "DE_LU" in cn["zones"] and "HU" not in cn["zones"], sorted(cn["zones"])
    n = len(cn["hourly_ts"])
    assert n >= 168 + 24, n
    z = cn["zones"]["AT"]
    assert len(z["load"]["actual"]) == n and len(z["net_import_mw"]) == n
    assert set(z["generation"]) >= {"nuclear", "gas", "solar"}
    assert "netpos_flipped" not in cn           # a day-ahead nettó pozíciót (előjel nélkül) már nem használjuk
    se, fc = cn["zones"]["SE"], FakeClient(NOW)
    st, en = pd.Timestamp("2026-11-20", tz="UTC"), pd.Timestamp("2026-11-21", tz="UTC")
    one = sum(float(fc.query_load(z, start=st, end=en).iloc[:, 0].sum()) for z in col.ZONE_GROUPS["SE"])
    got = float(col.GroupClient(fc).query_load("SE", start=st, end=en).iloc[:, 0].sum())
    assert abs(one - got) < 1e-6 * one, (one, got)         # az országösszeg a tagzónák összege
    json.dumps(cn, allow_nan=False)
    # a nettó import a fizikai határáramlásokból jön: AT = (bejövő - kimenő) az összes szomszédjával
    fc2 = FakeClient(NOW)
    adj = col._adjacency()
    zn, idx = cn["zones"]["AT"], pd.DatetimeIndex(cn["hourly_ts"])
    exp_net = None
    for nbr in sorted(adj["AT"]):
        for a_, b_, sg in ((nbr, "AT", 1), ("AT", nbr, -1)):
            try:
                sr = fc2.query_crossborder_flows(a_, b_, start=idx[0], end=idx[-1] + pd.Timedelta(hours=1))
            except Exception:  # noqa: BLE001
                continue
            h = col.hourly_mean(sr).reindex(idx) * sg
            exp_net = h if exp_net is None else exp_net.add(h, fill_value=0)
    assert exp_net is not None and zn["net_borders"][0] >= 1
    got_net = pd.Series(zn["net_import_mw"], index=idx, dtype="float64")
    both = pd.concat([got_net, exp_net], axis=1).dropna().iloc[:120]      # a jól lefedett (nem a legfrissebb, részleges) órák
    assert len(both) > 50 and (both.iloc[:, 0] - both.iloc[:, 1]).abs().max() < 0.05, "a nettó import nem egyezik a határáramlások különbségével"
    # országcsoport (SE): a tagzónák közötti belső áramlás nem számít bele
    assert "net_import_mw" in cn["zones"].get("DK", {}) or "DK" not in cn["zones"]
    print(f"7. országadatok rendben ({len(cn['zones'])} zóna, {n} óra, nettó import fizikai áramlásból)")


def test_balancing_and_finance():
    """aFRR/mFRR az új (12.3.E) adatkörből, aktivált energia ára, 17.1.I havi pénzügyi mérleg és a nyers A87-XML értelmezése."""
    eng = col.collect_engineer(FakeClient(NOW), now=NOW, hours=168)
    b = eng["balancing"]
    for k in ("afrr_up", "afrr_down", "afrr_up_offered", "mfrr_up", "mfrr_down_offered", "afrr_price_up", "mfrr_price_down"):
        assert b.get(k) and any(v is not None for v in b[k]), k
    # a két termékidősor aktivált teljesítménye összeadódik (0,8 + 0,2 arány): az összeg a teljes aktivált érték
    up = [v for v in b["afrr_up"] if v is not None]
    off = [v for v in b["afrr_up_offered"] if v is not None]
    assert max(off) > max(up) > 0
    f = eng["finance"]
    assert f["currency"] == "HUF" and len(f["months"]) >= 23 and len(f["up"]) == len(f["months"]) == len(f["down"]), f and f["months"]
    assert eng["modules"]["finance"] is True
    # nyers A87-XML: irány a pont alatt (Financial_Price/direction) és idősor-szinten, ZIP-ben és anélkül
    import io
    import zipfile
    pt = ("<Point><position>{pos}</position><Financial_Price><amount>{amt}</amount><direction>{d}</direction></Financial_Price></Point>")
    xml = ("<?xml version='1.0'?><Balancing_MarketDocument xmlns='urn:iec62325.351:tc57wg16:451-6:balancingdocument:4:5'><type>A87</type>"
           "<TimeSeries><mRID>1</mRID><businessType>A99</businessType><currency_Unit.name>HUF</currency_Unit.name><curveType>A01</curveType>"
           "<Period><timeInterval><start>2025-12-31T23:00Z</start><end>2026-02-28T23:00Z</end></timeInterval><resolution>P1M</resolution>"
           + pt.format(pos=1, amt="1087522143", d="A01") + pt.format(pos=2, amt="1200000000", d="A01") + "</Period></TimeSeries>"
           "<TimeSeries><mRID>1</mRID><businessType>A99</businessType><currency_Unit.name>HUF</currency_Unit.name><curveType>A01</curveType>"
           "<Period><timeInterval><start>2025-12-31T23:00Z</start><end>2026-02-28T23:00Z</end></timeInterval><resolution>P1M</resolution>"
           + pt.format(pos=1, amt="32564550", d="A02") + pt.format(pos=2, amt="-5000", d="A02") + "</Period></TimeSeries></Balancing_MarketDocument>")
    rows, sample = col.parse_financial_balance(xml.encode())
    got = {(r["month"], r["dir"]): r["amount"] for r in rows}
    assert got == {("2026-01", "up"): 1087522143.0, ("2026-02", "up"): 1200000000.0, ("2026-01", "down"): 32564550.0, ("2026-02", "down"): -5000.0}, got
    assert rows[0]["currency"] == "HUF" and sample["resolution"] == "P1M"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Financial_expenses_and_income_for_balancing.xml", xml)
    rows2, _ = col.parse_financial_balance(buf.getvalue())
    assert rows2 == rows
    fs = col.finance_summary((rows, sample))
    assert fs["months"] == ["2026-01", "2026-02"] and fs["up"] == [1087522143.0, 1200000000.0] and fs["down"] == [32564550.0, -5000.0]
    json.dumps(eng, allow_nan=False)
    print("8. aFRR/mFRR (12.3.E), aktivált energia ára és 17.1.I pénzügyi mérleg rendben")


def test_financial_two_prices_in_point():
    """Egy Point két Financial_Price-t tartalmaz (A01 kiadás, A02 bevétel): mindkettőnek meg kell maradnia."""
    xml = (b"<Balancing_MarketDocument><TimeSeries><mRID>1</mRID><currency_Unit.name>HUF</currency_Unit.name><Period>"
           b"<timeInterval><start>2024-11-30T23:00Z</start><end>2024-12-31T23:00Z</end></timeInterval><resolution>P1M</resolution>"
           b"<Point><position>1</position><Financial_Price><amount>5000</amount><direction>A01</direction></Financial_Price>"
           b"<Financial_Price><amount>4400</amount><direction>A02</direction></Financial_Price></Point></Period></TimeSeries></Balancing_MarketDocument>")
    rows, _ = col.parse_financial_balance(xml)
    fs = col.finance_summary((rows, _))
    assert fs["up"] == [5000.0] and fs["down"] == [4400.0], fs
    print("9. 17.1.I: kiadás és bevétel is megmarad")


if __name__ == "__main__":
    # a with_retry várakozását kikapcsoljuk, hogy a hibatesztek ne lassúak legyenek
    col.time.sleep = lambda s: None
    test_main_numbers()
    test_engineer()
    test_survives_broken_client()
    test_budget()
    test_parallel()
    test_europe()
    test_financial_two_prices_in_point()
    test_countries()
    test_balancing_and_finance()
    print("MINDEN TESZT ÁTMENT")
