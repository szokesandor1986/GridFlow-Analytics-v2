"""Kitalált HUPX IIP kliens: lapozás (nextCursor), 401, átmeneti 500."""
from datetime import datetime, timedelta, timezone


def umm(i, now, planned=True, open_end=False, unit="MW"):
    s = now - timedelta(hours=6 * i)
    e = "0001-01-01T00:00:00Z" if open_end else (s + timedelta(days=2 + i)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"threadKey": f"demo-unit-{i}", "versionNo": 2, "action": "UPDATE", "category": "ELECTRICITY",
            "publishedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "firstPublishedAt": s.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "message": {"messageId": f"demo-{i}_002", "title": f"DEMO egység {i} karbantartás",
                        "event": {"eventStatus": "ACTIVE", "eventType": "Production unavailability",
                                  "eventStart": s.strftime("%Y-%m-%dT%H:%M:%SZ"), "eventStop": e},
                        "unavailabilityType": "Planned" if planned else "Unplanned",
                        "capacity": {"unitMeasure": unit, "installedCapacity": 200 + 50 * i, "capacityIntervals": [
                            {"intervalStart": s.strftime("%Y-%m-%dT%H:%M:%SZ"), "intervalStop": e if not open_end else (s + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                             "unavailableCapacity": 100 + 25 * i, "availableCapacity": 100 + 25 * i}]},
                        "unavailabilityReason": "Planned maintenance", "unavailabilityReasonHun": "Tervezett karbantartás",
                        "fuelType": "Fossil Gas" if i % 2 else "Hydro",
                        "affectedAsset": {"name": f"DEMO egység {i}", "eic": f"10WDEMO{i:010d}"},
                        "marketParticipants": [{"name": "DEMO Termelő Zrt.", "ace": "A0.HU"}]}}


class FakeHupx:
    def __init__(self, n=7, page=3, key="k", fail_500=0, now=None):
        self.now = now or datetime.now(timezone.utc)
        self.items = [umm(i, self.now, planned=i % 3 != 0, open_end=i == 4, unit="GWh/d" if i == 5 else "MW") for i in range(n)]
        self.items.append(dict(self.items[0]))          # duplikált szál
        self.page, self.key, self.fail_500, self.calls, self.last_params = page, key, fail_500, 0, []

    def get(self, url, params=None, headers=None, timeout=60):
        self.calls += 1
        self.last_params.append(dict(params or {}))
        if (headers or {}).get("Authorization") != f"Bearer {self.key}":
            e = RuntimeError("HTTP 401"); e.status_code = 401; raise e
        if self.fail_500 > 0:
            self.fail_500 -= 1
            e = RuntimeError("HTTP 500"); e.status_code = 500; raise e
        off = int((params or {}).get("cursor") or 0)
        chunk = self.items[off:off + self.page]
        r = {"items": chunk, "count": len(chunk)}
        if off + self.page < len(self.items):
            r["nextCursor"] = str(off + self.page)
        return r
