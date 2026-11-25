"""Kitalált AGSI+ / ENTSOG kliens a gas.py tesztjéhez és a DEMO adathoz. NEM valós mérés.

Ugyanazt a get(url, params, headers, timeout) felületet adja, mint a gas.Http, és ugyanolyan alakú választ
(idézőjeles számok az AGSI+-nál, "operationaldatas" lista az ENTSOG-nál, kWh/d egység).
A pontkulcsok kitaláltak (DEMO-...), a valódiakat a gas.py futáskor az /interconnections végpontról deríti fel.
"""
import math
from datetime import date, datetime, timedelta

CAP = {  # munkagáz-kapacitás TWh, csúcs-töltöttség %, tél végi mélypont %
    "HU": (67.0, 92, 30), "AT": (95.0, 90, 25), "SK": (36.0, 93, 35), "RO": (31.0, 88, 22),
    "HR": (6.0, 85, 20), "UA": (310.0, 70, 18), "DE": (250.0, 94, 25), "IT": (194.0, 95, 30),
    "CZ": (44.0, 92, 28), "PL": (36.0, 98, 40), "BG": (6.0, 90, 20), "NL": (140.0, 96, 22),
    "FR": (130.0, 95, 28), "EU": (1130.0, 93, 28),
}


def fill_pct(code, d, bias=0.0):
    """Szezonális görbe: kb. nov. 1-jén csúcs, kb. márc. 31-én mélypont (gázév: okt. 1 – szept. 30).
    Az évenkénti eltérés (bias) a gázév két végén nullára simul, így nincs ugrás a gázévek határán."""
    hi, lo = CAP[code][1], CAP[code][2]
    gy_start = date(d.year if d.month >= 10 else d.year - 1, 10, 1)
    t = (d - gy_start).days
    if t < 31:
        x = hi - 10 * (31 - t) / 31
    elif t < 182:
        x = hi - (hi - lo) * ((t - 31) / 151) ** 1.1
    else:
        x = lo + (hi - lo - 10) * min(1, (t - 182) / 183) ** 0.9
    x += bias * math.sin(math.pi * min(t, 364) / 365)
    return max(3.0, min(99.5, x + 1.5 * math.sin(d.toordinal() / 9.0)))


def agsi_record(code, d, today):
    cap = CAP[code][0]
    gy = d.year if d.month >= 10 else d.year - 1
    yr_bias = ((gy * 7 + (1 if code == "HU" else 3)) % 9) - 4
    f = fill_pct(code, d, yr_bias)
    f_prev = fill_pct(code, d - timedelta(days=1), yr_bias)
    gis = cap * f / 100
    net_gwh = (f_prev - f) / 100 * cap * 1000          # pozitív = kivétel
    inj, wdr = max(0.0, -net_gwh), max(0.0, net_gwh)
    scale = 1.0 / 300 if code != "EU" else 1.0
    rec = {
        "name": COUNTRY(code), "code": code, "url": code.lower(), "gasDayStart": d.isoformat(),
        "gasInStorage": f"{gis:.4f}", "consumption": "n/a", "consumptionFull": "n/a",
        "injection": f"{inj:.2f}", "withdrawal": f"{wdr:.2f}", "netWithdrawal": f"{wdr - inj:.2f}",
        "workingGasVolume": f"{cap:.2f}", "injectionCapacity": f"{cap * 1000 * 0.0045:.2f}",
        "withdrawalCapacity": f"{cap * 1000 * 0.0075:.2f}", "status": "E",
        "trend": f"{(inj - wdr) / (cap * 1000) * 100:.3f}", "full": f"{f:.2f}",
        "info": [], "updatedAt": f"{(today).isoformat()} 19:41:00",
    }
    if code == "HU" and d == today - timedelta(days=1):
        rec["children"] = [
            {"name": "MFGT (DEMO)", "code": "21XDEMO000000001", "gasInStorage": f"{gis * 0.62:.3f}", "workingGasVolume": f"{cap * 0.62:.2f}",
             "full": f"{f + 1:.2f}", "injection": f"{inj * 0.62:.1f}", "withdrawal": f"{wdr * 0.62:.1f}",
             "injectionCapacity": f"{cap * 4.5 * 0.62:.1f}", "withdrawalCapacity": f"{cap * 7.5 * 0.62:.1f}", "status": "E"},
            {"name": "HEXUM (DEMO)", "code": "21XDEMO000000002", "gasInStorage": f"{gis * 0.38:.3f}", "workingGasVolume": f"{cap * 0.38:.2f}",
             "full": f"{f - 1:.2f}", "injection": f"{inj * 0.38:.1f}", "withdrawal": f"{wdr * 0.38:.1f}",
             "injectionCapacity": f"{cap * 4.5 * 0.38:.1f}", "withdrawalCapacity": f"{cap * 7.5 * 0.38:.1f}", "status": "E"},
        ]
    return rec


