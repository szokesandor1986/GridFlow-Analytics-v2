"""Kitalált Open-Meteo kliens a weather.py tesztjéhez és a DEMO adathoz. NEM valós időjárás.

Napi menetű hőmérséklet, a napmagasságból számolt sugárzás (felhőzettel csillapítva), lassan változó szél,
néhány kitalált csapadékos óra. A válasz alakja az Open-Meteo többhelyes válaszát követi (lista, "hourly" objektummal).
"""
import math
from datetime import datetime, timedelta, timezone


def _sun_elev(lat, lon, t):
    doy = t.timetuple().tm_yday
    decl = math.radians(23.44) * math.sin(2 * math.pi * (doy - 81) / 365)
    hours = t.hour + t.minute / 60 + lon / 15.0
    ha = math.radians(15 * (hours - 12))
    la = math.radians(lat)
    return math.asin(math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha))


class FakeOpenMeteo:
    def __init__(self, now, fail=False, drop_var=None):
        self.now, self.fail, self.drop_var = now, fail, drop_var
        self.calls = []

    def get(self, url, params=None, timeout=60):
        self.calls.append((url, dict(params or {})))
        if self.fail:
            raise RuntimeError("HTTP 500")
        lats = [float(x) for x in params["latitude"].split(",")]
        lons = [float(x) for x in params["longitude"].split(",")]
        pd_, fd = int(params.get("past_days", 0)), int(params.get("forecast_days", 7))
        d0 = datetime(self.now.year, self.now.month, self.now.day, tzinfo=timezone.utc) - timedelta(days=pd_)
        n = (pd_ + fd) * 24
        times = [d0 + timedelta(hours=i) for i in range(n)]
        out = []
        for k, (la, lo) in enumerate(zip(lats, lons)):
            cloud, temp, wind, rad, prec = [], [], [], [], []
            for i, t in enumerate(times):
                c = 55 + 40 * math.sin(i / 17.0 + k * .6) * math.sin(i / 41.0 + 1)
                c = max(0, min(100, c))
                el = _sun_elev(la, lo, t)
                g = max(0.0, math.sin(el)) * 720 * (1 - 0.75 * (c / 100) ** 1.6)
                tmp = 5 + 4 * math.sin(i / 53.0 + k * .2) + 3.5 * math.sin(2 * math.pi * (t.hour + lo / 15 - 9) / 24) - (la - 47) * .8
                w = 6.5 + 3.5 * math.sin(i / 29.0 + k) + 1.2 * math.sin(i / 7.0)
                p = max(0.0, math.sin(i / 23.0 + k * 1.3) - .72) * 6
                cloud.append(round(c)); temp.append(round(tmp, 1)); wind.append(round(max(0.3, w), 1)); rad.append(round(g)); prec.append(round(p, 1))
            hourly = {"time": [int(t.timestamp()) for t in times], "temperature_2m": temp, "wind_speed_120m": wind,
                      "shortwave_radiation": rad, "cloud_cover": cloud, "precipitation": prec}
            if self.drop_var:
                hourly.pop(self.drop_var, None)
            out.append({"latitude": la, "longitude": lo, "hourly": hourly, "hourly_units": {}})
        return out
