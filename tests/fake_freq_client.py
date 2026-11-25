"""Kitalált Energy-Charts kliens a freq.py tesztjéhez és a DEMO adathoz. NEM valós mérés.

Másodperces frekvencia: 50 Hz körüli lassú ingadozás, az órafordulók körüli menetrendi lépcsők, és egy
kitalált erőműkiesés (2026-11-12 08:14:20 UTC körül) mély, lassan visszatérő beesésssel.
"""
import math
from datetime import datetime, timedelta, timezone

import numpy as np

EVENT = datetime(2026, 11, 12, 8, 14, 20, tzinfo=timezone.utc).timestamp()


def series_for(t0, t1, now):
    t = np.arange(int(t0), int(min(t1, now)) + 1, dtype=float)
    rng = np.random.default_rng(int(t0) // 86400)
    ou = np.zeros(len(t))
    for i in range(1, len(t)):
        ou[i] = ou[i - 1] * 0.995 + rng.normal(0, 0.0011)
    sec_in_h = t % 3600
    hour_step = 0.028 * np.exp(-((sec_in_h - 20) / 90.0) ** 2) * np.sign(np.sin(t // 3600 * 1.7))
    f = 50.0 + ou + hour_step + rng.normal(0, 0.004, len(t))
    dt = t - EVENT
    f = f - np.where(dt >= 0, 0.17 * (1 - np.exp(-np.clip(dt, 0, 8) / 2.5)) * np.exp(-np.maximum(dt - 8, 0) / 220.0), 0)
    return t, f


class FakeEnergyCharts:
    def __init__(self, now, v1_only=False, rate_limit_first=False, empty_days=()):
        self.now, self.v1_only, self.rate_limit_first = now, v1_only, rate_limit_first
        self.empty_days = set(empty_days)
        self.calls = []
        self._limited = False

    def get(self, url, params=None, headers=None, timeout=120):
        self.calls.append((url, dict(params or {})))
        if self.rate_limit_first and not self._limited:
            self._limited = True
            e = RuntimeError("HTTP 429")
            e.status_code, e.retry_after = 429, 0
            raise e
        v2 = "/v2/" in url
        if self.v1_only and v2:
            e = RuntimeError("HTTP 404")
            e.status_code = 404
            raise e
        a = datetime.fromisoformat(params["start"].replace("Z", "+00:00")).timestamp()
        b = datetime.fromisoformat(params["end"].replace("Z", "+00:00")).timestamp()
        if params["start"][:10] in self.empty_days:
            return {"data": []}
        t, f = series_for(a, b, self.now.timestamp())
        if not v2:
            return {"unix_seconds": [int(x) for x in t], "frequency": [round(float(x), 4) for x in f]}
        recs = [{"timestamp": datetime.fromtimestamp(x, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                 "values": {"frequency": round(float(y), 4)}} for x, y in zip(t, f)]
        return {"schema_version": "2.0", "endpoint": "/v2/frequency", "unit": "Hz", "resolution": "1 s",
                "series": [{"id": "frequency", "name": "Grid frequency"}], "data": recs,
                "license": "CC BY 4.0, energy-charts.info", "deprecated": False}
