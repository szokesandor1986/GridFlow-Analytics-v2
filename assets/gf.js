/* GridFlow Analytics – közös segédkód (téma, adatállapot, hozzáférhetőség, betöltés).
   Klasszikus szkript, a lap <head>-jében töltődik be; a GF globális objektumot ad.
   Nem tartalmaz titkot, és nem hív külső szolgáltatást. */
(function () {
  "use strict";
  var root = document.documentElement, KEY = "gf-theme", GF = (window.GF = {});

  // ---------------------------------------------------------------- téma
  function stored() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function keep(v) { try { if (v) localStorage.setItem(KEY, v); else localStorage.removeItem(KEY); } catch (e) { /* privát mód */ } }
  function applyTheme(m) { if (m === "light" || m === "dark") root.setAttribute("data-theme", m); else root.removeAttribute("data-theme"); }
  applyTheme(stored());                         // még rajzolás előtt, hogy ne villanjon
  var mq = window.matchMedia ? matchMedia("(prefers-color-scheme: dark)") : null;
  GF.theme = function () { var t = root.getAttribute("data-theme"); return t === "light" || t === "dark" ? t : "auto"; };
  GF.isDark = function () { var t = GF.theme(); return t === "auto" ? !!(mq && mq.matches) : t === "dark"; };
  function fire() { document.dispatchEvent(new Event("gf-theme")); }
  if (mq) (mq.addEventListener ? mq.addEventListener.bind(mq, "change") : mq.addListener.bind(mq))(function () { if (GF.theme() === "auto") fire(); });
  var THEME_TXT = { auto: "Téma: automatikus", light: "Téma: világos", dark: "Téma: sötét" };
  function themeButton() {
    var nav = document.querySelector("nav.tabs"); if (!nav || nav.querySelector(".themebtn")) return;
    var b = document.createElement("button"); b.type = "button"; b.className = "themebtn";
    function label() { var t = GF.theme(); b.textContent = THEME_TXT[t]; b.setAttribute("aria-label", "Megjelenés váltása (automatikus, világos, sötét). Jelenleg: " + THEME_TXT[t].replace("Téma: ", "")); }
    b.addEventListener("click", function () { var n = { auto: "light", light: "dark", dark: "auto" }[GF.theme()]; applyTheme(n === "auto" ? null : n); keep(n === "auto" ? null : n); label(); fire(); });
    label(); nav.appendChild(b);
  }

  // ---------------------------------------------------------------- szerkezet, ugrólink, betöltésjelző
  var loadingEl = null;
  GF.loaded = function () { if (loadingEl && loadingEl.parentNode) loadingEl.parentNode.removeChild(loadingEl); loadingEl = null; };
  function scaffold() {
    var main = document.querySelector("main"); if (!main) return;
    if (!main.id) main.id = "main"; main.setAttribute("tabindex", "-1");
    var a = document.createElement("a"); a.className = "skip"; a.href = "#" + main.id; a.textContent = "Ugrás a tartalomra";
    document.body.insertBefore(a, document.body.firstChild);
    themeButton();
    if (pending > 0 || !seen) {
      loadingEl = document.createElement("div"); loadingEl.className = "loading"; loadingEl.setAttribute("role", "status"); loadingEl.textContent = "Adatok betöltése…";
      var nav = main.querySelector("nav.tabs"); if (nav && nav.nextSibling) main.insertBefore(loadingEl, nav.nextSibling); else main.insertBefore(loadingEl, main.firstChild);
      setTimeout(function () { if (pending === 0) GF.loaded(); }, 6000);   // biztonsági lezárás, ha semmi sem kért adatot
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", scaffold); else scaffold();

  // ---------------------------------------------------------------- adatbetöltés
  // Az adatfájlok feltételes kéréssel (ETag / Last-Modified) frissülnek: ha nem változtak, 304 jön, nem a teljes fájl.
  // A ritkán változó statikus fájlok (térképgeometria) a böngésző gyorsítótárát használják.
  var pending = 0, seen = false;
  GF.getJson = function (url, opt) {
    pending++; seen = true;
    return fetch(url, { cache: opt && opt.static ? "default" : "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (j) { done(); return j; }, function (e) { done(); throw e; });
  };
  function done() { pending = Math.max(0, pending - 1); if (pending === 0) setTimeout(function () { if (pending === 0) GF.loaded(); }, 80); }

  // ---------------------------------------------------------------- számformátum, escape
  GF.esc = function (s) { return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); };
  var nfd = new Intl.NumberFormat("hu-HU", { maximumFractionDigits: 2 });
  function fmtNum(v) { return nfd.format(v).replace(/^-/, "−"); }
  var tz = "Europe/Budapest";
  var fStamp = new Intl.DateTimeFormat("hu-HU", { timeZone: tz, year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
  GF.stamp = function (d) { return fStamp.format(d instanceof Date ? d : new Date(d)); };

  // ---------------------------------------------------------------- adatállapot (valós / demo / elavult / hiányos)
  // o: {demo, generatedUtc, now, staleHours, missing:[szöveg], partial:[szöveg], what}
  GF.state = function (o) {
    var now = o.now ? +new Date(o.now) : Date.now(), gen = o.generatedUtc ? +new Date(o.generatedUtc) : null;
    var ageH = gen == null ? null : Math.max(0, (now - gen) / 36e5), stale = !o.demo && ageH != null && ageH > (o.staleHours || 3);
    var miss = (o.missing || []).filter(Boolean), part = (o.partial || []).filter(Boolean);
    var kind = o.demo ? "demo" : stale ? "stale" : (miss.length || part.length) ? "partial" : "live";
    return { kind: kind, ageH: ageH, stale: stale, missing: miss, partial: part };
  };
  function ageText(h) { if (h == null) return ""; var m = Math.round(h * 60); return m < 90 ? m + " perce" : fmtNum(Math.round(h * 10) / 10) + " órája"; }
  var KIND_TXT = { live: "Valós adat", demo: "Demo adat", stale: "Elavult adat", partial: "Részben hiányos adat" };
  var KIND_ICO = { live: "●", demo: "◆", stale: "▲", partial: "◐" };
  // Rövid címke az állapotsorba: szöveg + jel, nem csak szín.
  GF.stateTag = function (st) {
    var t = KIND_TXT[st.kind] + (st.kind === "live" || st.kind === "stale" ? ", frissítve " + ageText(st.ageH) : "");
    return '<span class="state ' + st.kind + '"><span aria-hidden="true">' + KIND_ICO[st.kind] + '</span> ' + GF.esc(t) + '</span>';
  };
  // Sávok az oldal tetejére. Csak ténylegesen betöltött adatból épül.
  GF.banners = function (el, o) {
    var st = GF.state(o), b = [], what = o.what || "az adatgyűjtés";
    if (st.kind === "demo") b.push('<div class="banner demo" role="status"><b>DEMO ADAT</b> – szintetikus, nem valós mérés. ' + GF.esc(o.demoText || "Csak az oldal kinézetének előnézete.") + '</div>');
    if (st.stale) b.push('<div class="banner warn" role="status"><b>Elavult adat.</b> ' + GF.esc(what.charAt(0).toUpperCase() + what.slice(1)) + ' utoljára ' + ageText(st.ageH) + ' frissült, az értékek nem a legfrissebb állapotot mutatják.</div>');
    if (st.missing.length) b.push('<div class="banner warn" role="status"><b>Hiányzó adat.</b> Még nincs: ' + st.missing.map(GF.esc).join(", ") + '. Az érintett részek üresen maradnak, nem nullát mutatnak.</div>');
    if (st.partial.length && o.showPartial) b.push('<div class="banner warn" role="status"><b>Részben hiányos adat.</b> ' + st.partial.map(GF.esc).join(" ") + '</div>');
    el.innerHTML = b.join(""); return st;
  };

  // ---------------------------------------------------------------- ábra: szöveges összefoglaló és táblázatnézet
  // o: {xs:[Date|string], series:[{label, values}], unit, title, fmt}
  // Az ábra role="img" és aria-label összefoglalót kap; alatta lenyitható táblázat tartalmazza ugyanazokat az adatokat.
  function cardTitle(host) {
    var c = host.closest ? host.closest(".card") : null, h2 = c && c.querySelector("h2"), sub = "";
    for (var p = host.previousElementSibling; p; p = p.previousElementSibling) if (/^H[34]$/.test(p.tagName)) { sub = p.textContent; break; }
    var base = h2 ? h2.textContent : "";
    return (base && sub && base !== sub ? base + " – " + sub : (sub || base)).trim();
  }
  function xText(x) { return x instanceof Date ? GF.stamp(x) : String(x == null ? "" : x); }
  GF.a11y = function (host, o) {
    var S = (o.series || []).filter(function (s) { return s.values && s.values.some(function (v) { return v != null && !Number.isNaN(v); }); });
    if (!host.hasAttribute("data-gf-title")) host.setAttribute("data-gf-title", host.getAttribute("aria-label") || "");
    var f = o.fmt || fmtNum, u = o.unit ? " " + o.unit : "", title = o.title || host.getAttribute("data-gf-title") || cardTitle(host) || "Ábra";
    var parts = S.slice(0, 6).map(function (s) {
      var lo = null, hi = null, last = null, li = -1, n = 0;
      s.values.forEach(function (v, i) { if (v == null || Number.isNaN(v)) return; n++; if (lo == null || v < lo) lo = v; if (hi == null || v > hi) hi = v; last = v; li = i; });
      return s.label + ": utolsó érték " + f(last) + u + " (" + xText(o.xs[li]) + "), legkisebb " + f(lo) + u + ", legnagyobb " + f(hi) + u;
    });
    host.setAttribute("role", "img");
    host.setAttribute("aria-label", title + ". " + (parts.length ? parts.join(". ") + "." : "Nincs közölt adat.") + (S.length > 6 ? " További sorozatok a táblázatnézetben." : "") + " Minden érték az „Adatok táblázatban” részben olvasható.");
    var tv = host._tv;
    if (!tv) {
      tv = document.createElement("details"); tv.className = "tview";
      var sm = document.createElement("summary"); sm.textContent = "Adatok táblázatban"; tv.appendChild(sm);
      var wrap = document.createElement("div"); wrap.className = "tscroll"; tv.appendChild(wrap);
      host.parentNode.insertBefore(tv, host.nextSibling); host._tv = tv;
      tv.addEventListener("toggle", function () { if (tv.open) tv._fill(); });
    }
    tv._fill = function () {
      var wrap = tv.querySelector(".tscroll"), n = o.xs.length, max = 1000, step = n > max ? Math.ceil(n / max) : 1;
      var h = "<table><caption class=\"sr\">" + GF.esc(title) + (o.unit ? " (" + GF.esc(o.unit) + ")" : "") + "</caption><thead><tr><th scope=\"col\">Időpont / sor</th>" + S.map(function (s) { return '<th scope="col" class="r">' + GF.esc(s.label) + "</th>"; }).join("") + "</tr></thead><tbody>";
      for (var i = 0; i < n; i += step) { h += '<tr><th scope="row">' + GF.esc(xText(o.xs[i])) + "</th>" + S.map(function (s) { var v = s.values[i]; return '<td class="r num">' + (v == null || Number.isNaN(v) ? '<span class="nodata">nincs adat</span>' : GF.esc(f(v))) + "</td>"; }).join("") + "</tr>"; }
      wrap.innerHTML = h + "</tbody></table>" + (step > 1 ? '<p class="hint">A táblázat minden ' + step + '. sort mutatja.</p>' : "");
    };
    if (tv.open) tv._fill();
    tv.firstChild.textContent = "Adatok táblázatban (" + S.length + " sorozat, " + o.xs.length + " pont)";
  };
})();
