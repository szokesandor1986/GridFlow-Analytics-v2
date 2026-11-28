"""Kitalált ENTSO-E kliens a tesztekhez és a DEMO adathoz. NEM valós mérés.

Ugyanazokat a metódusokat adja, mint az entsoe-py EntsoePandasClient, ugyanolyan alakú
(oszlopok, időzóna, felbontás) kimenettel, hogy a collector.py kódja végig lefusson rajta.
A hiányosságok szándékosak: Ukrajnára nincs adat, a Core-határokon nincs NTC, csak Szerbiára.
"""
import numpy as np
import pandas as pd
from entsoe.exceptions import NoMatchingDataError

BUD = "Europe/Budapest"
BRU = "Europe/Brussels"


def lh(idx):
    t = idx.tz_convert(BUD)
    return (t.hour + t.minute / 60).to_numpy()


_EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def secs(idx):
    """Másodperc az epoch óta; egységfüggetlen (az asi8 a pandas-időegységtől függ)."""
    return np.asarray((idx - _EPOCH) / pd.Timedelta(seconds=1), dtype=float)


def net_pattern(nb, idx):
    """Fizikai nettó áramlás (pozitív = import HU felé), MW."""
    h = lh(idx)
    solar = np.exp(-((h - 13) ** 2) / 12)
    evening = np.exp(-((h - 19) ** 2) / 6)
    n = {
        "AT": 650 - 350 * solar + 300 * evening,
        "SK": 300 - 450 * solar + 150 * evening,
        "RO": -150 - 250 * solar + 350 * evening,
        "HR": -250 - 120 * solar + 100 * evening,
        "SI": 80 + 60 * evening - 40 * solar,
        "RS": 110 - 150 * solar + 120 * evening,
    }[nb]
    t = secs(idx)
    return n + 22 * np.sin(t / 1700.0) + 12 * np.sin(t / 530.0)


def unscheduled(nb, idx):
    """Nem menetrendezett (hurok-) áramlás, MW: fizikai - menetrendezett."""
    t = secs(idx)
    return {
        "AT": 90 + 60 * np.sin(t / 15000.0),
        "SK": -70 + 40 * np.sin(t / 12000.0),
        "RO": 30 * np.sin(t / 9000.0),
        "HR": 20 + 15 * np.sin(t / 7000.0),
        "SI": 12 * np.sin(t / 5000.0),
        "RS": 40 * np.sin(t / 8000.0),
    }[nb]


def others(idx):
    """Nem gázerőművi termelés típusonként, MW (a gáz a maradék)."""
    h = lh(idx)
    t = secs(idx)
    day = ((idx.tz_convert(BUD).normalize() - pd.Timestamp("2026-01-01", tz=BUD)).days).to_numpy()
    clear = 0.72 + 0.28 * np.sin(day * 1.9)
    return {
        "solar": 2300 * np.exp(-((h - 12) ** 2) / (2 * 2.3**2)) * clear,
        "wind": 140 + 90 * np.sin(t / 21000.0),
        "coal": 240 + 10 * np.sin(t / 3000.0),
        "bio": 210 + 6 * np.sin(t / 4000.0),
        "hydro": 45 + 5 * np.sin(t / 6000.0),
        "other": 60 + 4 * np.sin(t / 2500.0),
    }


def load_target(idx):
    h = lh(idx)
    return 4500 + 1100 * np.exp(-((h - 8) ** 2) / 6) + 800 * np.exp(-((h - 12.5) ** 2) / 14) + 2100 * np.exp(-((h - 19) ** 2) / 7)


ZONE_SCALE = {"AT": 1.1, "SK": 0.7, "RO": 1.3, "HR": 0.5, "SI": 0.3, "RS": 0.9, "CZ": 1.4, "DE_LU": 11.0, "PL": 3.2,
              "BG": 0.8, "IT_NORD": 5.0, "FR": 9.0, "CH": 1.2, "NL": 2.5, "BE": 1.8, "ES": 4.5, "GR": 0.9, "PT": 1.5}


def zscale(zone):
    return ZONE_SCALE.get(zone, 1.0)


