/* GridFlow Analytics – közös diagramkönyvtár (vonal, terület, oszlop, halmozott, hőtérkép) és CSV-segéd.
   Klasszikus szkript; a gf.js-re (GF.a11y, GF.nf, GF.esc) épít. Nincs külső függőség és nincs külső kérés.
   Elvek: egy tengely; vékony jelek; a sorozatok színe az entitáshoz kötött (--c1…--c8, nem a rangsorhoz);
   a jelmagyarázat minden ≥2 sorozatos ábrán ott van és kapcsolható; vezérlőpont/tooltip egérrel, érintéssel és billentyűvel;
   a hiányzó érték (null) szakadás, nem nulla; minden ábrához szöveges összefoglaló és táblázatnézet (GF.a11y). */
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg", GFChart = (window.GFChart = {});
  var nf = function (v, d) { return GF.nf(v, d); };

  function el(name, attrs, parent) {
    var e = document.createElementNS(NS, name);
    if (attrs) for (var k in attrs) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function color(i, s) { return (s && s.color) || "var(--c" + ((i % 8) + 1) + ")"; }

  // ---- tengelyek
  function niceStep(span, count) {
    var raw = span / Math.max(1, count), p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
  }
  function niceScale(lo, hi, count) {
    if (!isFinite(lo) || !isFinite(hi)) { lo = 0; hi = 1; }
    if (lo === hi) { var d = Math.abs(lo) * 0.1 || 1; lo -= d; hi += d; }
    var st = niceStep(hi - lo, count), a = Math.floor(lo / st) * st, b = Math.ceil(hi / st) * st, t = [];
    for (var v = a; v <= b + st * 0.001; v += st) t.push(Math.round(v / st) * st);
    return { lo: a, hi: b, ticks: t, step: st };
  }
  function decimalsFor(step) { return step >= 1 ? 0 : Math.min(3, Math.ceil(-Math.log10(step))); }

  // ---- közös keret: jelmagyarázat, SVG-tartó, tooltip, újrarajzolás méretváltozáskor
  function build(host, o, draw) {
    host.classList.add("chart"); host.style.position = "relative";
    var st = host._gfc || (host._gfc = { hidden: {} });
    st.o = o; st.draw = draw;
    if (o.resetHidden) st.hidden = {};
    function render() {
      var o2 = st.o, hidden = st.hidden;
      host.textContent = "";
      var vis = o2.series.map(function (s, i) { return { s: s, i: i }; }).filter(function (x) { return !hidden[x.s.id != null ? x.s.id : x.i]; });
      if (o2.series.length >= 2 && !o2.noLegend) {
        var lg = document.createElement("div"); lg.className = "chips"; lg.setAttribute("role", "group"); lg.setAttribute("aria-label", "Sorozatok");
        o2.series.forEach(function (s, i) {
          var key = s.id != null ? s.id : i, b = document.createElement("button"); b.type = "button"; b.className = "chip";
          b.setAttribute("aria-pressed", String(!hidden[key]));
          b.innerHTML = '<i style="background:' + color(i, s) + (s.dash ? ";opacity:.85" : "") + '"></i>' + GF.esc(s.label);
          b.addEventListener("click", function () {
            if (!hidden[key] && vis.length <= 1) return;       // legalább egy sorozat látszik
            hidden[key] = !hidden[key]; render();
            var nb = host.querySelectorAll(".chip")[i]; if (nb) nb.focus();
          });
          lg.appendChild(b);
        });
        host.appendChild(lg);
      }
      var wrap = document.createElement("div"); wrap.style.position = "relative"; host.appendChild(wrap);
      var tip = document.createElement("div"); tip.className = "tip"; tip.setAttribute("aria-hidden", "true"); wrap.appendChild(tip);
      var W = Math.max(280, wrap.clientWidth || host.clientWidth || 600);
      st.w = host.clientWidth;
      var ctx = { host: host, wrap: wrap, tip: tip, W: W, vis: vis, o: o2, st: st };
      var n = draw(ctx);
      if (n) wire(ctx, n);
      if (window.GF && GF.a11y && o2.labels) {
        GF.a11y(host, { xs: o2.labels, series: vis.map(function (x) { return { label: x.s.label, values: x.s.values }; }), unit: o2.unit, title: o2.title, fmt: o2.vfmt || function (v) { return nf(v, o2.dec); } });
      }
    }
    st.render = render;
    if (!st.ro && window.ResizeObserver) {
      st.ro = new ResizeObserver(function () { if (host.isConnected && Math.abs(host.clientWidth - (st.w || 0)) > 2 && host.clientWidth > 0) render(); });
      st.ro.observe(host);
    }
    render();
  }

  // ---- hover / érintés / billentyű: n = {svg, plot:{l,t,w,h}, count, at(i)->{x, rows:[{label,color,text}], head}, kind}
  function wire(ctx, n) {
    var svg = n.svg, tip = ctx.tip, wrap = ctx.wrap, cur = -1, cross = n.cross;
    function idxAt(px) {
      var f = (px - n.plot.l) / n.plot.w;
      var i = n.kind === "bars" ? Math.floor(f * n.count) : Math.round(f * (n.count - 1));
      return Math.max(0, Math.min(n.count - 1, i));
    }
    function show(i) {
      cur = i; var a = n.at(i);
      if (!a) { hide(); return; }
      var rows = a.rows.map(function (r) { return '<div class="row"><span><i style="background:' + r.color + '"></i>' + GF.esc(r.label) + '</span><b class="num">' + r.text + "</b></div>"; }).join("");
      tip.innerHTML = '<div class="t">' + GF.esc(a.head) + "</div>" + rows; tip.style.display = "block";
      var tw = tip.offsetWidth, th = tip.offsetHeight, left = a.x + 14, top = Math.max(0, n.plot.t + 4);
      if (left + tw > wrap.clientWidth) left = a.x - tw - 14;
      if (left < 0) left = 0;
      tip.style.left = left + "px"; tip.style.top = Math.min(top, Math.max(0, n.plot.t + n.plot.h - th)) + "px";
      if (cross) { cross.setAttribute("x1", a.x); cross.setAttribute("x2", a.x); cross.style.display = ""; }
      if (n.mark) n.mark(i, a);
    }
    function hide() { cur = -1; tip.style.display = "none"; if (cross) cross.style.display = "none"; if (n.mark) n.mark(-1); }
    var rect = el("rect", { x: n.plot.l, y: n.plot.t, width: n.plot.w, height: n.plot.h, fill: "transparent", "pointer-events": "all" }, svg);
    function local(e) { var b = svg.getBoundingClientRect(); return (e.clientX - b.left) * (svg.viewBox.baseVal.width / b.width); }
    rect.addEventListener("pointermove", function (e) { show(idxAt(local(e))); });
    rect.addEventListener("pointerdown", function (e) { show(idxAt(local(e))); });
    rect.addEventListener("pointerleave", function (e) { if (e.pointerType !== "touch") hide(); });
    var host = ctx.host;
    host.tabIndex = 0;
    host.onkeydown = function (e) {
      var k = e.key, i = cur < 0 ? 0 : cur;
      if (k === "ArrowRight") i = Math.min(n.count - 1, i + (e.shiftKey ? 10 : 1));
      else if (k === "ArrowLeft") i = Math.max(0, i - (e.shiftKey ? 10 : 1));
      else if (k === "Home") i = 0; else if (k === "End") i = n.count - 1; else if (k === "Escape") { hide(); return; } else return;
      e.preventDefault(); show(i);
    };
    host.onblur = hide;
  }

  function axesY(svg, m, W, H, sc, unit, dec) {
    var g = el("g", null, svg), plotH = H - m.t - m.b;
    var d = dec != null ? dec : decimalsFor(sc.step);
    sc.ticks.forEach(function (v) {
      var y = m.t + plotH * (1 - (v - sc.lo) / (sc.hi - sc.lo));
      el("line", { x1: m.l, x2: W - m.r, y1: y, y2: y, style: "stroke:var(--grid);stroke-width:" + (v === 0 ? 1.5 : 1) }, g);
      var t = el("text", { x: m.l - 8, y: y + 4, "text-anchor": "end", style: "fill:var(--ink2);font-size:12px" }, g); t.textContent = nf(v, d);
    });
    if (unit) { var u = el("text", { x: 2, y: 12, style: "fill:var(--ink2);font-size:12px" }, g); u.textContent = unit; }
  }
  function axisX(svg, m, W, H, count, labelAt, o, bars) {
    var g = el("g", null, svg), plotW = W - m.l - m.r, maxLab = Math.max(2, Math.floor(plotW / (o.tickPx || 74)));
    var idx = [];
    if (o.ticks) idx = o.ticks.map(function (t) { return t; });
    else { var step = Math.max(1, Math.ceil(count / maxLab)); for (var i = 0; i < count; i += step) idx.push({ i: i, label: labelAt(i) }); }
    var last = -1e9;
    idx.forEach(function (t) {
      var x = bars ? m.l + plotW * (t.i + 0.5) / count : m.l + (count > 1 ? plotW * t.i / (count - 1) : plotW / 2);
      if (x - last < 38) return; last = x;
      el("line", { x1: x, x2: x, y1: H - m.b, y2: H - m.b + 4, style: "stroke:var(--muted)" }, g);
      var tx = el("text", { x: x, y: H - m.b + 18, "text-anchor": "middle", style: "fill:var(--ink2);font-size:12px" }, g); tx.textContent = t.label;
    });
    el("line", { x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b, style: "stroke:var(--muted)" }, g);
  }
  function extent(vis, stacked, zeroBase) {
    var lo = Infinity, hi = -Infinity, n = vis[0] ? vis[0].s.values.length : 0, i;
    if (stacked) {
      for (i = 0; i < n; i++) { var p = 0, q = 0, any = false; vis.forEach(function (x) { var v = x.s.values[i]; if (v != null && !isNaN(v)) { any = true; if (v >= 0) p += v; else q += v; } }); if (any) { hi = Math.max(hi, p); lo = Math.min(lo, q); } }
      lo = Math.min(lo, 0);
    } else {
      vis.forEach(function (x) { x.s.values.forEach(function (v) { if (v != null && !isNaN(v)) { if (v < lo) lo = v; if (v > hi) hi = v; } }); });
    }
    if (zeroBase) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    return [lo, hi];
  }
  function noData(ctx, msg) {
    var d = document.createElement("div"); d.className = "nodata"; d.style.padding = "24px 8px"; d.textContent = msg || "Nincs közölt adat a kiválasztott időszakra."; ctx.wrap.appendChild(d); return null;
  }
  function fmtv(o) { return o.vfmt || function (v) { return nf(v, o.dec); }; }

  // ---- vonaldiagram. o: {labels:[str], series:[{id,label,values,color,dash}], unit, dec, height, zero, ticks, longLabel(i), title, vfmt, bands}
  GFChart.line = function (host, o) {
    build(host, o, function (ctx) {
      var vis = ctx.vis, W = ctx.W, H = o.height || (W < 520 ? 240 : 300), m = { l: 56, r: 12, t: 22, b: 28 }, n = o.labels.length;
      var ex = extent(vis, false, o.zero);
      if (!vis.length || !isFinite(ex[0])) return noData(ctx);
      var sc = niceScale(o.yMin != null ? o.yMin : ex[0], o.yMax != null ? o.yMax : ex[1], 5);
      var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "presentation" }, ctx.wrap); svg.style.cssText = "display:block;width:100%;height:auto;overflow:visible";
      axesY(svg, m, W, H, sc, o.unit, o.dec);
      axisX(svg, m, W, H, n, function (i) { return o.labels[i]; }, o, false);
      var pw = W - m.l - m.r, ph = H - m.t - m.b;
      var X = function (i) { return m.l + (n > 1 ? pw * i / (n - 1) : pw / 2); }, Y = function (v) { return m.t + ph * (1 - (v - sc.lo) / (sc.hi - sc.lo)); };
      (o.bands || []).forEach(function (b) { el("rect", { x: m.l, width: pw, y: Y(b.hi), height: Math.max(0, Y(b.lo) - Y(b.hi)), style: "fill:var(--neutral);opacity:.55" }, svg); });
      vis.forEach(function (x) {
        var d = "", pen = false, single = [];
        x.s.values.forEach(function (v, i) {
          if (v == null || isNaN(v)) { pen = false; return; }
          d += (pen ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1); pen = true;
          var pv = x.s.values[i - 1], nx = x.s.values[i + 1];
          if ((pv == null || isNaN(pv)) && (nx == null || isNaN(nx))) single.push(i);
        });
        el("path", { d: d, fill: "none", style: "stroke:" + color(x.i, x.s) + ";stroke-width:2;stroke-linejoin:round;stroke-linecap:round" + (x.s.dash ? ";stroke-dasharray:" + x.s.dash : "") }, svg);
        single.forEach(function (i) { el("circle", { cx: X(i), cy: Y(x.s.values[i]), r: 3, style: "fill:" + color(x.i, x.s) }, svg); });
      });
      var cross = el("line", { y1: m.t, y2: H - m.b, style: "stroke:var(--ink2);stroke-width:1;stroke-dasharray:3 3;display:none" }, svg), dots = [];
      var vf = fmtv(o);
      return {
        svg: svg, plot: { l: m.l, t: m.t, w: pw, h: ph }, count: n, kind: "line", cross: cross,
        at: function (i) {
          dots.forEach(function (d) { d.remove(); }); dots = [];
          var rows = vis.map(function (x) {
            var v = x.s.values[i];
            if (v != null && !isNaN(v)) dots.push(el("circle", { cx: X(i), cy: Y(v), r: 4.5, style: "fill:" + color(x.i, x.s) + ";stroke:var(--surface);stroke-width:2;pointer-events:none" }, svg));
            return { label: x.s.label, color: color(x.i, x.s), text: v == null || isNaN(v) ? '<span class="nodata">nincs adat</span>' : GF.esc(vf(v)) + (o.unit ? " " + GF.esc(o.unit) : "") };
          });
          return { x: X(i), head: (o.longLabel ? o.longLabel(i) : o.labels[i]), rows: rows };
        },
        mark: function (i) { if (i < 0) { dots.forEach(function (d) { d.remove(); }); dots = []; } }
      };
    });
  };

  // ---- halmozott terület (pl. termelési mix). o mint a vonalnál; a sorozatok összege látszik; a null a sorozatnál 0-nak számít a halmozásban (a tooltip "nincs adat"-ot ír)
  GFChart.stack = function (host, o) {
    build(host, o, function (ctx) {
      var vis = ctx.vis, W = ctx.W, H = o.height || (W < 520 ? 250 : 320), m = { l: 56, r: 12, t: 22, b: 28 }, n = o.labels.length;
      var ex = extent(vis, true, true);
      if (!vis.length || !isFinite(ex[1])) return noData(ctx);
      var sc = niceScale(ex[0], ex[1], 5);
      var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "presentation" }, ctx.wrap); svg.style.cssText = "display:block;width:100%;height:auto;overflow:visible";
      axesY(svg, m, W, H, sc, o.unit, o.dec);
      axisX(svg, m, W, H, n, function (i) { return o.labels[i]; }, o, false);
      var pw = W - m.l - m.r, ph = H - m.t - m.b;
      var X = function (i) { return m.l + (n > 1 ? pw * i / (n - 1) : pw / 2); }, Y = function (v) { return m.t + ph * (1 - (v - sc.lo) / (sc.hi - sc.lo)); };
      var base = new Array(n).fill(0);
      vis.forEach(function (x) {
        var top = [], bot = [], i;
        for (i = 0; i < n; i++) { var v = x.s.values[i]; v = v == null || isNaN(v) ? 0 : Math.max(0, v); bot.push(base[i]); base[i] += v; top.push(base[i]); }
        var d = "M" + X(0) + " " + Y(top[0]);
        for (i = 1; i < n; i++) d += "L" + X(i).toFixed(1) + " " + Y(top[i]).toFixed(1);
        for (i = n - 1; i >= 0; i--) d += "L" + X(i).toFixed(1) + " " + Y(bot[i]).toFixed(1);
        el("path", { d: d + "Z", style: "fill:" + color(x.i, x.s) + ";stroke:var(--surface);stroke-width:1" }, svg);
      });
      var cross = el("line", { y1: m.t, y2: H - m.b, style: "stroke:var(--ink);stroke-width:1;stroke-dasharray:3 3;display:none" }, svg), vf = fmtv(o);
      return {
        svg: svg, plot: { l: m.l, t: m.t, w: pw, h: ph }, count: n, kind: "line", cross: cross,
        at: function (i) {
          var tot = 0, rows = vis.map(function (x) { var v = x.s.values[i]; if (v != null && !isNaN(v)) tot += v; return { label: x.s.label, color: color(x.i, x.s), text: v == null || isNaN(v) ? '<span class="nodata">nincs adat</span>' : GF.esc(vf(v)) + " " + GF.esc(o.unit || "") }; }).reverse();
          rows.push({ label: "Összesen", color: "transparent", text: GF.esc(vf(tot)) + " " + GF.esc(o.unit || "") });
          return { x: X(i), head: (o.longLabel ? o.longLabel(i) : o.labels[i]), rows: rows };
        }
      };
    });
  };

  // ---- oszlopdiagram (csoportos vagy halmozott). o: {labels, series, stacked, unit, max, ...}; negatív érték a nulla alá megy; max: a tengely felső korlátja, ha az adat nem lépi túl
  GFChart.bars = function (host, o) {
    build(host, o, function (ctx) {
      var vis = ctx.vis, W = ctx.W, H = o.height || (W < 520 ? 250 : 300), m = { l: 56, r: 12, t: 22, b: 28 }, n = o.labels.length;
      var ex = extent(vis, !!o.stacked, true);
      if (!vis.length || !isFinite(ex[0])) return noData(ctx);
      if (o.max != null && ex[1] <= o.max * (1 + 1e-6)) ex[1] = o.max;      // pl. 100 %-ra normált halmozás: a tengely ne lépje túl a 100-at
      var sc = niceScale(ex[0], ex[1], 5);
      var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "presentation" }, ctx.wrap); svg.style.cssText = "display:block;width:100%;height:auto;overflow:visible";
      axesY(svg, m, W, H, sc, o.unit, o.dec);
      axisX(svg, m, W, H, n, function (i) { return o.labels[i]; }, o, true);
      var pw = W - m.l - m.r, ph = H - m.t - m.b, slot = pw / n, gap = Math.min(2, slot * 0.12);
      var Y = function (v) { return m.t + ph * (1 - (v - sc.lo) / (sc.hi - sc.lo)); }, gw = Math.max(1, slot - 2 * gap), k = vis.length;
      var bw = o.stacked ? gw : Math.max(1, gw / k - (k > 1 ? 1 : 0));
      var pos = new Array(n).fill(0), neg = new Array(n).fill(0), rects = [];
      vis.forEach(function (x, j) {
        for (var i = 0; i < n; i++) {
          var v = x.s.values[i]; if (v == null || isNaN(v)) continue;
          var x0 = m.l + i * slot + gap + (o.stacked ? 0 : j * (gw / k)), y0, y1;
          if (o.stacked) { if (v >= 0) { y0 = Y(pos[i]); pos[i] += v; y1 = Y(pos[i]); } else { y0 = Y(neg[i]); neg[i] += v; y1 = Y(neg[i]); } }
          else { y0 = Y(0); y1 = Y(v); }
          var top = Math.min(y0, y1), h = Math.max(0.5, Math.abs(y1 - y0) - (o.stacked ? 1 : 0));
          rects.push({ i: i, r: el("rect", { x: x0, y: top, width: bw, height: h, rx: Math.min(3, bw / 3), style: "fill:" + color(x.i, x.s) }, svg) });
        }
      });
      var hl = el("rect", { y: m.t, height: ph, style: "fill:var(--ink);opacity:.06;display:none;pointer-events:none" }, svg), vf = fmtv(o);
      return {
        svg: svg, plot: { l: m.l, t: m.t, w: pw, h: ph }, count: n, kind: "bars",
        at: function (i) {
          var rows = vis.map(function (x) { var v = x.s.values[i]; return { label: x.s.label, color: color(x.i, x.s), text: v == null || isNaN(v) ? '<span class="nodata">nincs adat</span>' : GF.esc(vf(v)) + " " + GF.esc(o.unit || "") }; });
          if (o.stacked && vis.length > 1) { var t = 0; vis.forEach(function (x) { var v = x.s.values[i]; if (v != null && !isNaN(v)) t += v; }); rows.push({ label: "Összesen", color: "transparent", text: GF.esc(vf(t)) + " " + GF.esc(o.unit || "") }); }
          return { x: m.l + (i + 0.5) * slot, head: (o.longLabel ? o.longLabel(i) : o.labels[i]), rows: rows };
        },
        mark: function (i) { if (i < 0) { hl.style.display = "none"; return; } hl.setAttribute("x", m.l + i * slot); hl.setAttribute("width", slot); hl.style.display = ""; }
      };
    });
  };

  // ---- hőtérkép. o: {rowLabels, colLabels, values[r][c], unit, dec, title, diverging, vfmt, rowTitle}
  function rgb(c) { var m = /rgba?\((\d+)[ ,]+(\d+)[ ,]+(\d+)/.exec(c); return m ? [+m[1], +m[2], +m[3]] : [128, 128, 128]; }
  function cssColor(v) { var t = document.createElement("span"); t.style.color = v; document.body.appendChild(t); var c = getComputedStyle(t).color; t.remove(); return rgb(c); }
  GFChart.heat = function (host, o) {
    host.classList.add("chart"); host.style.position = "relative";
    var st = host._gfc || (host._gfc = {});
    st.o = o;
    function render() {
      var R = o.rowLabels.length, C = o.colLabels.length, vals = o.values, lo = Infinity, hi = -Infinity;
      vals.forEach(function (r) { r.forEach(function (v) { if (v != null && !isNaN(v)) { if (v < lo) lo = v; if (v > hi) hi = v; } }); });
      host.textContent = "";
      if (!isFinite(lo)) { var d = document.createElement("div"); d.className = "nodata"; d.style.padding = "24px 8px"; d.textContent = "Nincs közölt adat a kiválasztott időszakra."; host.appendChild(d); return; }
      var W = Math.max(280, host.clientWidth || 600); st.w = host.clientWidth;
      var ml = 64, mt = 20, mb = 26, mr = 8, cw = (W - ml - mr) / C, ch = Math.max(14, Math.min(28, (o.height || 300) / R)), H = mt + R * ch + mb;
      var lowC = cssColor(getComputedStyle(host).getPropertyValue("--surface") || "#fff"), hiC = cssColor(o.diverging ? "var(--c2)" : "var(--c1)"), midC = cssColor("var(--neutral)"), loC = cssColor("var(--c1)");
      var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "presentation" }, host); svg.style.cssText = "display:block;width:100%;height:auto;overflow:visible";
      var vfn = fmtv(o), div = !!o.diverging, ext = div ? Math.max(Math.abs(lo), Math.abs(hi)) : 0;
      function fill(v) {
        var a, b, t;
        if (div) { t = Math.max(-1, Math.min(1, v / (ext || 1))); a = midC; b = t >= 0 ? hiC : loC; t = Math.abs(t); }
        else { t = hi === lo ? 1 : (v - lo) / (hi - lo); a = lowC; b = hiC; t = 0.08 + 0.92 * t; }
        return "rgb(" + [0, 1, 2].map(function (k) { return Math.round(a[k] + (b[k] - a[k]) * t); }).join(",") + ")";
      }
      var step = Math.max(1, Math.ceil(C / Math.max(2, Math.floor((W - ml - mr) / 56))));
      for (var r = 0; r < R; r++) {
        var rl = el("text", { x: ml - 6, y: mt + r * ch + ch / 2 + 4, "text-anchor": "end", style: "fill:var(--ink2);font-size:12px" }, svg); rl.textContent = o.rowLabels[r];
        for (var c = 0; c < C; c++) {
          var v = vals[r][c];
          var cell = el("rect", { x: ml + c * cw, y: mt + r * ch, width: Math.max(1, cw - 1), height: ch - 1, rx: 2, style: "fill:" + (v == null || isNaN(v) ? "var(--neutral)" : fill(v)) + (v == null || isNaN(v) ? ";opacity:.5" : "") }, svg);
          cell.setAttribute("data-r", r); cell.setAttribute("data-c", c);
        }
      }
      for (var c2 = 0; c2 < C; c2 += step) { var cl = el("text", { x: ml + c2 * cw + cw / 2, y: H - 8, "text-anchor": "middle", style: "fill:var(--ink2);font-size:12px" }, svg); cl.textContent = o.colLabels[c2]; }
      var tip = document.createElement("div"); tip.className = "tip"; tip.setAttribute("aria-hidden", "true"); host.appendChild(tip);
      svg.addEventListener("pointermove", function (e) {
        var t = e.target; if (!t.getAttribute || t.getAttribute("data-r") == null) { tip.style.display = "none"; return; }
        var rr = +t.getAttribute("data-r"), cc = +t.getAttribute("data-c"), v = vals[rr][cc];
        tip.innerHTML = '<div class="t">' + GF.esc(o.rowLabels[rr] + " · " + (o.colLongLabels ? o.colLongLabels[cc] : o.colLabels[cc])) + '</div><div class="row"><span>' + GF.esc(o.title || "Érték") + '</span><b class="num">' + (v == null || isNaN(v) ? '<span class="nodata">nincs adat</span>' : GF.esc(vfn(v)) + " " + GF.esc(o.unit || "")) + "</b></div>";
        tip.style.display = "block";
        var b = host.getBoundingClientRect(), x = e.clientX - b.left + 14, y = e.clientY - b.top + 10;
        if (x + tip.offsetWidth > b.width) x = e.clientX - b.left - tip.offsetWidth - 14;
        tip.style.left = Math.max(0, x) + "px"; tip.style.top = y + "px";
      });
      svg.addEventListener("pointerleave", function () { tip.style.display = "none"; });
      var lg = document.createElement("div"); lg.className = "legend"; lg.style.marginTop = "6px";
      lg.innerHTML = '<span>' + GF.esc(nf(lo, o.dec)) + '</span><span aria-hidden="true" style="width:120px;height:10px;border-radius:5px;display:inline-block;background:linear-gradient(90deg,' + fill(div ? -ext : lo) + "," + (div ? fill(0) + "," : "") + fill(div ? ext : hi) + ')"></span><span>' + GF.esc(nf(hi, o.dec)) + " " + GF.esc(o.unit || "") + "</span>";
      host.appendChild(lg);
      if (window.GF && GF.a11y) {
        GF.a11y(host, { xs: o.rowLabels, series: o.colLabels.map(function (cl2, ci) { return { label: cl2, values: vals.map(function (row) { return row[ci]; }) }; }), unit: o.unit, title: o.title, fmt: vfn });
      }
    }
    if (!st.ro && window.ResizeObserver) { st.ro = new ResizeObserver(function () { if (host.isConnected && Math.abs(host.clientWidth - (st.w || 0)) > 2 && host.clientWidth > 0) render(); }); st.ro.observe(host); }
    if (!st.th) { st.th = function () { if (host.isConnected) render(); }; document.addEventListener("gf-theme", st.th); }
    render();
  };

  // ---- szórásdiagram (pl. ár és termelés összefüggése). o: {points:[{x,y}], xLabel, yLabel, xUnit, yUnit, title}
  GFChart.scatter = function (host, o) {
    host.classList.add("chart"); host.style.position = "relative";
    var st = host._gfc || (host._gfc = {});
    function render() {
      host.textContent = "";
      var pts = o.points.filter(function (p) { return p.x != null && p.y != null && !isNaN(p.x) && !isNaN(p.y); });
      if (pts.length < 3) { var d = document.createElement("div"); d.className = "nodata"; d.style.padding = "24px 8px"; d.textContent = "Nincs elég közös adatpont a kiválasztott időszakra."; host.appendChild(d); return; }
      var W = Math.max(280, host.clientWidth || 600); st.w = host.clientWidth;
      var H = o.height || (W < 520 ? 260 : 320), m = { l: 56, r: 12, t: 22, b: 40 };
      var xs = pts.map(function (p) { return p.x; }), ys = pts.map(function (p) { return p.y; });
      var sx = niceScale(Math.min.apply(null, xs), Math.max.apply(null, xs), 6), sy = niceScale(Math.min.apply(null, ys), Math.max.apply(null, ys), 5);
      var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "presentation" }, host); svg.style.cssText = "display:block;width:100%;height:auto;overflow:visible";
      axesY(svg, m, W, H, sy, o.yUnit, null);
      var pw = W - m.l - m.r, ph = H - m.t - m.b;
      var X = function (v) { return m.l + pw * (v - sx.lo) / (sx.hi - sx.lo); }, Y = function (v) { return m.t + ph * (1 - (v - sy.lo) / (sy.hi - sy.lo)); };
      var gx = el("g", null, svg);
      sx.ticks.forEach(function (v) { var x = X(v); el("line", { x1: x, x2: x, y1: m.t, y2: H - m.b, style: "stroke:var(--grid)" }, gx); var t = el("text", { x: x, y: H - m.b + 16, "text-anchor": "middle", style: "fill:var(--ink2);font-size:12px" }, gx); t.textContent = nf(v, decimalsFor(sx.step)); });
      var xl = el("text", { x: m.l + pw / 2, y: H - 4, "text-anchor": "middle", style: "fill:var(--ink2);font-size:12px" }, svg); xl.textContent = (o.xLabel || "") + (o.xUnit ? " (" + o.xUnit + ")" : "");
      pts.forEach(function (p) { el("circle", { cx: X(p.x), cy: Y(p.y), r: 2.4, style: "fill:var(--c1);opacity:.45" }, svg); });
      var n = pts.length, mx = xs.reduce(function (a, b) { return a + b; }, 0) / n, my = ys.reduce(function (a, b) { return a + b; }, 0) / n, sxy = 0, sxx = 0, syy = 0;
      pts.forEach(function (p) { sxy += (p.x - mx) * (p.y - my); sxx += (p.x - mx) * (p.x - mx); syy += (p.y - my) * (p.y - my); });
      var r = sxx > 0 && syy > 0 ? sxy / Math.sqrt(sxx * syy) : null;
      if (sxx > 0) { var b1 = sxy / sxx, b0 = my - b1 * mx; el("line", { x1: X(sx.lo), y1: Y(b0 + b1 * sx.lo), x2: X(sx.hi), y2: Y(b0 + b1 * sx.hi), style: "stroke:var(--c2);stroke-width:2" }, svg); }
      var cap = document.createElement("p"); cap.className = "hint"; cap.style.margin = "6px 0 0";
      cap.textContent = n + " közös óra" + (r != null ? "; lineáris korreláció: r = " + nf(r, 2) + " (az összefüggés nem jelent okozatiságot)." : ".");
      host.appendChild(cap);
      if (window.GF && GF.a11y) {
        var sub = pts.length > 600 ? pts.filter(function (_, i) { return i % Math.ceil(pts.length / 600) === 0; }) : pts;
        GF.a11y(host, { xs: sub.map(function (p) { return nf(p.x, 1); }), series: [{ label: o.yLabel || "y", values: sub.map(function (p) { return p.y; }) }], unit: o.yUnit, title: (o.title || "Szórásdiagram") + " (" + (o.xLabel || "x") + " szerint)" });
      }
    }
    if (!st.ro && window.ResizeObserver) { st.ro = new ResizeObserver(function () { if (host.isConnected && Math.abs(host.clientWidth - (st.w || 0)) > 2 && host.clientWidth > 0) render(); }); st.ro.observe(host); }
    render();
  };

  // ---- CSV letöltés. UTF-8 BOM-mal (a táblázatkezelő jól olvassa az ékezeteket).
  // opt.decimal: "," (alap; magyar Excel: pontosvessző elválasztó + tizedesvessző) vagy "." (gépi feldolgozás: vessző elválasztó + tizedespont).
  // Egy érték csak akkor kerül tizedesvesszővel a fájlba, ha szám; a szöveges mezők (idő, forrás) változatlanok. A hiányzó érték üres mező, nem nulla.
  GFChart.csv = function (filename, header, rows, opt) {
    var dec = opt && opt.decimal === "." ? "." : ",", sep = dec === "," ? ";" : ",";
    var q = function (v) {
      if (v == null || (typeof v === "number" && !isFinite(v))) return "";
      var s = typeof v === "number" && dec === "," ? String(v).replace(".", ",") : String(v);
      return s.indexOf(sep) >= 0 || /["\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    var txt = "\ufeff" + [header].concat(rows).map(function (r) { return r.map(q).join(sep); }).join("\r\n");
    var blob = new Blob([txt], { type: "text/csv;charset=utf-8" }), a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = filename; document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  };
})();
