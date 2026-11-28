/* GridFlow Analytics – a hosszú távú adattár (hist/) olvasója a böngészőben.
   - Betölti a manifest.json-t és a catalog.json-t; a partíciókat csak akkor kéri le, ha kellenek, a manifest hash-ével
     (?v=hash) tartósan gyorsítótárazva; a letöltött fájlok a memóriában maradnak.
   - Ha a hist/ még nincs a kiszolgálón, a havi history.json-ból épít azonos alakú havi/éves adatot (mode "monthly").
   - Nem interpolál, nem tölt ki hiányt: a hiányzó érték null.
   Az időszak határai helyi (Europe/Budapest) naptári napok: "YYYY-MM-DD". */
(function () {
  "use strict";
  var H = (window.GFHist = {}), TZ = "Europe/Budapest", cache = {}, M = null, CAT = null, mode = "none", fallback = null, root = "hist/";
  var MIN_COV = 0.7;

  // ------------------------------------------------------------ idő (helyi, DST-helyes)
  var fOff = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
  function offsetMs(utcMs) {
    var p = {}; fOff.formatToParts(new Date(utcMs)).forEach(function (x) { p[x.type] = +x.value; });
    return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second) - Math.floor(utcMs / 1000) * 1000;
  }
  function midnight(ds) {            // a helyi nap kezdete, UTC epoch (másodperc)
    var a = ds.split("-").map(Number), g = Date.UTC(a[0], a[1] - 1, a[2]);
    var t = g - offsetMs(g); t = g - offsetMs(t);
    return Math.round(t / 1000);
  }
  function addDays(ds, n) { var a = ds.split("-").map(Number), d = new Date(Date.UTC(a[0], a[1] - 1, a[2] + n)); return d.toISOString().slice(0, 10); }
  function dayOf(epoch) { return new Date(epoch * 1000 + offsetMs(epoch * 1000)).toISOString().slice(0, 10); }
  var fLab = new Intl.DateTimeFormat("hu-HU", { timeZone: TZ, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  var fLong = new Intl.DateTimeFormat("hu-HU", { timeZone: TZ, year: "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  H.labelHour = function (e) { return fLab.format(new Date(e * 1000)).replace(/\s+/g, " "); };
  H.longHour = function (e) { return fLong.format(new Date(e * 1000)); };
  H.hourOfDay = function (e) { return +new Date(e * 1000 + offsetMs(e * 1000)).toISOString().slice(11, 13); };
  H.day = dayOf; H.midnight = midnight; H.addDays = addDays;
  function isoWeekKey(ds) {
    var a = ds.split("-").map(Number), d = new Date(Date.UTC(a[0], a[1] - 1, a[2])), dow = d.getUTCDay() || 7;
    d.setUTCDate(d.getUTCDate() + 4 - dow);
    var y = d.getUTCFullYear(), w = Math.ceil(((d - Date.UTC(y, 0, 1)) / 864e5 + 1) / 7);
    return y + "-W" + (w < 10 ? "0" : "") + w;
  }
  H.isoWeekKey = isoWeekKey;
  function keyOf(ds, res) { return res === "d" ? ds : res === "w" ? isoWeekKey(ds) : res === "m" ? ds.slice(0, 7) : ds.slice(0, 4); }
  function hoursInMonth(key) {
    var a = key.split("-").map(Number), s = key + "-01", e = (a[1] === 12 ? (a[0] + 1) + "-01" : a[0] + "-" + (a[1] < 9 ? "0" : "") + (a[1] + 1)) + "-01";
    return Math.round((midnight(e) - midnight(s)) / 3600);
  }

  // ------------------------------------------------------------ betöltés
  function get(url, fresh) {
    var k = url + (fresh ? "#f" : "");
    if (!cache[k]) cache[k] = fetch(url, { cache: fresh ? "no-cache" : "default" }).then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status + " " + url); return r.json(); });
    cache[k].catch(function () { delete cache[k]; });
    return cache[k];
  }
  function hashed(rel) { var h = M && M.files && M.files[rel]; return root + rel + (h ? "?v=" + h : ""); }

  // o: {root: "hist/", fallbackUrl: "history.json"}
  H.init = function (o) {
    o = o || {}; root = o.root || "hist/";
    return get(root + "manifest.json", true).then(function (m) {
      M = m; return get(root + "catalog.json", true);
    }).then(function (c) { CAT = c; mode = "hist"; return info(); }, function () {
      if (!o.fallbackUrl) { mode = "none"; return info(); }
      return get(o.fallbackUrl, true).then(function (h) { fallback = h; mode = "monthly"; CAT = fbCatalog(); M = fbManifest(); return info(); }, function () { mode = "none"; return info(); });
    });
  };
  function info() { return { mode: mode, manifest: M, catalog: CAT }; }
  H.mode = function () { return mode; };
  H.catalog = function () { return CAT; };
  H.manifest = function () { return M; };

  // ------------------------------------------------------------ elérhetőség
  H.cats = function (zone) { var z = M && M.zones[zone]; return z ? Object.keys(z.cats) : []; };
  H.zones = function () { return M ? Object.keys(M.zones) : []; };
  H.avail = function (zone, cat) { var z = M && M.zones[zone]; return z && z.cats[cat] || null; };
  H.seriesOf = function (zone, cat) { var a = H.avail(zone, cat); return a ? a.series : []; };
  H.seriesLabel = function (cat, id) { var c = CAT && CAT.cats[cat]; return c && c.series[id] || id; };
  H.tiersOf = function (zone, cat) { var a = H.avail(zone, cat); return a ? (mode === "monthly" ? ["m", "y"] : (a.tiers || ["d", "w", "m", "y"])).slice() : []; };
  H.hasHourly = function (zone, cat) { var a = H.avail(zone, cat); return mode === "hist" && !!a && cat !== "ramp" && a.years && a.years.length > 0; };
  H.hasQuarter = function (zone, cat) { var a = H.avail(zone, cat); return mode === "hist" && !!a && !!a.q_years && a.q_years.length > 0; };
  H.prelimFrom = function () { // az "előzetes" határ (UTC epoch, mp): a manifest keletkezése mínusz 90 nap
    var g = M && M.generated_utc ? Date.parse(M.generated_utc) : Date.now(), d = (M && M.prelim_days) || 90;
    return Math.floor((g - d * 864e5) / 1000);
  };

  // ------------------------------------------------------------ tier- és partíciófájlok
  H.tier = function (zone, cat, tier) {
    if (mode === "monthly") return Promise.resolve(fbTier(zone, cat, tier));
    return get(hashed(tier + "/" + zone + "/" + cat + ".json"));
  };
  H.partition = function (zone, cat, year, step) {
    return get(hashed((step === 900 ? "q/" : "h/") + zone + "/" + year + "/" + cat + ".json"));
  };

  // ------------------------------------------------------------ lekérdezés
  // o: {zone, cat, res: "q"|"h"|"d"|"w"|"m"|"y", from, to (helyi nap, zárt), series: [id]|null, stat: avg|min|max|energy|neg}
  // Eredmény: {res, keys (d/w/m/y: kulcs; h/q: epoch mp), series: {id: [érték|null]}, h: [órák], n: {id: [..]}, unit, cat, last}
  H.query = function (o) {
    var a = H.avail(o.zone, o.cat);
    if (!a) return Promise.reject(new Error("nincs ilyen sorozat: " + o.zone + "/" + o.cat));
    var ids = (o.series && o.series.length ? o.series : a.series).filter(function (s) { return a.series.indexOf(s) >= 0; });
    var meta = CAT.cats[o.cat], stat = o.stat || "avg";
    if (o.res === "h" || o.res === "q") return hourly(o, a, ids, meta, o.res === "q" ? 900 : 3600, stat);
    return H.tier(o.zone, o.cat, o.res).then(function (t) {
      var k0 = keyOf(o.from, o.res), k1 = keyOf(o.to, o.res), i0 = lowerBound(t.keys, k0), i1 = lowerBound(t.keys, k1, true);
      var keys = t.keys.slice(i0, i1), out = { res: o.res, keys: keys, series: {}, n: {}, h: t.h.slice(i0, i1), unit: meta.unit, cat: o.cat, last: t.last, per: t.per || "h", stat: stat, agg: meta.agg };
      ids.forEach(function (id) {
        var s = t.series[id]; if (!s) return;
        var avg = s.avg.slice(i0, i1), v;
        if (stat === "avg") v = avg;
        else if (stat === "min") v = s.min.slice(i0, i1);
        else if (stat === "max") v = s.max.slice(i0, i1);
        else if (stat === "neg") v = (s.neg || []).slice(i0, i1);
        else if (stat === "energy") v = avg.map(function (x, i) { return x == null ? null : Math.round(x * out.h[i]) / 1000; });     // MW × h = MWh -> GWh
        out.series[id] = v; out.n[id] = s.n.slice(i0, i1);
      });
      out.unit = stat === "energy" ? "GWh" : stat === "neg" ? "óra" : meta.unit;
      return out;
    });
  };
  function lowerBound(arr, key, past) {   // az első index, ahol arr[i] >= key (past: az első, ahol arr[i] > key)
    var lo = 0, hi = arr.length;
    while (lo < hi) { var mid = (lo + hi) >> 1; if (past ? arr[mid] <= key : arr[mid] < key) lo = mid + 1; else hi = mid; }
    return lo;
  }
  function hourly(o, a, ids, meta, step, stat) {
    var e0 = midnight(o.from), e1 = midnight(addDays(o.to, 1)), y0 = +dayOf(e0).slice(0, 4), y1 = +dayOf(e1 - 1).slice(0, 4), years = [];
    for (var y = y0; y <= y1; y++) if (step === 900 ? (a.q_years || []).indexOf(y) >= 0 : (a.years || []).indexOf(y) >= 0) years.push(y);
    return Promise.all(years.map(function (y) { return H.partition(o.zone, o.cat, y, step); })).then(function (parts) {
      var keys = [], series = {}, nat = null;
      ids.forEach(function (id) { series[id] = []; });
      parts.forEach(function (p) {
        if (p.native15_from != null) nat = nat == null ? p.native15_from : Math.min(nat, p.native15_from);
        // Csak az első és az utolsó mért óra közötti rész kerül vissza: a még be nem következett órák nem "hiányzó" adatok.
        var lo = Math.max(e0, a.first != null ? a.first : e0), hi = Math.min(e1, a.last != null ? a.last + 3600 : e1);
        var i0 = Math.max(0, Math.ceil((lo - p.t0) / p.step)), i1 = Math.min(p.n, Math.ceil((hi - p.t0) / p.step));
        for (var i = i0; i < i1; i++) {
          keys.push(p.t0 + i * p.step);
          ids.forEach(function (id) {
            var v = p.series[id] ? p.series[id][i] : null;
            if (v != null && stat === "energy") v = Math.round(v * p.step / 3600) / 1000;
            else if (v != null && stat === "neg") v = v < 0 ? 1 : 0;
            series[id].push(v);
          });
        }
      });
      return { res: o.res, keys: keys, series: series, n: null, h: null, unit: stat === "energy" ? "GWh" : stat === "neg" ? "óra" : meta.unit, cat: o.cat, last: a.last, per: "h", stat: stat, agg: meta.agg, step: step, native15_from: nat };
    });
  }

  // ------------------------------------------------------------ címkék és igazítás
  H.label = function (res, key) {
    if (res === "h" || res === "q") return H.labelHour(key);
    if (res === "d") return key.slice(5).replace("-", ".") + ".";
    if (res === "w") return key.slice(2);
    if (res === "m") return key.slice(0, 4) + "." + key.slice(5);
    return key;
  };
  H.longLabel = function (res, key) {
    if (res === "h" || res === "q") return H.longHour(key);
    if (res === "d") return key;
    if (res === "w") return key + " (ISO-hét)";
    if (res === "m") return key.replace("-", ". ") + ".";
    return key + ". év";
  };
  // Az időszak eltolása n évvel ugyanazokra a naptári napokra (a február 29. nem létező napon a hó utolsó napjára esik).
  H.shiftYear = function (ds, n) {
    var a = ds.split("-").map(Number), y = a[0] + n, m = a[1], d = a[2], last = new Date(Date.UTC(y, m, 0)).getUTCDate();
    d = Math.min(d, last); return y + "-" + (m < 10 ? "0" : "") + m + "-" + (d < 10 ? "0" : "") + d;
  };
  // Igazítási kulcs: azonos naptári nap / hét / hónap / napszak más évben ugyanarra a kulcsra esik.
  H.alignKey = function (res, key, seen) {
    if (res === "d") return key.slice(5);
    if (res === "w") return key.slice(5);
    if (res === "m") return key.slice(5);
    if (res === "y") return "év";
    var ds = dayOf(key), k = ds.slice(5) + " " + ("0" + H.hourOfDay(key)).slice(-2);
    if (seen) { if (seen[k]) k += "b"; seen[k.replace(/b$/, "")] = true; seen[k] = true; }
    return k;
  };
  // Két lekérdezés ugyanarra az x-tengelyre: a második sorozatai az első (alap) kulcsaihoz igazodnak az igazítási kulcs szerint
  // (azonos naptári nap / hét / hónap / napszak); ahol nincs megfelelő, ott null.
  H.alignTo = function (base, other) {
    var sb = {}, so = {}, idx = {}, res = {};
    var bk = base.keys.map(function (k) { return H.alignKey(base.res, k, sb); });
    other.keys.forEach(function (k, i) { idx[H.alignKey(other.res, k, so)] = i; });
    Object.keys(other.series).forEach(function (id) { res[id] = bk.map(function (ak) { var i = idx[ak]; return i == null ? null : other.series[id][i]; }); });
    return res;
  };

  // ------------------------------------------------------------ havi tartalék (history.json)
  function fbCatalog() {
    var gen = { nuclear: "Atomerőmű", gas: "Földgáz", coal: "Szén", solar: "Napenergia", wind: "Szél", bio: "Biomassza és hulladék", hydro: "Víz", other: "Egyéb" };
    var zones = {}; Object.keys(fallback.names || {}).forEach(function (z) { zones[z] = { name: fallback.names[z], country: z.slice(0, 2) }; });
    zones.DE_LU && (zones.DE_LU.country = "DE"); zones.DE_LU && (zones.DE_LU.note = "közös ajánlati zóna, nem azonos Németországgal");
    var bl = { AT: "Ausztria", SK: "Szlovákia", UA: "Ukrajna", RO: "Románia", RS: "Szerbia", HR: "Horvátország", SI: "Szlovénia" };
    return {
      schema: 1, zones: zones, tiers: { m: "havi", y: "éves" }, local_tz: TZ, prelim_days: 90, min_cov: MIN_COV, co2: fallback.co2 || {},
      cats: {
        generation: { label: "Termelés típusonként", unit: "MW", agg: "mean", source: "ENTSO-E 16.1.B&C (havi összesítésből)", quality: "published", series: gen, zones: ["HU"] },
        load: { label: "Fogyasztás (tény)", unit: "MW", agg: "mean", source: "ENTSO-E 6.1.A (havi összesítésből)", quality: "published", series: { load: "Fogyasztás" }, zones: ["HU"] },
        price_da: { label: "Day-ahead ár", unit: "€/MWh", agg: "time_mean", source: "ENTSO-E 12.1.D (havi összesítésből)", quality: "published", series: { price: "Day-ahead ár" }, zones: Object.keys(zones) },
        flow_physical: { label: "Fizikai határkeresztező áramlás (nettó, + = import Magyarországra)", unit: "MW", agg: "mean", source: "ENTSO-E 12.1.G (havi összesítésből)", quality: "published", series: bl, zones: ["HU"] },
        net_import: { label: "Nettó import (a fizikai áramlásokból)", unit: "MW", agg: "mean", source: "saját számítás az ENTSO-E 12.1.G adataiból", quality: "calculated", series: { net: "Nettó import" }, zones: ["HU"] },
        co2: { label: "Termelés-alapú CO₂-intenzitás", unit: "g/kWh", agg: "gen_weighted", source: "saját számítás: ENTSO-E 16.1.B&C × IPCC AR5 életciklus-tényezők", quality: "estimated", series: { intensity: "CO₂-intenzitás" }, zones: ["HU"] }
      }
    };
  }
  function fbMonths() { return Object.keys(fallback.months).sort(); }
  function fbManifest() {
    var ms = fbMonths(), years = []; ms.forEach(function (k) { var y = +k.slice(0, 4); if (years.indexOf(y) < 0) years.push(y); });
    var zones = {}, first = midnight(ms[0] + "-01"), last = midnight(ms[ms.length - 1] + "-01");
    Object.keys(CAT.zones).forEach(function (z) {
      var cats = {};
      Object.keys(CAT.cats).forEach(function (c) {
        if (CAT.cats[c].zones.indexOf(z) < 0) return;
        var ser = Object.keys(CAT.cats[c].series);
        if (c === "flow_physical") ser = ser.filter(function (b) { return ms.some(function (k) { var v = (fallback.months[k].border || {})[b]; return v != null; }); });
        if (c === "price_da" && z !== "HU" && !ms.some(function (k) { return ((fallback.months[k].z || {})[z] || {}).avg != null; })) return;
        cats[c] = { years: years, series: ser, cov: {}, first: first, last: last, tiers: ["m", "y"] };
      });
      zones[z] = { name: CAT.zones[z].name, country: CAT.zones[z].country, note: CAT.zones[z].note || null, cats: cats };
    });
    return { schema: 1, generated_utc: fallback.generated_utc, prelim_days: 90, min_cov: MIN_COV, zones: zones, files: {}, monthly: true };
  }
  function fbTier(zone, cat, tier) {
    var ms = fbMonths(), keys = ms.slice(), hrs = keys.map(hoursInMonth), series = {}, F = (CAT.co2 && CAT.co2.factors) || {};
    function put(id, fn, extra) {
      var avg = [], min = [], max = [], n = [], neg = [];
      keys.forEach(function (k, i) {
        var r = fallback.months[k], v = fn(r, hrs[i]);
        var ok = v && v.avg != null && !r.partial;
        avg.push(ok ? Math.round(v.avg * 10) / 10 : null); min.push(ok && v.min != null ? v.min : null); max.push(ok && v.max != null ? v.max : null);
        n.push(ok ? hrs[i] : 0); neg.push(ok && v.neg != null ? v.neg : null);
      });
      series[id] = { avg: avg, min: min, max: max, n: n }; if (extra) series[id].neg = neg;
    }
    var mw = function (gwh, h) { return gwh == null ? null : gwh * 1000 / h; };
    if (cat === "generation") Object.keys(CAT.cats.generation.series).forEach(function (g) { put(g, function (r, h) { return r.gen && r.gen[g] != null ? { avg: mw(r.gen[g], h) } : null; }); });
    else if (cat === "load") put("load", function (r) { return r.load_avg != null ? { avg: r.load_avg, min: r.load_min, max: r.load_peak } : null; });
    else if (cat === "price_da") put("price", function (r) {
      if (zone === "HU") return r.price ? { avg: r.price.avg, min: r.price.min, max: r.price.max, neg: r.price.neg_h } : null;
      var z = (r.z || {})[zone]; return z && z.avg != null ? { avg: z.avg, neg: z.neg } : null;
    }, true);
    else if (cat === "flow_physical") Object.keys(CAT.cats.flow_physical.series).forEach(function (b) { put(b, function (r, h) { var v = (r.border || {})[b]; return v != null ? { avg: mw(v, h) } : null; }); });
    else if (cat === "net_import") put("net", function (r, h) { return r.imp_gwh != null ? { avg: mw(r.imp_gwh, h) } : null; });
    else if (cat === "co2") put("intensity", function (r) {
      if (!r.gen) return null; var num = 0, den = 0; Object.keys(r.gen).forEach(function (g) { if (r.gen[g] != null && F[g] != null) { num += r.gen[g] * F[g]; den += r.gen[g]; } });
      return den > 0 ? { avg: num / den } : null;
    });
    var t = { schema: 1, zone: zone, cat: cat, tier: "m", unit: CAT.cats[cat].unit, keys: keys, h: hrs, series: series, last: null, per: "h" };
    return tier === "y" ? fbYear(t) : t;
  }
  function fbYear(t) {      // az éves érték csak teljes (12 érvényes hónapos) évre, a hónapok órákkal súlyozott átlaga
    var byY = {};
    t.keys.forEach(function (k, i) { (byY[k.slice(0, 4)] = byY[k.slice(0, 4)] || []).push(i); });
    var keys = Object.keys(byY).sort(), out = { schema: 1, zone: t.zone, cat: t.cat, tier: "y", unit: t.unit, keys: keys, h: [], series: {}, per: "h", last: null };
    keys.forEach(function (y) { out.h.push(byY[y].reduce(function (s, i) { return s + t.h[i]; }, 0)); });
    Object.keys(t.series).forEach(function (id) {
      var s = t.series[id], o = { avg: [], min: [], max: [], n: [] };
      if (s.neg) o.neg = [];
      keys.forEach(function (y, yi) {
        var ix = byY[y], num = 0, den = 0, mn = null, mx = null, ng = 0, hasNeg = false;
        ix.forEach(function (i) { if (s.avg[i] != null) { num += s.avg[i] * t.h[i]; den += t.h[i]; if (s.min[i] != null) mn = mn == null ? s.min[i] : Math.min(mn, s.min[i]); if (s.max[i] != null) mx = mx == null ? s.max[i] : Math.max(mx, s.max[i]); if (s.neg && s.neg[i] != null) { ng += s.neg[i]; hasNeg = true; } } });
        var ok = den / out.h[yi] >= MIN_COV && ix.length >= 12;
        o.avg.push(ok ? Math.round(num / den * 10) / 10 : null); o.min.push(ok ? mn : null); o.max.push(ok ? mx : null); o.n.push(den);
        if (s.neg) o.neg.push(ok && hasNeg ? ng : null);
      });
      out.series[id] = o;
    });
    return out;
  }
})();
