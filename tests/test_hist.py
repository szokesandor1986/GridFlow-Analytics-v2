"""A hist/ tár (hist_store.py, backfill.py, aggregate.py) tesztje kitalált klienssel, hálózat nélkül.
Futtatás:  python -I tests/test_hist.py"""
import json
import os
import pathlib
import shutil
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import aggregate as ag  # noqa: E402
import backfill as bf  # noqa: E402
import collector as col  # noqa: E402
import hist_store as hs  # noqa: E402
from fake_history_client import FakeHistoryClient  # noqa: E402

NOW = pd.Timestamp("2026-11-20 12:20", tz="UTC")
TMP = pathlib.Path(tempfile.mkdtemp(prefix="hist-test-"))


def build(root, zones=("HU", "AT", "UA", "RS"), years=(2026, 2025, 2024), q=()):
    client = col.GroupClient(FakeHistoryClient(NOW))
    ranges = [bf.year_range(y, NOW) for y in years]
    report, B = bf.collect(client, list(zones), ranges, NOW, str(root), workers=4, budget_s=600, q_years=set(q))
    ag.run(str(root), now=NOW)
    return report, B


def snapshot(root):
    return {os.path.relpath(os.path.join(d, f), root): hs.file_hash(os.path.join(d, f))
            for d, _, fs in os.walk(root) for f in fs if f.endswith(".json") and f != "manifest.json"}


def local_day(df, day):
    ix = df.index.tz_convert(hs.BUD)
    return df[ix.strftime("%Y-%m-%d") == day]


