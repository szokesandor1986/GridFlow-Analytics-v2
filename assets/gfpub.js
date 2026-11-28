/* GridFlow Analytics – a publikációs oldalak ábráinak kirajzolása.
   Minden <figure class="fig"> tartalmaz egy application/json leírást (a publish.py írja az építéskor) és egy <noscript> táblázatot.
   Itt a közös diagramkönyvtárral (gfchart.js) rajzoljuk ki; ha a szkript nem fut, ugyanaz az adat a táblázatban látszik. */
(function () {
  "use strict";
  var QK = { "végleges": "final", "előzetes": "prelim", "hiányzik": "miss", "számított": "calc", "becsült": "est" };
  function draw(fig) {
    var host = fig.querySelector(".chart"), js = fig.querySelector('script[type="application/json"]');
    if (!host || !js || !window.GFChart) return;
    var spec; try { spec = JSON.parse(js.textContent); } catch (e) { host.textContent = "Az ábra adata nem olvasható."; return; }
    var o = { labels: spec.labels, series: spec.series, unit: spec.unit, dec: spec.dec, title: spec.title, height: 300, zero: !!spec.zero };
    if (spec.ticks && spec.ticks.length) o.ticks = spec.ticks;
    if (spec.kind === "line") GFChart.line(host, o);
    else if (spec.kind === "bars") { o.stacked = !!spec.stacked; GFChart.bars(host, o); }
    else if (spec.kind === "scatter") GFChart.scatter(host, { points: spec.points, xLabel: spec.xLabel, yLabel: spec.yLabel, xUnit: spec.xUnit, yUnit: spec.yUnit, title: spec.title, height: 320 });
    fig.classList.add("drawn");
  }
  function run() {
    if (window.GF && GF.loaded) GF.loaded();
    Array.prototype.forEach.call(document.querySelectorAll("figure.fig"), draw);
    Array.prototype.forEach.call(document.querySelectorAll(".q-slot[data-q]"), function (el) {
      if (window.GF && GF.q) el.innerHTML = "Minőség: " + GF.q(el.getAttribute("data-q"), document.body.getAttribute("data-root") || "");
    });
  }
  // ---- listázás (Kezdőlap, Elemzések): a publish.py által írt index.json betöltése és kártyák
  var MONTHS = ["január", "február", "március", "április", "május", "június", "július", "augusztus", "szeptember", "október", "november", "december"];
  var STATUS_TXT = { "teljes": "Teljes elemzés", "részleges": "Részleges: a hiányzó részt a Korlátok sorolja fel", "adatra vár": "Adatra vár" };
  var GFPub = (window.GFPub = {});
  GFPub.dir = function (demo) { return demo ? "demo-elemzesek/" : "elemzesek/"; };
  GFPub.monthLong = function (k) { return k ? k.slice(0, 4) + ". " + MONTHS[+k.slice(5, 7) - 1] : "–"; };
  GFPub.load = function (demo) {
    return fetch(GFPub.dir(demo) + "index.json", { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); });
  };
  GFPub.card = function (p, dir, opt) {
    opt = opt || {};
    var a = document.createElement("a"); a.className = "card pubcard" + (opt.big ? " big" : ""); a.href = dir + p.slug + ".html";
    var q = QK[p.quality] || "final";
    a.innerHTML = '<span class="tag-topic">' + GF.esc(p.topic) + "</span><h3>" + GF.esc(p.title) + "</h3><p>" + GF.esc(opt.big ? (p.question + " ") : "") + GF.esc(p.summary) + "</p>" +
      '<div class="meta2"><span>Adatok állása: ' + GF.esc(GFPub.monthLong(p.data_through)) + "</span>" + (p.status === "adatra vár" ? "" : GF.q(q, "", true)) +
      (p.status === "teljes" ? "" : '<span class="tag-topic" title="' + GF.esc(STATUS_TXT[p.status] || p.status) + '">' + GF.esc(p.status) + "</span>") + "</div>";
    return a;
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", run); else run();
})();
