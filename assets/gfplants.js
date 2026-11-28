/* GridFlow Analytics – erőművi térkép és egységadat-párosítás (GFPlants).
   Klasszikus szkript, nincs külső függőség és nincs külső kérés. A gf.js-re (GF.esc, GF.nf) épít.

   Két rész:
   1) tiszta logika (böngésző nélkül is tesztelhető, tests/test_gfplants.js): vetítés, ENTSO-E egységnevek párosítása a nyilvántartás
      erőműveihez, legutóbbi érték, 24 órás energia, kiesések, erőmű-állapot, lefedettség;
   2) GFPlants.map: interaktív SVG-térkép (nagyítás, húzás, szűrés, kijelölés, billentyűzet, érintés).

   Elvek: a „termel” állapot csak ellenőrzött ENTSO-E egységadatból jön, névegyeztetéssel (a párosítás a panelen látszik);
   beépített teljesítmény (nyílt adatbázis) külön jelölt; nem találunk ki üzemállapotot, értéket vagy koordinátát; a hiány nem nulla. */
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg", P = (window.GFPlants = {});

  // ------------------------------------------------------------------ vetítés
  // A hu-geo.json (Natural Earth) Mercator-jellegű kivágás; a paramétereket hat város ismert koordinátájára illesztettük
  // (a maradék eltérés legfeljebb ~2 képpont, kb. 2,5 km). Minden nyilvántartott erőmű a magyar határon belülre esik (teszt).
  var KX = 74.72773143, BX = -1090.236486749, KY = KX * 180 / Math.PI, BY = 4249.5980873;
  P.project = function (lat, lon) {
    var m = Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360));
    return [KX * lon + BX, BY - KY * m];
  };

  // ------------------------------------------------------------------ párosítás
  P.norm = function (s) { return String(s == null ? "" : s).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); };
  var COMPAT = {          // nyilvántartási tüzelőanyag -> elfogadható ENTSO-E csoportok (a tényleges típus a panelen látszik)
    nuclear: ["nuclear"], gas: ["gas", "other"], coal: ["coal", "bio", "gas"], solar: ["solar"], wind: ["wind"], hydro: ["hydro"],
    other: ["other", "gas", "bio", "coal"]
  };
  // Egy ENTSO-E névhez (egység vagy kiesés) a nyilvántartás erőműve: pontosan egy találat kell, különben nincs párosítás.
  P.matchName = function (plants, name, group) {
    var n = P.norm(name), hits = plants.filter(function (p) {
      if (!p.match || !p.match.length) return false;
      if (group && (COMPAT[p.fuel] || []).indexOf(group) < 0) return false;
      return p.match.some(function (s) { return n.indexOf(s) >= 0; });
    });
    return hits.length === 1 ? { plant: hits[0] } : hits.length ? { ambiguous: hits } : null;
  };
  // units: engineer.json "units". Kimenet: {byPlant:{id:[unit]}, unmatched:[unit], ambiguous:[{unit, plants:[név]}]}
  P.matchUnits = function (plants, units) {
    var out = { byPlant: {}, unmatched: [], ambiguous: [] };
    (units || []).forEach(function (u) {
      var m = P.matchName(plants, u.name, u.group);
      if (m && m.plant) (out.byPlant[m.plant.id] = out.byPlant[m.plant.id] || []).push(u);
      else if (m) out.ambiguous.push({ unit: u, plants: m.ambiguous.map(function (p) { return p.name; }) });
      else out.unmatched.push(u);
    });
    return out;
  };
  // Egység beépített teljesítménye az ENTSO-E egységlistából (A71): azonos normalizált név és csoport, pontosan egy találat.
  P.unitCapacity = function (unit, caps) {
    var n = P.norm(unit.name).replace(/[^a-z0-9]+/g, " ").trim();
    var hits = (caps || []).filter(function (c) { return c.group === unit.group && P.norm(c.name).replace(/[^a-z0-9]+/g, " ").trim() === n; });
    return hits.length === 1 ? hits[0].mw : null;
  };

  // ------------------------------------------------------------------ érték, energia
  // Legutóbbi közölt óra: {mw, i, t}. upTo: idő (ms) vagy null; a jövőbeli (előrejelzési) rács kimarad.
  P.latest = function (unit, ts, upTo) {
    var lim = upTo == null ? Infinity : upTo;
    for (var i = Math.min(unit.mw.length, ts.length) - 1; i >= 0; i--) {
      var v = unit.mw[i];
      if (v != null && !Number.isNaN(v) && +new Date(ts[i]) <= lim) return { mw: v, i: i, t: new Date(ts[i]) };
    }
    return null;
  };
  // Az utolsó 24 óra energiája (MWh) a végindexig; órás átlagteljesítmény × 1 h. Legalább 20 érvényes óra kell, különben null.
  P.energy24 = function (units, endIdx) {
    if (!units.length || endIdx == null || endIdx < 0) return { mwh: null, n: 0 };
    var sum = 0, n = 0;
    for (var i = Math.max(0, endIdx - 23); i <= endIdx; i++) {
      var ok = units.every(function (u) { return u.mw[i] != null && !Number.isNaN(u.mw[i]); });
      if (ok) { n++; units.forEach(function (u) { sum += u.mw[i]; }); }
    }
    return n >= 20 ? { mwh: sum, n: n } : { mwh: null, n: n };
  };

  // ------------------------------------------------------------------ erőmű-állapot
  // Állapotok: producing (termel), idle (0 MW az utolsó közölt órában), stale (van egységadat, de nincs friss érték), nodata (csak beépített teljesítmény ismert).
  // opt: {now (ms), staleH (alap 6)}
  P.plantStates = function (plants, E, opt) {
    opt = opt || {};
    var now = opt.now != null ? opt.now : Date.now(), staleMs = (opt.staleH || 6) * 36e5;
    var ts = (E && E.hourly_ts) || [], gen = E && E.generated_utc ? +new Date(E.generated_utc) : now;
    var upTo = Math.min(now, gen + 36e5);
    var M = P.matchUnits(plants, (E && E.units) || []), caps = (E && E.unit_capacity) || [];
    var outByPlant = {};
    ((E && E.outages_gen) || []).forEach(function (o) {
      var m = P.matchName(plants, o.name, o.group);
      if (m && m.plant) (outByPlant[m.plant.id] = outByPlant[m.plant.id] || []).push(o);
    });
    var res = {};
    plants.forEach(function (p) {
      var us = M.byPlant[p.id] || [], st = { id: p.id, state: "nodata", units: [], mw: null, t: null, frac: null, capKnown: null, mwh: null, mwhN: 0, outages: [], outageNow: false };
      var tm = null, tot = 0, any = false, capSum = 0, capAll = true;
      us.forEach(function (u) {
        var l = P.latest(u, ts, upTo), cap = P.unitCapacity(u, caps);
        st.units.push({ unit: u, latest: l, cap: cap, frac: l && cap ? l.mw / cap : null });
        if (l) { any = true; tot += l.mw; if (!tm || l.t > tm) tm = l.t; }
        if (cap == null) capAll = false; else capSum += cap;
      });
      if (us.length) {
        if (!any || (now - tm) > staleMs) st.state = "stale";      // az elavultságot a valódi időhöz mérjük: ha a gyűjtés leállt, az erőmű sem „termel” tovább
        else st.state = tot > 0 ? "producing" : "idle";
        if (any) { st.mw = tot; st.t = tm; }
        if (any && capAll && capSum > 0) { st.capKnown = capSum; st.frac = Math.max(0, tot / capSum); }
        var ei = any ? Math.max.apply(null, st.units.map(function (x) { return x.latest ? x.latest.i : -1; })) : -1;
        var e = P.energy24(us, ei); st.mwh = e.mwh; st.mwhN = e.n;
      }
      var outs = (outByPlant[p.id] || []).filter(function (o) { return +new Date(o.end) >= now - 36e5 * 24 * 7; });
      st.outages = outs;
      st.outageNow = outs.some(function (o) { return +new Date(o.start) <= now && +new Date(o.end) >= now; });
      res[p.id] = st;
    });
    return { states: res, unmatched: M.unmatched, ambiguous: M.ambiguous };
  };

  // Lefedettség: a nyilvántartás kapacitása tüzelőanyag-csoportonként az ENTSO-E országos beépített teljesítményéhez (A68) viszonyítva.
  // installed: engineer.json "installed_mw" ({nuclear, gas, coal, solar, wind, bio, hydro, other}).
  P.coverage = function (plants, installed, fuels) {
    var map = { nuclear: ["nuclear"], gas: ["gas"], coal: ["coal"], solar: ["solar"], wind: ["wind"], hydro: ["hydro"], other: ["other", "bio"] };
    return Object.keys(fuels).map(function (f) {
      var mapped = plants.filter(function (p) { return p.fuel === f; }).reduce(function (a, p) { return a + p.capacity_mw; }, 0);
      var nat = null;
      if (installed) { var any = false, s = 0; map[f].forEach(function (g) { if (installed[g] != null) { any = true; s += installed[g]; } }); nat = any ? s : null; }
      return { fuel: f, label: fuels[f], n: plants.filter(function (p) { return p.fuel === f; }).length, mapped: mapped, national: nat, share: nat ? mapped / nat : null };
    });
  };

  // ------------------------------------------------------------------ jelalakok (a szín mellett második kódolás: színvakság, nyomtatás)
  P.shape = function (fuel, r) {
    var pts = function (n, rot, rr) { var a = []; for (var i = 0; i < n; i++) { var t = rot + 2 * Math.PI * i / n; a.push((rr * Math.cos(t)).toFixed(2) + "," + (rr * Math.sin(t)).toFixed(2)); } return "M" + a.join("L") + "Z"; };
    switch (fuel) {
      case "nuclear": return pts(6, 0, r * 1.08);                 // hatszög
      case "coal": return pts(4, Math.PI / 4, r * 1.25);           // négyzet
      case "solar": return pts(4, 0, r * 1.2);                     // rombusz
      case "wind": return pts(3, -Math.PI / 2, r * 1.25);          // felfelé álló háromszög
      case "hydro": return pts(3, Math.PI / 2, r * 1.25);          // lefelé álló háromszög
      case "other": return pts(5, -Math.PI / 2, r * 1.12);         // ötszög
      default: return "M" + (-r) + ",0a" + r + "," + r + " 0 1,0 " + (2 * r) + ",0a" + r + "," + r + " 0 1,0 " + (-2 * r) + ",0Z";   // gáz: kör
    }
  };
  P.radius = function (mw) { return 3.4 + 0.42 * Math.sqrt(Math.max(0, mw)); };   // képpont: 1,8 MW ≈ 4 px, 100 MW ≈ 7,6 px, 1887 MW ≈ 21,7 px

  // ------------------------------------------------------------------ térkép
  function el(name, attrs, parent) {
    var e = document.createElementNS(NS, name);
    if (attrs) for (var k in attrs) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  var NAMES = { AT: "Ausztria", SK: "Szlovákia", UA: "Ukrajna", RO: "Románia", RS: "Szerbia", HR: "Horvátország", SI: "Szlovénia" };
  var CITY_LL = { Budapest: [47.4979, 19.0402], Debrecen: [47.5316, 21.6273], Szeged: [46.253, 20.1414], "Győr": [47.6875, 17.6504], "Pécs": [46.0727, 18.233], Miskolc: [48.1035, 20.7784] };

  // o: {geo, plants:[{id,name,fuel,capacity_mw,lat,lon}], states:{id:state}, fuels:{key:label}, onSelect(id|null), onHover}
  P.map = function (host, o) {
    var G = o.geo, plants = o.plants, states = o.states || {};
    host.innerHTML = "";
    host.classList.add("pmapwrap");
    var svg = el("svg", { class: "pmap", role: "group", "aria-label": "Magyarország erőművi térképe. Az erőművek a térkép alatti listában és táblázatban is megtalálhatók." });
    host.appendChild(svg);
    var tip = document.createElement("div"); tip.className = "tip"; host.appendChild(tip);

    // alapnézet: a magyar határ befoglalója
    var nums = G.zones.HU.match(/-?\d+\.?\d*/g).map(Number), xs = [], ys = [];
    nums.forEach(function (v, i) { (i % 2 ? ys : xs).push(v); });
    var bb = { x0: Math.min.apply(null, xs), x1: Math.max.apply(null, xs), y0: Math.min.apply(null, ys), y1: Math.max.apply(null, ys) };
    var pad = 22, homeW = bb.x1 - bb.x0 + 2 * pad, view = { cx: (bb.x0 + bb.x1) / 2, cy: (bb.y0 + bb.y1) / 2, w: homeW };
    var pxW = 800, pxH = 560;

    // rétegek
    var gBase = el("g", {}, svg), gLab = el("g", { "pointer-events": "none" }, svg), gPl = el("g", {}, svg);
    el("path", { d: G.ctx, class: "pm-ctx", "vector-effect": "non-scaling-stroke" }, gBase);
    Object.keys(G.zones).forEach(function (z) { el("path", { d: G.zones[z], class: z === "HU" ? "pm-hu" : "pm-zone", "vector-effect": "non-scaling-stroke" }, gBase); });
    var labels = [];
    Object.keys(NAMES).forEach(function (z) { if (G.labels[z]) labels.push({ t: el("text", { class: "pm-zname", "text-anchor": "middle" }, gLab), x: G.labels[z][0], y: G.labels[z][1], s: NAMES[z].toUpperCase(), fs: 11 }); });
    Object.keys(CITY_LL).forEach(function (c) {
      var p = G.cities && G.cities[c]; if (!p) return;
      var dot = el("circle", { class: "pm-city", r: 2 }, gLab);
      labels.push({ t: el("text", { class: "pm-cname" }, gLab), dot: dot, x: p[0], y: p[1], s: c, fs: 10.5, dx: 5, dy: 3.5 });
    });
    labels.forEach(function (l) { l.t.textContent = l.s; });

    // erőművek (nagyok alul, kicsik felül: a kicsi jel ne tűnjön el a nagy alatt)
    var order = plants.slice().sort(function (a, b) { return b.capacity_mw - a.capacity_mw; });
    var M = {}, vis = {}, sel = null;
    order.forEach(function (p) { vis[p.fuel] = true; });
    order.forEach(function (p) {
      var st = states[p.id] || { state: "nodata" }, r = P.radius(p.capacity_mw), xy = P.project(p.lat, p.lon), col = "var(--f-" + p.fuel + ")";
      var g = el("g", { class: "pm-pl s-" + st.state + (st.outageNow ? " outage" : ""), tabindex: 0, role: "button", "data-id": p.id }, gPl), pc = {};
      pc.hit = el("circle", { r: Math.max(r + 4, 13), fill: "transparent" }, g);
      pc.ring = el("path", { class: "pm-sel", d: P.shape(p.fuel, r + 6), fill: "none" }, g);
      pc.body = el("path", { class: "pm-body", d: P.shape(p.fuel, r), style: "--fc:" + col }, g);
      if (st.state === "producing") {
        var inner = st.frac != null ? Math.max(0.18, Math.min(1, Math.sqrt(st.frac))) * r * 0.86 : r * 0.38;      // a korong területe a terhelés arányában nő
        pc.in = el("circle", { class: "pm-in", r: inner.toFixed(2), style: "--fc:" + col }, g);
      } else if (st.state === "idle") {
        pc.in = el("path", { class: "pm-zero", d: "M" + (-r * 0.45) + ",0H" + (r * 0.45) }, g);
      }
      if (st.outageNow) { pc.out = el("path", { class: "pm-out", d: "M" + (r * 0.55) + "," + (-r * 1.45) + "l" + 5 + ",9h-10z" }, g); }
      pc.lab = el("text", { class: "pm-pname", "text-anchor": "start" }, g); pc.lab.textContent = p.name;
      var stText = { producing: "termel", idle: "0 MW az utolsó közölt órában", stale: "az egységadat nem friss", nodata: "csak beépített teljesítmény ismert" }[st.state];
      g.setAttribute("aria-label", p.name + ", " + (o.fuels[p.fuel] || p.fuel) + ", " + GF.nf(p.capacity_mw, 0) + " MW beépített teljesítmény (nyílt adatbázis), " + stText + (st.outageNow ? ", bejelentett kiesés" : ""));
      g.addEventListener("click", function () { if (!drag.moved) select(p.id, true); });
      g.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(p.id, true); } else if (e.key === "Escape") select(null); });
      g.addEventListener("pointerenter", function (e) { if (e.pointerType === "mouse") showTip(p, e); });
      g.addEventListener("pointermove", function (e) { if (e.pointerType === "mouse") showTip(p, e); });
      g.addEventListener("pointerleave", function () { tip.style.display = "none"; });
      g.addEventListener("focus", function () { showTip(p, null, g); });
      g.addEventListener("blur", function () { tip.style.display = "none"; });
      M[p.id] = { g: g, p: p, r: r, x: xy[0], y: xy[1], pc: pc };
    });

    function showTip(p, ev, g) {
      var st = states[p.id] || { state: "nodata" }, r = svg.getBoundingClientRect(), h = host.getBoundingClientRect();
      var line2 = st.state === "producing" ? "Termel: " + GF.nf(st.mw, 0) + " MW" : st.state === "idle" ? "0 MW az utolsó közölt órában" : st.state === "stale" ? "Az egységadat nem friss" : "Csak beépített teljesítmény ismert";
      tip.innerHTML = "<b>" + GF.esc(p.name) + "</b><br>" + GF.esc(o.fuels[p.fuel] || p.fuel) + " · " + GF.nf(p.capacity_mw, 0) + " MW<br>" + GF.esc(line2) + (st.outageNow ? "<br>Bejelentett kiesés" : "");
      tip.style.display = "block";
      var k = view.w / pxW, mx = ev ? ev.clientX - h.left : (M[p.id].x - (view.cx - view.w / 2)) / k + (r.left - h.left);
      var my = ev ? ev.clientY - h.top : (M[p.id].y - (view.cy - view.h / 2)) / k + (r.top - h.top);
      var tw = tip.offsetWidth, th = tip.offsetHeight, l = mx + 14, t = my - th - 10;
      if (l + tw > h.width) l = mx - tw - 14; if (l < 0) l = 4; if (t < 0) t = my + 16;
      tip.style.left = l + "px"; tip.style.top = t + "px";
    }

    // ---- nézet, méretezés
    function apply() {
      view.h = view.w * pxH / pxW;
      var k = view.w / pxW, x0 = view.cx - view.w / 2, y0 = view.cy - view.h / 2;
      svg.setAttribute("viewBox", x0.toFixed(2) + " " + y0.toFixed(2) + " " + view.w.toFixed(2) + " " + view.h.toFixed(2));
      labels.forEach(function (l) {
        l.t.setAttribute("x", (l.x + (l.dx || 0) * k).toFixed(2)); l.t.setAttribute("y", (l.y + (l.dy || 0) * k).toFixed(2)); l.t.setAttribute("font-size", (l.fs * k).toFixed(3));
        if (l.dot) { l.dot.setAttribute("cx", l.x); l.dot.setAttribute("cy", l.y); l.dot.setAttribute("r", (2.2 * k).toFixed(3)); }
      });
      var placed = [], mrect = {};
      var ordered = order.filter(function (p) { return vis[p.fuel]; });
      ordered.sort(function (a, b) { return (b.id === sel) - (a.id === sel) || b.capacity_mw - a.capacity_mw; });
      Object.keys(M).forEach(function (id) {
        var m = M[id], on = vis[m.p.fuel];
        m.g.setAttribute("transform", "translate(" + m.x.toFixed(2) + " " + m.y.toFixed(2) + ") scale(" + k.toFixed(4) + ")");
        m.g.style.display = on ? "" : "none"; m.pc.lab.style.display = "none";
      });
      ordered.forEach(function (p) {          // címkék: mohó elhelyezés, ütközésnél kimarad (a kijelölté mindig megvan)
        var m = M[p.id], sx = (m.x - (view.cx - view.w / 2)) / k, sy = (m.y - (view.cy - view.h / 2)) / k;
        if (sx < -20 || sy < -20 || sx > pxW + 20 || sy > pxH + 20) return;
        var w = p.name.length * 7.0 + 6, h = 15, r = m.r + 5;
        if (!mrect.done) { ordered.forEach(function (q) { var mm = M[q.id], qx = (mm.x - (view.cx - view.w / 2)) / k, qy = (mm.y - (view.cy - view.h / 2)) / k, rr = mm.r + 2; mrect[q.id] = { x: qx - rr, y: qy - rr, w: 2 * rr, h: 2 * rr }; }); mrect.done = true; }
        var cand = [[sx + r, sy - h / 2, r, 4], [sx - r - w, sy - h / 2, -r - w, 4], [sx - w / 2, sy - r - h, -w / 2, -r - 3], [sx - w / 2, sy + r, -w / 2, r + 12]];
        for (var i = 0; i < cand.length; i++) {
          var c = cand[i], rect = { x: c[0], y: c[1], w: w, h: h };
          var bad = rect.x < 2 || rect.x + w > pxW - 2 || rect.y < 2 || rect.y + h > pxH - 2 || placed.some(function (q) { return rect.x < q.x + q.w && rect.x + w > q.x && rect.y < q.y + q.h && rect.y + h > q.y; }) ||
            Object.keys(mrect).some(function (id) { var q = mrect[id]; return id !== "done" && id !== p.id && rect.x < q.x + q.w && rect.x + w > q.x && rect.y < q.y + q.h && rect.y + h > q.y; });
          if (!bad || (p.id === sel && i === cand.length - 1)) { placed.push(rect); m.pc.lab.setAttribute("x", c[2]); m.pc.lab.setAttribute("y", c[3]); m.pc.lab.style.display = ""; break; }
        }
      });
      var zoomed = view.w < homeW * 0.97;
      svg.style.touchAction = zoomed ? "none" : "pan-y";
      if (o.onView) o.onView({ zoomed: zoomed, scale: homeW / view.w });
    }
    function size() {
      pxW = Math.max(280, host.clientWidth); pxH = Math.round(Math.max(340, Math.min(700, pxW * (pxW < 560 ? 1.0 : 0.78))));
      svg.style.height = pxH + "px"; clamp(); apply();
    }
    function clamp() {
      view.w = Math.max(homeW / 9, Math.min(homeW * 1.25, view.w));
      var h = view.w * pxH / pxW, mx = 120;
      view.cx = Math.max(bb.x0 - mx, Math.min(bb.x1 + mx, view.cx)); view.cy = Math.max(bb.y0 - mx, Math.min(bb.y1 + mx, view.cy));
      view.h = h;
    }
    function zoomAt(f, px, py) {         // px, py: képpont a térképen belül (alap: közép)
      var k = view.w / pxW, ax = view.cx - view.w / 2 + (px == null ? pxW / 2 : px) * k, ay = view.cy - view.h / 2 + (py == null ? pxH / 2 : py) * k;
      var nw = Math.max(homeW / 9, Math.min(homeW * 1.25, view.w / f)), nk = nw / pxW;
      view.w = nw; view.cx = ax - ((px == null ? pxW / 2 : px) - pxW / 2) * nk; view.cy = ay - ((py == null ? pxH / 2 : py) - pxH / 2) * nk;
      clamp(); apply();
    }

    // ---- húzás, csíptetés, görgő
    var drag = { moved: false }, ptrs = {}, pinch = null;
    function local(e) { var r = svg.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }
    svg.addEventListener("pointerdown", function (e) {
      ptrs[e.pointerId] = local(e); drag.moved = false; drag.start = local(e); drag.cx = view.cx; drag.cy = view.cy;
      if (Object.keys(ptrs).length === 2) { var a = ptrs[Object.keys(ptrs)[0]], b = ptrs[Object.keys(ptrs)[1]]; pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]) || 1, w: view.w }; }
    });
    svg.addEventListener("pointermove", function (e) {
      if (!ptrs[e.pointerId]) return;
      ptrs[e.pointerId] = local(e); var ids = Object.keys(ptrs);
      if (ids.length === 2 && pinch) {
        var a = ptrs[ids[0]], b = ptrs[ids[1]], d = Math.hypot(a[0] - b[0], a[1] - b[1]) || 1; drag.moved = true;
        var cxp = (a[0] + b[0]) / 2, cyp = (a[1] + b[1]) / 2, f = (pinch.w / view.w) * (d / pinch.d); zoomAt(f, cxp, cyp); pinch.d = d; pinch.w = view.w; return;
      }
      if (ids.length !== 1) return;
      var p = local(e), dx = p[0] - drag.start[0], dy = p[1] - drag.start[1];
      if (!drag.moved && Math.hypot(dx, dy) < 5) return;
      if (!drag.moved) { try { svg.setPointerCapture(e.pointerId); } catch (x) { /* nem kritikus */ } svg.classList.add("grab"); }
      drag.moved = true; var k = view.w / pxW; view.cx = drag.cx - dx * k; view.cy = drag.cy - dy * k; clamp(); apply();
    });
    function up(e) { delete ptrs[e.pointerId]; if (Object.keys(ptrs).length < 2) pinch = null; svg.classList.remove("grab"); setTimeout(function () { drag.moved = false; }, 0); }
    svg.addEventListener("pointerup", up); svg.addEventListener("pointercancel", up);
    svg.addEventListener("wheel", function (e) {
      if (!(e.ctrlKey || e.metaKey)) return;         // a sima görgetés az oldalt görgeti; Ctrl + görgő nagyít
      e.preventDefault(); var p = local(e); zoomAt(e.deltaY < 0 ? 1.25 : 0.8, p[0], p[1]);
    }, { passive: false });
    svg.addEventListener("click", function (e) { if (e.target === svg || (e.target.classList && (e.target.classList.contains("pm-zone") || e.target.classList.contains("pm-hu") || e.target.classList.contains("pm-ctx")))) { if (!drag.moved) select(null); } });

    function select(id, user) {
      if (sel && M[sel]) M[sel].g.classList.remove("on");
      sel = id; if (id && M[id]) { M[id].g.classList.add("on"); M[id].g.parentNode.appendChild(M[id].g); }
      apply(); if (o.onSelect) o.onSelect(id, user);
    }
    var ro = window.ResizeObserver ? new ResizeObserver(function () { if (Math.abs(host.clientWidth - pxW) > 1) size(); }) : null;
    if (ro) ro.observe(host); else window.addEventListener("resize", size);
    size();

    return {
      select: select,
      selected: function () { return sel; },
      zoomIn: function () { zoomAt(1.5); }, zoomOut: function () { zoomAt(1 / 1.5); },
      reset: function () { view.cx = (bb.x0 + bb.x1) / 2; view.cy = (bb.y0 + bb.y1) / 2; view.w = homeW; clamp(); apply(); },
      focusOn: function (ids, minW) {       // a megadott erőművekre nagyít
        var pts = ids.map(function (id) { return M[id]; }).filter(Boolean); if (!pts.length) return;
        var x0 = Math.min.apply(null, pts.map(function (m) { return m.x; })), x1 = Math.max.apply(null, pts.map(function (m) { return m.x; })), y0 = Math.min.apply(null, pts.map(function (m) { return m.y; })), y1 = Math.max.apply(null, pts.map(function (m) { return m.y; }));
        view.cx = (x0 + x1) / 2; view.cy = (y0 + y1) / 2; view.w = Math.max(minW || 40, (x1 - x0) * 2.4, (y1 - y0) * 2.4 * pxW / pxH); clamp(); apply();
      },
      setVisible: function (fuelsOn) { Object.keys(vis).forEach(function (f) { vis[f] = !!fuelsOn[f]; }); if (sel && M[sel] && !vis[M[sel].p.fuel]) select(null); else apply(); },
      cities: CITY_LL
    };
  };
})();