def COUNTRY(code):
    return {"EU": "Europe"}.get(code, code)


POINTS = [  # (kulcs, címke, szomszéd, hu-oldali irány, alap GWh/nap, téli többlet)
    ("DEMO-PT-AT", "Mosonmagyaróvár (DEMO)", "AT", "entry", 40, 30),
    ("DEMO-PT-SK", "Balassagyarmat (DEMO)", "SK", "exit", 25, 30),
    ("DEMO-PT-RO", "Csanádpalota (DEMO)", "RO", "exit", 12, 14),
    ("DEMO-PT-HR", "Drávaszerdahely (DEMO)", "HR", "exit", 10, 12),
    ("DEMO-PT-RS", "Kiskundorozsma (DEMO)", "RS", "entry", 120, 70),
    ("DEMO-PT-UA", "VIP Bereg (DEMO)", "UA", "exit", 12, 22),
]


def winter(d):
    return 0.5 + 0.5 * math.cos((d.timetuple().tm_yday - 20) / 365.0 * 2 * math.pi)


# ---- ALSI (LNG): (kulcs, név, vállalat, ország, típus, szélesség, hosszúság, DTMI GWh, DTRS GWh/nap, alap kihasználtság)
LNG_TERMINALS = [
    ("DEMO-ES-1", "Barcelona (DEMO)", "Enagas (DEMO)", "ES", "LAND", 41.32, 2.17, 960, 540, 0.55),
    ("DEMO-ES-2", "Huelva (DEMO)", "Enagas (DEMO)", "ES", "LAND", 37.20, -6.93, 820, 400, 0.45),
    ("DEMO-ES-3", "Bilbao BBG (DEMO)", "BBG (DEMO)", "ES", "LAND", 43.35, -3.04, 480, 250, 0.50),
    ("DEMO-FR-1", "Montoir (DEMO)", "Elengy (DEMO)", "FR", "LAND", 47.30, -2.15, 790, 370, 0.60),
    ("DEMO-FR-2", "Fos Cavaou (DEMO)", "Fosmax (DEMO)", "FR", "LAND", 43.40, 4.85, 780, 410, 0.65),
    ("DEMO-FR-3", "Dunkerque (DEMO)", "Dunkerque LNG (DEMO)", "FR", "LAND", 51.03, 2.20, 740, 550, 0.75),
    ("DEMO-IT-1", "Adriatic LNG (DEMO)", "Adriatic (DEMO)", "IT", "LAND", 45.05, 12.60, 1000, 260, 0.80),
    ("DEMO-IT-2", "Panigaglia (DEMO)", "GNL Italia (DEMO)", "IT", "LAND", 44.05, 9.85, 100, 130, 0.35),
    ("DEMO-IT-3", "Piombino FSRU (DEMO)", "SNAM FSRU (DEMO)", "IT", "FSRU", 42.93, 10.55, 170, 150, 0.85),
    ("DEMO-NL-1", "Gate Rotterdam (DEMO)", "Gate (DEMO)", "NL", "LAND", 51.95, 4.05, 700, 400, 0.70),
    ("DEMO-NL-2", "Eemshaven FSRU (DEMO)", "EET (DEMO)", "NL", "FSRU", 53.45, 6.83, 170, 150, 0.80),
    ("DEMO-BE-1", "Zeebrugge (DEMO)", "Fluxys LNG (DEMO)", "BE", "LAND", 51.33, 3.20, 560, 480, 0.55),
    ("DEMO-PL-1", "Świnoujście (DEMO)", "Polskie LNG (DEMO)", "PL", "LAND", 53.90, 14.28, 180, 150, 0.85),
    ("DEMO-DE-1", "Wilhelmshaven FSRU (DEMO)", "Uniper (DEMO)", "DE", "FSRU", 53.52, 8.10, 170, 220, 0.60),
    ("DEMO-DE-2", "Brunsbüttel FSRU (DEMO)", "DET (DEMO)", "DE", "FSRU", 53.89, 9.14, 170, 200, 0.50),
    ("DEMO-GR-1", "Revithoussa (DEMO)", "DESFA (DEMO)", "GR", "LAND", 37.95, 23.40, 80, 140, 0.50),
    ("DEMO-GR-2", "Alexandroupolis FSRU (DEMO)", "Gastrade (DEMO)", "GR", "FSRU", 40.77, 25.80, 150, 150, 0.60),
    ("DEMO-PT-1", "Sines (DEMO)", "REN (DEMO)", "PT", "LAND", 37.95, -8.85, 130, 200, 0.45),
    ("DEMO-LT-1", "Klaipėda FSRU (DEMO)", "KN (DEMO)", "LT", "FSRU", 55.72, 21.10, 100, 130, 0.50),
    ("DEMO-HR-1", "Krk FSRU (DEMO)", "LNG Croatia (DEMO)", "HR", "FSRU", 45.22, 14.57, 160, 100, 0.75),
    ("DEMO-GB-1", "Isle of Grain (DEMO)", "Grain LNG (DEMO)", "GB", "LAND", 51.44, 0.72, 1050, 600, 0.50),
]
LNG_EU = {t[3] for t in LNG_TERMINALS} - {"GB"}
LNG_NAMES = {"ES": "Spain", "FR": "France", "IT": "Italy", "NL": "Netherlands", "BE": "Belgium", "PL": "Poland", "DE": "Germany",
             "GR": "Greece", "PT": "Portugal", "LT": "Lithuania", "HR": "Croatia", "GB": "United Kingdom"}


