"""A demo-hist/ mappa előállítása (kitalált adat, NEM valós mérés): a Historikus adatok és a publikációk előnézetéhez.
Kicsi: 10 zóna napi/heti/havi/éves összesítője 2024–2026-ra, és csak a magyar 2026-os évnek van óránkénti és negyedórás partíciója.
A zónák méretükben és összetételükben eltérnek (kitalált arányok), Ukrajnáról csak a fogyasztás van meg, mint a valós ENTSO-E közlésben: így a hiányzó adat kezelése is látszik.
Futtatás:  python -I tests/make_demo_hist.py"""
import json
import os
import pathlib
import shutil
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import aggregate as ag  # noqa: E402
import backfill as bf  # noqa: E402
import collector as col  # noqa: E402
import hist_store as hs  # noqa: E402
from entsoe.exceptions import NoMatchingDataError  # noqa: E402
from fake_history_client import FakeHistoryClient  # noqa: E402

NOW = pd.Timestamp("2026-11-23 13:20", tz="UTC")
OUT = ROOT / "demo-hist"
ZONES = ["HU", "AT", "SK", "RO", "RS", "HR", "SI", "UA", "DE_LU", "CZ"]
# kitalált zónajellemzők: fogyasztás-szorzó, nap-, szélszorzó, atomerőmű (MW, 0 = nincs), szénszorzó (0 = nincs)
ZF = {"HU": (1.0, 1.0, 1.0, 1900, 1.0), "AT": (1.3, 1.2, 2.0, 0, 0.0), "SK": (0.6, 0.6, 0.1, 1800, 0.4),
      "RO": (1.5, 0.9, 6.0, 1300, 1.8), "RS": (0.9, 0.2, 1.0, 0, 3.0), "HR": (0.5, 0.5, 2.5, 0, 0.0),
      "SI": (0.3, 0.7, 0.0, 700, 0.5), "UA": (1.4, 1.0, 1.0, 0, 1.0), "DE_LU": (11.0, 8.0, 24.0, 0, 6.0),
      "CZ": (1.7, 1.1, 0.3, 3900, 2.5)}


class DemoClient(FakeHistoryClient):
    """A HU-modell zónánként átméretezve; Ukrajnáról csak fogyasztás van (nincs termelés és ár)."""

    def query_load(self, zone, start, end, **kw):
        return super().query_load("HU", start, end, **kw) * ZF[zone][0]

    def query_load_forecast(self, zone, start, end, **kw):
        return super().query_load_forecast("HU", start, end, **kw) * ZF[zone][0]

    def query_generation(self, zone, start, end, nett=False, **kw):
        if zone == "UA":
            raise NoMatchingDataError
        ls, ss, ws, nuc, coal = ZF[zone]
        df = super().query_generation("HU", start, end, nett=nett, **kw) * ls
        for c in list(df.columns):
            if c == "Solar":
                df[c] = df[c] * ss / ls
            elif c.startswith("Wind"):
                if ws == 0:
                    del df[c]
                else:
                    df[c] = df[c] * ws / ls
            elif c == "Nuclear":
                if nuc == 0:
                    del df[c]
                else:
                    df[c] = nuc + 0 * df[c]
            elif c.startswith("Fossil Brown"):
                if coal == 0:
                    del df[c]
                else:
                    df[c] = df[c] * coal / ls
        return df


def main():
    tmp = pathlib.Path("/tmp/demo-hist-build")
    shutil.rmtree(tmp, ignore_errors=True)
    client = col.GroupClient(DemoClient(NOW))
    ranges = [bf.year_range(y, NOW) for y in (2026, 2025, 2024)]
    bf.collect(client, ZONES, ranges, NOW, str(tmp), workers=8, budget_s=600, q_years={2026})
    ag.run(str(tmp), now=NOW)
    # a kis demóban csak a magyar 2026-os óránkénti és negyedórás partíció marad meg
    for tier in ("h", "q"):
        for z in os.listdir(tmp / tier):
            for y in os.listdir(tmp / tier / z):
                if not (z == "HU" and y == "2026"):
                    shutil.rmtree(tmp / tier / z / y)
            if not os.listdir(tmp / tier / z):
                shutil.rmtree(tmp / tier / z)
    if (tmp / "q" / "HU" / "2026").exists():
        for f in os.listdir(tmp / "q" / "HU" / "2026"):
            if f not in ("load.json", "price_da.json"):
                os.remove(tmp / "q" / "HU" / "2026" / f)
    man = json.loads((tmp / "manifest.json").read_text(encoding="utf-8"))
    for zn, z in man["zones"].items():
        for cat, c in z["cats"].items():
            c["years"] = [y for y in c["years"] if (tmp / "h" / zn / str(y) / (cat + ".json")).exists()]
            q = [y for y in c.get("q_years", []) if (tmp / "q" / zn / str(y) / (cat + ".json")).exists()]
            if q:
                c["q_years"] = q
            else:
                c.pop("q_years", None)
    man["files"] = {k: v for k, v in man["files"].items() if (tmp / k).exists()}
    man["demo"] = True
    (tmp / "manifest.json").write_bytes(hs.dumps(man))
    shutil.rmtree(OUT, ignore_errors=True)
    shutil.copytree(tmp, OUT)
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"demo-hist/ kész: {sum(1 for f in OUT.rglob('*') if f.is_file())} fájl, {size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
