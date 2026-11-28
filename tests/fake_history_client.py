"""Kitalált, több évre visszanyúló ENTSO-E kliens a history.py teszteléséhez és a DEMO adathoz. NEM valós mérés.

Szándékos trendek, hogy a grafikonok előnézete értelmes legyen: a napelemes termelés évről évre nő,
a déli ár egyre mélyebbre süllyed (negatív órák), 2021-22-ben ármagas időszak, a gáz a maradék.
"""
import numpy as np
import pandas as pd
from entsoe.exceptions import NoMatchingDataError

from fake_client import BRU, BUD, lh, net_pattern, secs

YEAR_PRICE = {2018: 50, 2019: 52, 2020: 40, 2021: 105, 2022: 260, 2023: 125, 2024: 100, 2025: 105, 2026: 92}
ZONE_OFF = {"HU": 0, "AT": -6, "SK": 3, "RO": 10, "HR": 2, "SI": -3, "CZ": -5, "DE_LU": -16, "PL": 8, "BG": 12,
            "IT_NORD": 14, "FR": -22, "CH": 4, "NL": -12, "BE": -14, "ES": -30, "GR": 15}


def doy(idx):
    return np.asarray(idx.tz_convert(BUD).dayofyear, dtype=float)


def year_f(idx):
    return np.asarray(idx.tz_convert(BUD).year, dtype=float)


def solar_scale(idx):
    return np.clip(0.04 + 0.16 * (year_f(idx) - 2019), 0.04, 1.2)


def solar(idx):
    h = lh(idx)
    season = 0.18 + 0.82 * np.clip(np.sin(2 * np.pi * (doy(idx) - 80) / 365), 0, None)
    clear = 0.75 + 0.25 * np.sin(doy(idx) * 1.9)
    return 2300 * solar_scale(idx) * np.exp(-((h - 12.5) ** 2) / (2 * 2.6**2)) * season * clear


def load_model(idx):
    h = lh(idx)
    season = 1 + 0.14 * np.cos(2 * np.pi * (doy(idx) - 20) / 365)
    wk = np.where(idx.tz_convert(BUD).dayofweek >= 5, 0.9, 1.0)
    shape = 4400 + 1000 * np.exp(-((h - 8) ** 2) / 6) + 700 * np.exp(-((h - 12.5) ** 2) / 14) + 1900 * np.exp(-((h - 19) ** 2) / 7)
    return shape * season * wk * (1 + 0.008 * (year_f(idx) - 2019))


def wind(idx):
    return 160 + 110 * np.sin(secs(idx) / 90000.0) + 40 * np.sin(secs(idx) / 7000.0)


def net(idx):
    return sum(net_pattern(nb, idx) for nb in ("AT", "SK", "RO", "HR", "SI", "RS")) * (1 + 0.15 * (year_f(idx) - 2019) / 7)


def same_offset(start, end):
    """Az entsoe-py truncate-je ezt a hibát dobja, ha a két időpont időzónája eltér."""
    if start.tz != end.tz:
        raise ValueError("Both dates must have the same UTC offset")