class FakeClient:
    def __init__(self, now):
        self.now = now
        self.pub_last = now.floor("h") - pd.Timedelta(hours=1)          # a legutóbbi közölt óra kezdete

    # ---------- segédek
    def _ser(self, f, start, end, freq, last=None, tz=BRU):
        stop = end if last is None else min(end, last)
        idx = pd.date_range(start, stop, freq=freq, tz="UTC", inclusive="left" if last is None else "both")
        if len(idx) == 0:
            raise NoMatchingDataError
        if freq == "h":      # az órás érték az óra átlaga, mint a 15 perces adatok órás átlaga
            vals = np.mean([f(idx + pd.Timedelta(minutes=15 * k)) for k in range(4)], axis=0)
        else:
            vals = f(idx)
        return pd.Series(vals, index=idx.tz_convert(tz))

    def _pub_end(self, freq):
        return self.pub_last + (pd.Timedelta(minutes=45) if freq == "15min" else pd.Timedelta(0))

    def _gen(self, idx):
        """Teljes termelési modell: típusonként és blokkonként, belsőleg összhangban a nettó importtal."""
        net = sum(net_pattern(nb, idx) for nb in ("AT", "SK", "RO", "HR", "SI", "RS"))
        o = others(idx)
        nuc = {1: 500.0, 2: 500.0, 3: 0.0, 4: 500.0}
        nuc = {k: v + 4 * np.sin(secs(idx) / (900.0 + 100 * k)) * (v > 0) for k, v in nuc.items()}
        nuc_tot = sum(nuc.values())
        gas = np.clip(load_target(idx) - net - nuc_tot - sum(o.values()), 60, None)
        outage_b = idx >= (self.now - pd.Timedelta(hours=6))             # a "B" gázblokk kiesik
        b = np.where(outage_b, 0.0, 0.15 * gas)
        a = 0.5 * gas + np.where(outage_b, 0.15 * gas, 0.0)
        c = 0.35 * gas
        load = nuc_tot + gas + sum(o.values()) + net
        return {"net": net, "o": o, "nuc": nuc, "gas": gas, "gasunits": (a, b, c), "load": load}

    # ---------- áramlás és ár
    def query_crossborder_flows(self, a, b, start, end, **kw):
        if "HU" not in (a, b):          # nem magyar határ: kitalált, de determinisztikus áramlás
            if "UA" in (a, b):
                raise NoMatchingDataError
            seed = sum(map(ord, min(a, b))) % 7
            sgn = 1 if a < b else -1
            f2 = lambda idx: np.maximum(sgn * (300 + 150 * seed) * np.sin(idx.asi8 / 3.6e12 / 9 + seed), 0)  # noqa: E731
            return self._ser(f2, start, min(end, self.now.floor("h")), "h")
        nb = b if a == "HU" else a
        if nb == "UA":
            raise NoMatchingDataError
        lag = 1 if nb == "SK" else 0
        freq = "15min" if nb == "AT" else "h"
        last = self.now.floor("h") - pd.Timedelta(hours=lag) + (pd.Timedelta(minutes=45) if freq == "15min" else pd.Timedelta(0))
        f = lambda idx: np.maximum(net_pattern(nb, idx), 0) if b == "HU" else np.maximum(-net_pattern(nb, idx), 0)  # noqa: E731
        return self._ser(f, start, min(end, last), freq)

    def query_day_ahead_prices(self, zone, start, end, **kw):
        if zone in ("UA", "RS"):
            raise NoMatchingDataError
        idx = pd.date_range(start, end, freq="15min", inclusive="left")
        h = lh(idx)
        day = (idx.tz_convert(BUD).normalize() - start.tz_convert(BUD).normalize()).days.to_numpy()
        base = 95 + 12 * np.sin(day * 1.7)
        shape = 70 * np.exp(-((h - 19) ** 2) / 5) + 35 * np.exp(-((h - 8) ** 2) / 4) - 115 * np.exp(-((h - 13) ** 2) / 7)
        off = {"HU": 0, "AT": -7, "SK": 4, "RO": 14, "HR": 3, "SI": -2, "CZ": -6, "DE_LU": -16, "PL": 9, "BG": 13,
               "IT_NORD": 15, "FR": -22, "CH": 5, "NL": -12, "BE": -14, "ES": -30, "GR": 16, "PT": -8}.get(zone, (sum(map(ord, zone)) % 31) - 15)
        return pd.Series(base + shape + off, index=idx.tz_convert(BRU)).round(2)

    # ---------- menetrend és kapacitás
    def query_scheduled_exchanges(self, a, b, start, end, dayahead=False, **kw):
        nb = b if a == "HU" else a
        if nb == "UA":
            raise NoMatchingDataError

        def f(idx):
            net = net_pattern(nb, idx) - unscheduled(nb, idx)
            if dayahead:
                net = net + 25 * np.sin(secs(idx) / 3000.0)
            return np.maximum(net, 0) if b == "HU" else np.maximum(-net, 0)

        if dayahead:
            return self._ser(f, start, end, "h")
        return self._ser(f, start, min(end, self._pub_end("h")), "h")

    def query_net_transfer_capacity_dayahead(self, a, b, start, end, **kw):
        nb = b if a == "HU" else a
        if nb != "RS":
            raise NoMatchingDataError              # Core flow-based határokon nincs határonkénti NTC
        base = 450 if b == "HU" else 520
        return self._ser(lambda idx: base + 40 * np.sin(secs(idx) / 40000.0), start, end, "h")

    def query_net_position(self, zone, start, end, dayahead=True, **kw):
        """Az entsoe-py konvenciója: pozitív = nettó export (a fake modellben a nettó import ellentettje)."""
        idx = pd.date_range(start, end, freq="h", tz="UTC", inclusive="left")
        if len(idx) == 0:
            raise NoMatchingDataError
        sign = -1.0 if getattr(self, "netpos_export_positive", True) else 1.0
        return pd.Series(sign * self._gen(idx)["net"] * zscale(zone), index=idx.tz_convert(BRU))

    # ---------- fogyasztás, termelés, előrejelzések
    def query_load(self, zone, start, end, **kw):
        s = self._ser(lambda idx: self._gen(idx)["load"], start, min(end, self._pub_end("15min")), "15min")
        return (s * zscale(zone)).to_frame("Actual Load")

    def query_load_forecast(self, zone, start, end, **kw):
        def f(idx):
            t = secs(idx)
            return load_target(idx) + 170 * np.sin(t / 9000.0) + 60 * np.sin(t / 1300.0)
        return (self._ser(f, start, end, "h") * zscale(zone)).to_frame("Forecasted Load")

    def query_generation(self, zone, start, end, nett=False, **kw):
        last = self._pub_end("15min")
        idx = pd.date_range(start, min(end, last), freq="15min", tz="UTC")
        g = self._gen(idx)
        o = g["o"]
        cols = {"Nuclear": sum(g["nuc"].values()), "Fossil Gas": g["gas"], "Fossil Brown coal/Lignite": o["coal"],
                "Solar": o["solar"], "Wind Onshore": o["wind"], "Biomass": o["bio"] * 0.8, "Waste": o["bio"] * 0.2,
                "Hydro Run-of-river and poundage": o["hydro"], "Other": o["other"]}
        return pd.DataFrame(cols, index=idx.tz_convert(BUD)).clip(lower=0) * zscale(zone)

    def query_wind_and_solar_forecast(self, zone, start, end, **kw):
        idx = pd.date_range(start, end, freq="h", tz="UTC", inclusive="left")
        o = others(idx)
        t = secs(idx)
        return pd.DataFrame({"Solar": o["solar"] * (1.0 + 0.18 * np.sin(t / 7000.0) + 0.05),
                             "Wind Onshore": o["wind"] * (1.0 + 0.3 * np.sin(t / 5000.0))}, index=idx.tz_convert(BUD)).clip(lower=0) * zscale(zone)

    def query_installed_generation_capacity(self, zone, start, end, **kw):
        cols = {"Nuclear": 2000, "Fossil Gas": 2900, "Fossil Brown coal/Lignite": 700, "Solar": 8500,
                "Wind Onshore": 330, "Biomass": 260, "Waste": 40, "Hydro Run-of-river and poundage": 60, "Other": 100}
        idx = pd.DatetimeIndex(["2025-01-01", "2026-01-01"], tz=BUD)
        return pd.DataFrame({k: [v * 0.97, v] for k, v in cols.items()}, index=idx)

    def query_installed_generation_capacity_per_unit(self, zone, start, end, **kw):
        rows = [(f"Atomerőmű, {k}. blokk", "Nuclear", 500.0) for k in (1, 2, 3, 4)] + [
            ("Lignit blokk", "Fossil Brown coal/Lignite", 300.0), ("Gázblokk A", "Fossil Gas", 1600.0),
            ("Gázblokk B", "Fossil Gas", 500.0), ("Gázblokk C", "Fossil Gas", 900.0)]
        return pd.DataFrame({"Name": [r[0] for r in rows], "Production Type": [r[1] for r in rows],
                             "Installed Capacity [MW]": [r[2] for r in rows]}, index=[f"FAKE-EIC-{i}" for i in range(len(rows))])

    def query_generation_per_plant(self, zone, start, end, **kw):
        idx = pd.date_range(start, min(end, self._pub_end("15min")), freq="15min", tz="UTC")
        g = self._gen(idx)
        a, b, c = g["gasunits"]
        data = {}
        for k, v in g["nuc"].items():
            data[(f"Atomerőmű, {k}. blokk", "Nuclear", "Actual Aggregated")] = v
        data[("Lignit blokk", "Fossil Brown coal/Lignite", "Actual Aggregated")] = g["o"]["coal"]
        data[("Gázblokk A", "Fossil Gas", "Actual Aggregated")] = a
        data[("Gázblokk B", "Fossil Gas", "Actual Aggregated")] = b
        data[("Gázblokk C", "Fossil Gas", "Actual Aggregated")] = c
        df = pd.DataFrame(data, index=idx.tz_convert(BUD))
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        return df

    # ---------- kiesések
    def _outage_frame(self, rows, headers):
        df = pd.DataFrame(rows, columns=headers)
        return df.set_index("created_doc_time").sort_index()

    def query_unavailability_of_generation_units(self, zone, start, end, **kw):
        n = self.now
        H = ["created_doc_time", "docstatus", "mrid", "revision", "businesstype", "biddingzone_domain", "qty_uom", "curvetype",
             "production_resource_id", "production_resource_name", "production_resource_psr_name", "production_resource_location",
             "plant_type", "nominal_power", "start", "end", "resolution", "pstn", "avail_qty"]

        def r(created, st, mrid, rev, bt, name, typ, nom, s, e, av):
            return [created, st, mrid, rev, bt, "HU", "MAW", "A01", "X", name, name, "HU", typ, nom, s, e, "PT60M", 1, av]
        d = pd.Timedelta
        rows = [
            r(n - d(days=12), "Active", "G-1", 1, "Planned maintenance", "Atomerőmű, 3. blokk", "Nuclear", 500.0, n - d(days=10), n + d(days=14), 0.0),
            r(n - d(hours=7), "Active", "G-2", 1, "Unplanned outage", "Gázblokk B", "Fossil Gas", 400.0, n - d(hours=6), n + d(hours=12), 0.0),
            r(n - d(hours=3), "Active", "G-2", 2, "Unplanned outage", "Gázblokk B", "Fossil Gas", 400.0, n - d(hours=6), n + d(hours=30), 0.0),
            r(n - d(days=2), "Cancelled", "G-3", 1, "Planned maintenance", "Lignit blokk", "Fossil Brown coal/Lignite", 240.0, n + d(days=1), n + d(days=3), 0.0),
            r(n - d(days=5), "Active", "G-4", 1, "Planned maintenance", "Gázblokk C", "Fossil Gas", 400.0, n + d(days=3), n + d(days=9), 180.0),
            r(n - d(days=20), "Active", "G-5", 1, "Planned maintenance", "Atomerőmű, 1. blokk", "Nuclear", 500.0, n + d(days=25), n + d(days=40), 0.0),
        ]
        return self._outage_frame(rows, H)

    def query_unavailability_transmission(self, a, b, start, end, **kw):
        nb = b if a == "HU" else a
        n = self.now
        d = pd.Timedelta
        H = ["created_doc_time", "docstatus", "mrid", "revision", "businesstype", "in_domain", "out_domain", "qty_uom", "curvetype",
             "start", "end", "resolution", "pstn", "avail_qty"]
        if nb == "SK":
            rows = [[n - d(days=3), "Active", f"T-SK-{a}", 1, "Planned maintenance", b, a, "MAW", "A01", n + d(days=2), n + d(days=5), "PT60M", 1, 400.0]]
        elif nb == "RS" and a == "RS":
            rows = [[n - d(hours=4), "Active", "T-RS-1", 1, "Unplanned outage", b, a, "MAW", "A01", n - d(hours=3), n + d(hours=20), "PT60M", 1, 0.0]]
        else:
            raise NoMatchingDataError
        return self._outage_frame(rows, H)

    # ---------- rendszeregyensúly
    def query_imbalance_prices(self, zone, start, end, **kw):
        def f(idx):
            t = secs(idx)
            base = 110 + 40 * np.sin(t / 8000.0)
            return base
        idx = pd.date_range(start, min(end, self._pub_end("15min")), freq="15min", tz="UTC")
        base = f(idx)
        spike = 160 * np.exp(-((lh(idx) - 18.5) ** 2) / 1.5)
        return pd.DataFrame({"Long": base - 25, "Short": base + 20 + spike}, index=idx.tz_convert(BUD))

    def query_imbalance_volumes(self, zone, start, end, **kw):
        idx = pd.date_range(start, min(end, self._pub_end("15min")), freq="15min", tz="UTC")
        t = secs(idx)
        return pd.DataFrame({"Imbalance Volume": 60 * np.sin(t / 4500.0) + 25 * np.sin(t / 700.0)}, index=idx.tz_convert(BUD))

    def query_aggregated_bids(self, zone, process_type, start, end, **kw):
        """12.3.E: (irány, mrid, 'Offered'|'Activated'); két termékidősor irányonként, mint az éles közlésben."""
        idx = pd.date_range(start, min(end, self._pub_end("15min")), freq="15min", tz="UTC")
        t = secs(idx)
        k = 1.0 if process_type == "A51" else 0.6
        up = np.maximum(0, np.sin(t / 5200.0)) * 70 * k + 8 * k
        dn = np.maximum(0, -np.sin(t / 5200.0)) * 60 * k + 6 * k
        cols = {("Up", 1, "Offered"): 400 * k + 0 * up, ("Up", 1, "Activated"): up * 0.8, ("Up", 2, "Offered"): 80 * k + 0 * up, ("Up", 2, "Activated"): up * 0.2,
                ("Down", 3, "Offered"): 380 * k + 0 * dn, ("Down", 3, "Activated"): dn}
        df = pd.DataFrame(cols, index=idx.tz_convert(BUD))
        df.columns = pd.MultiIndex.from_tuples(df.columns, names=("direction", "mrid", "unit"))
        return df

    def query_activated_balancing_energy_prices(self, zone, start, end, process_type="A16", business_type=None, **kw):
        idx = pd.date_range(start, min(end, self._pub_end("15min")), freq="15min", tz="UTC")
        t = secs(idx)
        k = 1.0 if business_type == "A96" else 1.3
        return pd.DataFrame({"Up": 130 * k + 40 * np.sin(t / 7000.0), "Down": 60 / k + 20 * np.sin(t / 6000.0), "ReserveType": "aFRR"}, index=idx.tz_convert(BUD))

    def query_financial_balance(self, zone, start, end, **kw):
        """17.1.I: havi, két irány (A01 = up, A02 = down), a helyi pénznemben."""
        months = pd.period_range(pd.Timestamp(start).tz_localize(None) if pd.Timestamp(start).tzinfo else pd.Timestamp(start), pd.Timestamp(end).tz_localize(None) if pd.Timestamp(end).tzinfo else pd.Timestamp(end), freq="M")
        rows = []
        for i, m in enumerate(months[:-1] if len(months) > 1 else months):
            base = 1.2e9 + 2.5e8 * np.sin(i / 3.0)
            rows.append({"month": str(m), "dir": "up", "amount": float(round(base)), "currency": "HUF"})
            rows.append({"month": str(m), "dir": "down", "amount": float(round(base * (0.55 + 0.25 * np.sin(i / 2.0)))), "currency": "HUF"})
        return rows, {"timeseries": ["businesstype", "currency_unit.name", "curvetype", "mrid"], "point": ["amount", "direction", "position"], "resolution": "P1M"}

    def query_activated_balancing_energy(self, zone, start, end, business_type, **kw):
        raise NoMatchingDataError              # az éles HU-adatban a régi 17.1.E közlés megszűnt
        idx = pd.date_range(start, min(end, self._pub_end("15min")), freq="15min", tz="UTC")
        t = secs(idx)
        k = 1.0 if business_type == "A96" else 0.6
        up = np.maximum(0, np.sin(t / 5200.0)) * 70 * k + 8 * k
        dn = np.maximum(0, -np.sin(t / 5200.0)) * 60 * k + 6 * k
        return pd.DataFrame({"Up": up, "Down": dn}, index=idx.tz_convert(BUD))