def test_build_and_grid():
    root = TMP / "main"
    report, B = build(root, q=(2026,))
    assert not B.errors, B.errors
    h = hs.read_json(str(root / "h/HU/2025/load.json"))
    assert h["n"] == 8760 and h["step"] == 3600 and h["t0"] == int(pd.Timestamp("2024-12-31 23:00", tz="UTC").timestamp()), h["t0"]
    assert hs.read_json(str(root / "h/HU/2024/load.json"))["n"] == 8784            # szökőév
    assert all(v is not None for v in h["series"]["load"]), "a lezárt év minden órájára van adat"
    cur = hs.read_json(str(root / "h/HU/2026/load.json"))
    i_now = int((NOW.floor("h").timestamp() - cur["t0"]) // 3600)
    v = cur["series"]["load"]
    assert v[i_now - 3] is not None and v[i_now + 5] is None and all(x is None for x in v[i_now + 5:]), "a jövő hiányzó (null), nem nulla"
    # UA ár nincs, de UA fogyasztás van; RS ár nincs
    assert not (root / "h/UA/2026/price_da.json").exists() and (root / "h/UA/2026/load.json").exists()
    assert not (root / "h/RS/2026/price_da.json").exists() and (root / "h/RS/2026/generation.json").exists()
    assert (root / "h/HU/2026/flow_physical.json").exists() and not (root / "h/AT/2026/flow_physical.json").exists()
    fp = hs.read_json(str(root / "h/HU/2025/flow_physical.json"))
    assert "UA" not in fp["series"] and {"AT", "SK", "RO", "RS", "HR", "SI"} <= set(fp["series"])
    print("1. rács, szökőév, hiány = null, zónák rendben")
    return root


def test_spans():
    assert ag.span("2026-03-29", "d") == 23 and ag.span("2026-10-25", "d") == 25 and ag.span("2026-06-10", "d") == 24
    assert ag.span("2024-02", "m") == 696 and ag.span("2025-02", "m") == 672
    assert ag.span("2024", "y") == 8784 and ag.span("2026", "y") == 8760
    assert ag.span("2026-W13", "w") == 167, ag.span("2026-W13", "w")               # a márc. 29-i óraátállítás hete
    assert ag.span("2026-W43", "w") == 169                                         # okt. 25. (25 órás nap)
    assert ag.span("2026-03", "m") == 743 and ag.span("2026-10", "m") == 745
    assert ag.span("2026-03-29", "d", "d") == 1 and ag.span("2026-W13", "w", "d") == 7
    assert ag.all_keys(["2026-W52", "2027-W02"], "w") == ["2026-W52", "2026-W53", "2027-W01", "2027-W02"], ag.all_keys(["2026-W52", "2027-W02"], "w")
    assert ag.all_keys(["2024-02-27", "2024-03-02"], "d") == ["2024-02-27", "2024-02-28", "2024-02-29", "2024-03-01", "2024-03-02"]
    print("2. időszak-hosszak (DST, szökőév, ISO-hét) rendben")


def test_rollup_matches_manual(root):
    df = hs.load_partition(str(root), "HU", 2025, "generation")
    d = hs.read_json(str(root / "d/HU/generation.json"))
    k = d["keys"].index("2025-07-15")
    day = local_day(df, "2025-07-15")["solar"]
    s = d["series"]["solar"]
    assert s["n"][k] == 24 and d["h"][k] == 24
    assert abs(s["avg"][k] - day.mean()) <= 0.06 and s["max"][k] == hs.rnd(day.max()) and s["min"][k] == hs.rnd(day.min())
    # a DST-átállás napja 23 órás: az átlag a 23 óráról számolódik, az energia = átlag × 23
    d26 = hs.read_json(str(root / "d/HU/load.json"))
    k = d26["keys"].index("2026-03-29")
    day = local_day(hs.load_partition(str(root), "HU", 2026, "load"), "2026-03-29")["load"]
    assert len(day) == 23 and d26["h"][k] == 23 and d26["series"]["load"]["n"][k] == 23
    assert abs(d26["series"]["load"]["avg"][k] - day.mean()) <= 0.06
    k = d26["keys"].index("2026-10-25")
    assert d26["h"][k] == 25 and d26["series"]["load"]["n"][k] == 25
    # havi összesítő a napi órákból
    m = hs.read_json(str(root / "m/HU/load.json"))
    km = m["keys"].index("2025-02")
    feb = hs.load_partition(str(root), "HU", 2025, "load")["load"]
    feb = feb[feb.index.tz_convert(hs.BUD).strftime("%Y-%m") == "2025-02"]
    assert len(feb) == 672 and m["h"][km] == 672 and abs(m["series"]["load"]["avg"][km] - feb.mean()) <= 0.06
    print("3. az összesítők egyeznek a kézi számítással (DST-napok, szökőévi február)")


def test_coverage_and_negative():
    r = TMP / "synthetic"
    idx = hs.year_grid(2025)
    load = pd.Series(1000.0, index=idx)
    loc = idx.tz_convert(hs.BUD)
    d10 = np.where(loc.strftime("%Y-%m-%d") == "2025-01-10")[0]
    load.iloc[d10[12:]] = np.nan                       # január 10.: 12/24 óra = 50 %
    d11 = np.where(loc.strftime("%Y-%m-%d") == "2025-01-11")[0]
    load.iloc[d11[18:]] = np.nan                       # január 11.: 18/24 óra = 75 %
    hs.save_partition(str(r), "CZ", 2025, "load", load.to_frame("load"))
    price = pd.Series(50.0, index=idx)
    price.iloc[100:104] = [-5.0, -0.01, 0.0, 12.5]
    hs.save_partition(str(r), "CZ", 2025, "price_da", price.to_frame("price"))
    ag.run(str(r), zones=["CZ"], now=NOW)
    d = hs.read_json(str(r / "d/CZ/load.json"))["series"]["load"]
    kd = hs.read_json(str(r / "d/CZ/load.json"))["keys"]
    k10, k11 = kd.index("2025-01-10"), kd.index("2025-01-11")
    assert d["n"][k10] == 12 and d["avg"][k10] is None and d["min"][k10] is None, "50 % lefedettség alatt nincs összesítés"
    assert d["n"][k11] == 18 and d["avg"][k11] == 1000, "75 %-nál van"
    assert hs.read_json(str(r / "d/CZ/load.json"))["h"][k10] == 24
    p = hs.read_json(str(r / "d/CZ/price_da.json"))
    kk = p["keys"].index("2025-01-05")                 # a 100–103. óra: január 5.
    assert p["series"]["price"]["neg"][kk] == 2 and p["series"]["price"]["min"][kk] == -5
    assert abs(p["series"]["price"]["avg"][kk] - (50 * 20 + -5 - 0.01 + 0 + 12.5) / 24) < 0.01
    # a hiányzó óra nem nulla: a vágott nap átlaga a meglévő órák átlaga marad (1000), nem húzza le a hiány
    print("4. lefedettségi szabály (<70 % = null), negatív órák, hiány ≠ nulla")


def test_co2_weighted():
    r = TMP / "co2"
    idx = hs.year_grid(2025)
    gas = pd.Series(0.0, index=idx)
    nuc = pd.Series(0.0, index=idx)
    loc = idx.tz_convert(hs.BUD)
    day = np.where(loc.strftime("%Y-%m-%d") == "2025-03-03")[0]
    nuc.iloc[day[:12]], gas.iloc[day[:12]] = 100, 100       # A órák: (12·100 + 490·100) / 200 = 251
    nuc.iloc[day[12:]], gas.iloc[day[12:]] = 300, 0         # B órák: 12
    gen = pd.DataFrame({"nuclear": nuc, "gas": gas})
    hs.save_partition(str(r), "CZ", 2025, "generation", gen.iloc[day[0]:day[-1] + 1])
    ag.run(str(r), zones=["CZ"], now=NOW)
    d = hs.read_json(str(r / "d/CZ/co2.json"))
    k = d["keys"].index("2025-03-03")
    got = d["series"]["intensity"]["avg"][k]
    assert abs(got - 107.6) < 0.1, got                       # termeléssel súlyozott; az átlagok átlaga 131,5 lenne
    assert d["series"]["intensity"]["max"][k] == 251 and d["series"]["intensity"]["min"][k] == 12
    print(f"5. CO₂-intenzitás termeléssel súlyozott ({got} g/kWh, nem 131,5)")


def test_net_import(root):
    h = hs.read_json(str(root / "h/HU/2025/flow_physical.json"))
    ni = hs.read_json(str(root / "h/HU/2025/net_import.json"))["series"]["net"]
    i = 5000
    assert abs(ni[i] - sum(h["series"][b][i] for b in h["series"])) <= 3, (ni[i], [h["series"][b][i] for b in h["series"]])
    # 5/6 határ megvan -> érvényes; 3/6 -> hiányzó
    p = root / "h/HU/2025/flow_physical.json"
    h["series"]["AT"][100] = None
    for b in ("AT", "SK", "RO"):
        h["series"][b][200] = None
    p.write_bytes(hs.dumps(h))
    assert hs.derive_net_import(str(root), "HU", 2025) if hasattr(hs, "derive_net_import") else ag.derive_net_import(str(root), "HU", 2025)
    ni = hs.read_json(str(root / "h/HU/2025/net_import.json"))["series"]["net"]
    assert ni[100] is not None and ni[200] is None, (ni[100], ni[200])
    print("6. nettó import: ≥70 % határ -> érvényes, különben hiányzó")


def test_residual_ramp(root):
    r = hs.read_json(str(root / "h/HU/2025/residual.json"))["series"]["residual"]
    load = hs.read_json(str(root / "h/HU/2025/load.json"))["series"]["load"]
    gen = hs.read_json(str(root / "h/HU/2025/generation.json"))["series"]
    i = 4000
    assert abs(r[i] - (load[i] - gen["solar"][i] - gen["wind"][i])) <= 2
    d = hs.read_json(str(root / "d/HU/ramp.json"))
    assert d["per"] == "d" and set(d["series"]) == {"res_mid_min", "ramp_eve"}
    k = d["keys"].index("2025-07-15")
    assert d["series"]["res_mid_min"]["avg"][k] is not None and d["series"]["ramp_eve"]["avg"][k] >= 0
    m = hs.read_json(str(root / "m/HU/ramp.json"))
    km = m["keys"].index("2025-07")
    assert m["h"][km] == 31 and m["series"]["ramp_eve"]["n"][km] >= 28 and m["series"]["ramp_eve"]["max"][km] >= m["series"]["ramp_eve"]["avg"][km]
    print("7. maradék terhelés és napi rámpa-mutatók rendben")


def test_partial_period(root):
    m = hs.read_json(str(root / "m/HU/load.json"))
    k = m["keys"].index("2026-11")
    assert m["series"]["load"]["n"][k] > 400 and m["series"]["load"]["avg"][k] is None, "a folyó hó 20 napja 70 % alatt: nincs havi érték"
    assert m["series"]["load"]["avg"][m["keys"].index("2026-10")] is not None
    print("8. a folyamatban lévő időszak nem ad félrevezető összesítést")


def test_idempotent_and_merge(root):
    build(root, q=(2026,))                                  # a korábbi tesztlépések (kézi módosítás) után visszaáll az eredeti állapot
    before = snapshot(root)
    report, B = build(root, q=(2026,))
    assert sum(r["files"] for r in report) == 0, [r for r in report if r["files"]]
    assert snapshot(root) == before, "az érintetlen fájlok bájtra azonosak"
    # új adat nem törli a meglévőt
    old = hs.load_partition(str(root), "HU", 2025, "load")
    part = old.copy()
    part.iloc[:100] = np.nan
    part.iloc[100] = 777
    hs.save_partition(str(root), "HU", 2025, "load", part.iloc[:200])
    now = hs.load_partition(str(root), "HU", 2025, "load")
    assert now["load"].iloc[100] == 777 and now["load"].iloc[50] == old["load"].iloc[50] and now["load"].iloc[3000] == old["load"].iloc[3000]
    print("9. újrafuttatás változatlan fájlokat ad; az új adat nem törli a régit")


def test_manifest_catalog(root):
    ag.run(str(root), now=NOW)
    man = hs.read_json(str(root / "manifest.json"))
    assert set(man["zones"]) == {"HU", "AT", "UA", "RS"} and man["prelim_days"] == 90
    hu = man["zones"]["HU"]["cats"]
    assert {"generation", "load", "load_forecast", "price_da", "flow_physical", "flow_scheduled", "net_import", "residual", "co2", "ramp"} <= set(hu), set(hu)
    assert "price_da" not in man["zones"]["UA"]["cats"] and "flow_physical" not in man["zones"]["AT"]["cats"]
    for rel, hsh in man["files"].items():
        assert hs.file_hash(str(root / rel)) == hsh, rel
    assert "h/HU/2025/load.json" in man["files"] and "d/HU/load.json" in man["files"] and "catalog.json" in man["files"]
    assert 0.99 <= hu["load"]["cov"]["2025"] <= 1.0 and hu["load"]["years"] == [2024, 2025, 2026]
    assert 0.9 < hu["load"]["cov"]["2026"] <= 1.0, hu["load"]["cov"]
    assert hu["load"]["q_years"] == [2026]
    cat = hs.read_json(str(root / "catalog.json"))
    assert cat["zones"]["DE_LU"]["country"] == "DE" and "közös ajánlati zóna" in cat["zones"]["DE_LU"]["note"]
    assert cat["cats"]["co2"]["agg"] == "gen_weighted" and cat["cats"]["price_da"]["unit"] == "€/MWh" and cat["co2"]["factors"]["gas"] == 490
    # részleges futás: a többi zóna a manifestben megmarad
    ag.run(str(root), zones=["AT"], now=NOW)
    assert set(hs.read_json(str(root / "manifest.json"))["zones"]) == {"HU", "AT", "UA", "RS"}
    print("10. manifest (hash, lefedettség, zónák) és katalógus rendben")


def test_quarter(root):
    q = hs.read_json(str(root / "q/HU/2026/load.json"))
    assert q["step"] == 900 and q["n"] == 35040 and q["native15_from"] > 0
    qp = hs.read_json(str(root / "q/HU/2026/price_da.json"))
    assert "native15_from" not in qp, "az ár a fake adatban mindig óránkénti: nincs natív negyedórás szakasz"
    v = qp["series"]["price"]
    assert v[8000] == v[8001] == v[8002] == v[8003] and v[8000] is not None, "az óránkénti érték a négy negyedórára ismétlődik"
    ql = q["series"]["load"]
    assert len({ql[8000], ql[8001], ql[8002], ql[8003]}) > 1, "a natív negyedórás fogyasztás negyedóránként más"
    print("11. negyedórás partíció: natív 15 perces adat érintetlen, óránkénti nem interpolált")


def test_plan(root):
    jobs = {j["zone"]: j["years"] for j in bf.plan(str(root), ["HU", "CZ"], 2023, NOW)}
    assert jobs["HU"] == "2026,2023", jobs                # a folyó év és a hiányzó 2023
    assert jobs["CZ"] == "2026,2025,2024,2023", jobs
    print("12. tervezés: a hiányzó zóna-évek és a folyó év")


def test_no_secret_in_store(root):
    blob = b"".join(open(os.path.join(d, f), "rb").read() for d, _, fs in os.walk(root) for f in fs)
    assert b"ENTSOE" not in blob and b"token" not in blob.lower()
    print("13. a tár nem tartalmaz kulcsot vagy tokent")


if __name__ == "__main__":
    try:
        root = test_build_and_grid()
        test_spans()
        test_rollup_matches_manual(root)
        test_coverage_and_negative()
        test_co2_weighted()
        test_net_import(root)
        test_residual_ramp(root)
        test_partial_period(root)
        test_manifest_catalog(root)
        test_quarter(root)
        test_plan(root)
        test_idempotent_and_merge(root)
        test_no_secret_in_store(root)
        print("Minden hist teszt rendben.")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