class FakeHistoryClient:
    def __init__(self, now):
        self.now = now
        self.calls = []

    def _idx(self, start, end, freq):
        stop = min(end, self.now.ceil("h"))
        idx = pd.date_range(start.tz_convert("UTC"), stop.tz_convert("UTC"), freq=freq, inclusive="left")
        if len(idx) == 0:
            raise NoMatchingDataError
        return idx

    def query_load(self, zone, start, end, **kw):
        self.calls.append(("load", start.year))
        idx = self._idx(start, end, "15min")
        return pd.Series(load_model(idx) + 25 * np.sin(secs(idx) / 1900.0), index=idx.tz_convert(BUD)).to_frame("Actual Load")

    def query_generation(self, zone, start, end, nett=False, **kw):
        self.calls.append(("gen", start.year))
        idx = self._idx(start, end, "15min")
        sol, wnd = solar(idx), wind(idx)
        coal, bio, hyd, oth = 260 - 8 * (year_f(idx) - 2019), 210, 45, 60
        nuc = 1900.0
        gas = np.clip(load_model(idx) - net(idx) - nuc - sol - wnd - coal - bio - hyd - oth, 120, None)
        cols = {"Nuclear": nuc + 0 * sol, "Fossil Gas": gas, "Fossil Brown coal/Lignite": coal + 0 * sol, "Solar": sol,
                "Wind Onshore": wnd, "Biomass": bio * 0.8 + 0 * sol, "Waste": bio * 0.2 + 0 * sol,
                "Hydro Run-of-river and poundage": hyd + 0 * sol, "Other": oth + 0 * sol}
        return pd.DataFrame(cols, index=idx.tz_convert(BUD))

    def query_day_ahead_prices(self, zone, start, end, **kw):
        same_offset(start, end)
        self.calls.append(("price", start.year))
        if zone in ("RS", "UA", "UA_IPS"):
            raise NoMatchingDataError
        idx = self._idx(start, end, "h")
        h = lh(idx)
        y = year_f(idx)
        base = np.array([YEAR_PRICE.get(int(v), 95) for v in y]) * (1 + 0.18 * np.cos(2 * np.pi * (doy(idx) - 15) / 365))
        dip = (30 + 130 * solar_scale(idx)) * np.exp(-((h - 13) ** 2) / 6) * (0.4 + 0.6 * np.clip(np.sin(2 * np.pi * (doy(idx) - 80) / 365) + 0.4, 0, 1))
        wk = np.where(idx.tz_convert(BUD).dayofweek >= 5, -18 * solar_scale(idx), 0)
        eve = 55 * np.exp(-((h - 19) ** 2) / 5)
        zoff = ZONE_OFF.get(zone, 0)
        # a zónák a magyar árhoz konvergálnak, ha az egyik a másiktól csak kismértékben tér el; a többi óra azonos
        z = base + eve - dip + wk
        z = np.where((np.abs(np.sin(secs(idx) / 40000.0 + hash(zone) % 7)) < 0.55) & (zone != "HU"), z, z + zoff)
        return pd.Series(np.round(z, 2), index=idx.tz_convert(BRU))

    def query_crossborder_flows(self, a, b, start, end, **kw):
        self.calls.append(("flow", start.year))
        nb = b if a == "HU" else a
        if nb == "UA":
            raise NoMatchingDataError
        idx = self._idx(start, end, "h")
        n = net_pattern(nb, idx) * (1 + 0.15 * (year_f(idx) - 2019) / 7)
        v = np.maximum(n, 0) if b == "HU" else np.maximum(-n, 0)
        return pd.Series(v, index=idx.tz_convert(BRU))

    def query_installed_generation_capacity(self, zone, start, end, **kw):
        same_offset(start, end)
        years = list(range(start.year, end.year + 1))
        rows = []
        for yr in years:
            sc = float(np.clip(0.04 + 0.16 * (yr - 2019), 0.04, 1.2))
            rows.append({"Nuclear": 1900, "Fossil Gas": 2900, "Fossil Brown coal/Lignite": 800 - 15 * (yr - 2019),
                         "Solar": 8500 * sc * 0.85, "Wind Onshore": 320, "Biomass": 260, "Waste": 40,
                         "Hydro Run-of-river and poundage": 60, "Other": 100})
        return pd.DataFrame(rows, index=pd.DatetimeIndex([f"{yr}-01-01" for yr in years], tz=BUD))

    def query_load_forecast(self, zone, start, end, **kw):
        self.calls.append(("load_forecast", start.year))
        idx = self._idx(start, end, "h")
        return pd.Series(load_model(idx) * 1.01, index=idx.tz_convert(BUD)).to_frame("Forecasted Load")

    def query_scheduled_exchanges(self, a, b, start, end, dayahead=False, **kw):
        self.calls.append(("sched", start.year))
        nb = b if a == "HU" else a
        if nb == "UA":
            raise NoMatchingDataError
        idx = self._idx(start, end, "h")
        n = net_pattern(nb, idx) * (1 + 0.15 * (year_f(idx) - 2019) / 7) * 0.97
        v = np.maximum(n, 0) if b == "HU" else np.maximum(-n, 0)
        return pd.Series(v, index=idx.tz_convert(BRU))