def lng_terminal_day(t, d):
    """Egy terminál napi (készlet GWh, kiadás GWh/nap) értéke: télen nagyobb kiadás, hajóérkezések fűrészfoga a készletben."""
    key, _n, _c, _cc, _tp, _la, _lo, dtmi, dtrs, base = t
    dtmi *= 5            # a DEMO-érték a valós nagyságrendhez igazítva (a táblában egység-arányos szám áll)
    seed = sum(map(ord, key))
    w = winter(d)
    send = dtrs * min(1.0, base * (0.75 + 0.55 * w) + 0.04 * math.sin(d.toordinal() / 2.0 + seed))
    saw = ((d.toordinal() + seed) % 9) / 9.0                     # 9 naponta egy hajó
    inv = dtmi * min(0.98, max(0.08, 0.35 + 0.45 * (1 - saw) * (0.6 + 0.4 * (1 - w)) + 0.08 * math.sin(d.toordinal() / 30.0 + seed)))
    return inv, send


class FakeHttp:
    def __init__(self, today, key="demo", fail_entsog=False, fail_agsi_country=(), no_opd=False, fail_alsi=False, alsi_key=None):
        self.today, self.key = today, key
        self.fail_entsog, self.fail_agsi_country = fail_entsog, set(fail_agsi_country)
        self.no_opd = no_opd
        self.fail_alsi, self.alsi_key = fail_alsi, alsi_key or key
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=60):
        params = params or {}
        self.calls.append((url, dict(params)))
        if "alsi" in url:
            return self._alsi(params, headers or {})
        if "agsi" in url:
            return self._agsi(params, headers or {})
        if "operatorpointdirections" in url:
            if self.no_opd:
                raise RuntimeError("HTTP 500")
            return self._opd()
        if "interconnections" in url:
            return self._inter()
        return self._flows(params)

    # ---- AGSI+
    def _agsi(self, p, headers):
        if headers.get("x-key") != self.key:
            e = RuntimeError("HTTP 403")
            e.status_code = 403
            raise e
        code = "EU" if p.get("type") == "eu" else p.get("country")
        if code in self.fail_agsi_country:
            raise RuntimeError("HTTP 500")
        if code not in CAP:
            return {"last_page": 1, "total": 0, "dataset": "x", "gas_day": "", "data": []}
        a = datetime.strptime(p["from"], "%Y-%m-%d").date()
        b = min(datetime.strptime(p["to"], "%Y-%m-%d").date(), self.today - timedelta(days=1))
        days = [b - timedelta(days=i) for i in range((b - a).days + 1)]      # az AGSI+ alapból csökkenő sorrend
        size, page = int(p.get("size", 30)), int(p.get("page", 1))
        chunk = days[(page - 1) * size: page * size]
        return {"last_page": max(1, math.ceil(len(days) / size)), "total": len(days), "dataset": "demo",
                "gas_day": b.isoformat(), "data": [agsi_record(code, d, self.today) for d in chunk]}

    # ---- ALSI
    def _alsi(self, p, headers):
        if headers.get("x-key") != self.alsi_key:
            e = RuntimeError("HTTP 403")
            e.status_code = 403
            raise e
        if self.fail_alsi:
            raise RuntimeError("HTTP 500")
        eu = p.get("type") == "eu"
        code = "EU" if eu else p.get("country")
        terms = [t for t in LNG_TERMINALS if (t[3] in LNG_EU if eu else t[3] == code)]
        if not terms:
            return {"last_page": 1, "total": 0, "dataset": "x", "gas_day": "", "data": []}
        a = datetime.strptime(p["from"], "%Y-%m-%d").date()
        b = min(datetime.strptime(p["to"], "%Y-%m-%d").date(), self.today - timedelta(days=1))
        days = [b - timedelta(days=i) for i in range((b - a).days + 1)]
        size, page = int(p.get("size", 30)), int(p.get("page", 1))
        chunk = days[(page - 1) * size: page * size]
        return {"last_page": max(1, math.ceil(len(days) / size)), "total": len(days), "dataset": "demo", "gas_day": b.isoformat(),
                "data": [self._alsi_rec(code, eu, terms, d) for d in chunk]}

    def _alsi_rec(self, code, eu, terms, d):
        def agg(ts):
            inv = sum(lng_terminal_day(t, d)[0] for t in ts)
            snd = sum(lng_terminal_day(t, d)[1] for t in ts)
            return {"inventory": {"lng": f"{inv / 6.4:.2f}", "gwh": f"{inv:.1f}"}, "sendOut": f"{snd:.1f}",
                    "dtmi": {"lng": f"{sum(t[7] * 5 for t in ts) / 6.4:.2f}", "gwh": f"{sum(t[7] * 5 for t in ts):.1f}"},
                    "dtrs": f"{sum(t[8] for t in ts):.1f}", "status": "E", "info": []}
        rec = {"name": "Europe" if eu else LNG_NAMES.get(code, code), "code": code, "url": code.lower(), "gasDayStart": d.isoformat(),
               "updatedAt": f"{self.today.isoformat()} 08:15:00", **agg(terms)}
        if eu:
            rec["children"] = [{"name": LNG_NAMES.get(c, c), "code": c, "url": c.lower(), **agg([t for t in terms if t[3] == c])}
                               for c in sorted({t[3] for t in terms})]
        else:
            comp = {}
            for t in terms:
                comp.setdefault(t[2], []).append(t)
            kids = []
            for cname, ts in comp.items():
                fl = []
                for t in ts:
                    f = {"name": t[1], "code": t[0], "url": t[0].lower(), "gasDayStart": d.isoformat(), "type": t[4],
                         "latitude": str(t[5]), "longitude": str(t[6]), **agg([t])}
                    fl.append(f)
                kids.append({"name": cname, "code": "COMP-" + cname[:6], "url": "c", **agg(ts), "children": fl})
            rec["children"] = kids
        return rec

    # ---- ENTSOG
    def _opd(self):
        recs = []
        for key, label, nb, side, *_ in POINTS:
            recs.append({"operatorKey": "HU-TSO-0001", "pointKey": key, "pointLabel": label, "directionKey": side,
                         "tSOCountry": "HU", "adjacentCountry": nb})
            recs.append({"operatorKey": f"{nb}-TSO-DEMO", "pointKey": key, "pointLabel": label,
                         "directionKey": "exit" if side == "entry" else "entry", "tSOCountry": nb, "adjacentCountry": "HU"})
        recs.append({"operatorKey": "HU-TSO-0001", "pointKey": "DEMO-UGS", "pointLabel": "Belső tároló", "directionKey": "entry",
                     "tSOCountry": "HU", "adjacentCountry": ""})
        return {"operatorpointdirections": recs}

    def _inter(self):
        recs = []
        for key, label, nb, side, *_ in POINTS:
            if side == "entry":      # a szomszéd -> HU
                recs.append({"pointKey": key, "pointLabel": label, "fromCountryKey": nb, "toCountryKey": "HU",
                             "fromOperatorKey": f"{nb}-TSO-DEMO", "toOperatorKey": "HU-TSO-0001"})
            else:
                recs.append({"pointKey": key, "pointLabel": label, "fromCountryKey": "HU", "toCountryKey": nb,
                             "fromOperatorKey": "HU-TSO-0001", "toOperatorKey": f"{nb}-TSO-DEMO"})
        recs.append({"pointKey": "DEMO-OTHER", "pointLabel": "Nem magyar pont", "fromCountryKey": "AT", "toCountryKey": "DE",
                     "fromOperatorKey": "AT-TSO-X", "toOperatorKey": "DE-TSO-X"})
        return {"interconnections": recs}

    def _flows(self, p):
        if self.fail_entsog:
            raise RuntimeError("HTTP 500")
        a = datetime.strptime(p["from"], "%Y-%m-%d").date()
        b = datetime.strptime(p["to"], "%Y-%m-%d").date()
        wanted = [x for x in p["pointDirection"].split(",") if x]
        out = []
        for key, label, nb, side, base, extra in POINTS:
            if f"HU-TSO-0001{key}{side}" not in wanted:
                continue
            for i in range((b - a).days + 1):
                d = a + timedelta(days=i)
                v = base + extra * winter(d) + 4 * math.sin(d.toordinal() / 3.0 + len(key))
                out.append({"indicator": "Physical Flow", "periodType": "day", "periodFrom": f"{d.isoformat()}T06:00:00+01:00",
                            "periodTo": f"{(d + timedelta(days=1)).isoformat()}T06:00:00+01:00", "operatorKey": "HU-TSO-0001",
                            "pointKey": key, "pointLabel": label, "directionKey": side, "unit": "kWh/d",
                            "value": round(max(0.0, v) * 1e6)})
        return {"meta": {"count": len(out)}, "operationaldatas": out}
