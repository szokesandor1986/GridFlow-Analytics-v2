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
  var THEME_TXT = { auto: "Téma: auto", light: "Téma: világos", dark: "Téma: sötét" };
  function themeButton(host) {
    if (!host || host.querySelector(".themebtn")) return;
    var b = document.createElement("button"); b.type = "button"; b.className = "themebtn";
    function label() { var t = GF.theme(); b.textContent = THEME_TXT[t]; b.setAttribute("aria-label", "Megjelenés váltása (automatikus, világos, sötét). Jelenleg: " + ({ auto: "automatikus", light: "világos", dark: "sötét" })[t]); }
    b.addEventListener("click", function () { var n = { auto: "light", light: "dark", dark: "auto" }[GF.theme()]; applyTheme(n === "auto" ? null : n); keep(n === "auto" ? null : n); label(); fire(); });
    label(); host.appendChild(b);
  }

  // ---------------------------------------------------------------- oldalváz: fejléc, főmenü, almenü, lábléc
  // A <body data-section="..." data-page="..." data-root="../"> attribútumaiból épül; az útvonalak relatívak (alkönyvtárban is működnek).
  // Három főmenüpont; az Adatok alatt a modulok egy második sorban (nav.subnav) érhetők el, a Rendszerkép nézeteinek külön sora van (subnav2).
  var MENU = [
    { id: "kezdolap", href: "index.html", t: "Főoldal" },
    { id: "elemzesek", href: "elemzesek.html", t: "Elemzések" },
    { id: "adatok", href: "rendszerkep.html", t: "Adatok" }
  ];
  var DATA = [
    { href: "rendszerkep.html", t: "Aktuális rendszerkép", also: ["hatarok.html", "muszaki.html", "europa.html"] },
    { href: "historikus.html", t: "Historikus adatok" },
    { href: "eromuvek.html", t: "Erőművek és termelőegységek" },
    { href: "idojaras.html", t: "Időjárási adatok" },
    { href: "foldgaz.html", t: "Földgáz és tárolók" },
    { href: "nemzetkozi.html", t: "Nemzetközi összehasonlítás" },
    { href: "modszertan.html", t: "Módszertan és adatforrások" }
  ];
  var SUB = [
    { href: "rendszerkep.html", t: "Áttekintés" }, { href: "hatarok.html", t: "Határok és árak" }, { href: "muszaki.html", t: "Rendszerállapot" },
    { href: "europa.html", t: "Európai piac" }
  ];
  GF.SLOGAN = "Safety first. Power always.";
  GF.menu = MENU;
  function shell() {
    var body = document.body, main = document.querySelector("main"); if (!main || body.querySelector("header.site")) return;
    var root = body.getAttribute("data-root") || "", sec = body.getAttribute("data-section") || "", page = body.getAttribute("data-page") || "";
    var h = document.createElement("header"); h.className = "site";
    var items = MENU.map(function (m) {
      return '<li><a href="' + root + m.href + '"' + (m.id === sec ? ' aria-current="' + (page && page !== m.href ? "true" : "page") + '"' : "") + ">" + GF.esc(m.t) + "</a></li>";
    }).join("");
    h.innerHTML = '<div class="gfbar"><a class="brand" href="' + root + 'index.html" aria-label="GridFlow Analytics – kezdőlap">' +
      '<svg class="logo" viewBox="0 0 32 32" width="30" height="30" aria-hidden="true" focusable="false"><rect x="1" y="1" width="30" height="30" rx="7" fill="none" stroke="currentColor" stroke-width="2"/>' +
      '<path d="M5 20h6l3-9 4 13 3-8h6" fill="none" stroke="var(--turq)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>' +
      '<span class="bt"><span class="bn">GridFlow Analytics</span><span class="bs">' + GF.SLOGAN + "</span></span></a>" +
      '<button type="button" class="menu-toggle" aria-expanded="false" aria-controls="gf-menu">Menü</button>' +
      '<nav class="mainnav" id="gf-menu" aria-label="Főmenü"><ul>' + items + "</ul></nav><span class=\"gftools\"></span></div>";
    body.insertBefore(h, main);
    var tg = h.querySelector(".menu-toggle"), menu = h.querySelector("#gf-menu");
    tg.addEventListener("click", function () { var o = tg.getAttribute("aria-expanded") === "true"; tg.setAttribute("aria-expanded", String(!o)); menu.classList.toggle("open", !o); });
    menu.addEventListener("keydown", function (e) { if (e.key === "Escape") { tg.setAttribute("aria-expanded", "false"); menu.classList.remove("open"); tg.focus(); } });
    themeButton(h.querySelector(".gftools"));
    if (sec === "adatok") {
      var ds = document.createElement("nav"); ds.className = "tabs subnav"; ds.setAttribute("aria-label", "Adatok");
      ds.innerHTML = DATA.map(function (m) {
        var exact = m.href === page, inside = !exact && m.also && m.also.indexOf(page) >= 0;
        return '<a href="' + root + m.href + '"' + (exact ? ' aria-current="page"' : inside ? ' aria-current="true"' : "") + ">" + GF.esc(m.t) + "</a>";
      }).join("");
      main.insertBefore(ds, main.firstChild);
      var cur = ds.querySelector("[aria-current]"); if (cur && ds.scrollWidth > ds.clientWidth) ds.scrollLeft = Math.max(0, cur.offsetLeft - 16);
      if (SUB.some(function (m) { return m.href === page; })) {
        var sub = document.createElement("nav"); sub.className = "tabs subnav2"; sub.setAttribute("aria-label", "Az aktuális rendszerkép nézetei");
        sub.innerHTML = SUB.map(function (m) { return '<a href="' + root + m.href + '"' + (m.href === page ? ' aria-current="page"' : "") + ">" + GF.esc(m.t) + "</a>"; }).join("");
        main.insertBefore(sub, ds.nextSibling);
      }
    }
    if (!body.querySelector("footer.site")) {
      var f = document.createElement("footer"); f.className = "site";
      f.innerHTML = '<div class="gfin"><p><b>GridFlow Analytics</b> – független, nem hivatalos, nem kereskedelmi elemzések a magyar villamosenergia-rendszerről. <i>' + GF.SLOGAN + "</i></p>" +
        '<p><a href="' + root + 'rolunk.html">Rólunk</a> · <a href="' + root + 'modszertan.html">Módszertan és adatforrások</a></p>' +
        '<p>Adatforrások: ENTSO-E Transparency Platform, Energy-Charts (Fraunhofer ISE, CC BY 4.0), Open-Meteo (CC BY 4.0), GIE AGSI+ és ALSI, ENTSOG, HUPX, Global Power Plant Database (WRI, CC BY 4.0), JRC Hydropower database (CC BY 4.0). Az adatok tájékoztató jellegűek, nem valós idejűek; a minőségi címkék és a számítások leírása a <a href="' + root + 'modszertan.html">Módszertanban</a> található.</p></div>';
      body.appendChild(f);
    }
  }

  // ---------------------------------------------------------------- szerkezet, ugrólink, betöltésjelző
  var loadingEl = null;
  GF.loaded = function () { if (loadingEl && loadingEl.parentNode) loadingEl.parentNode.removeChild(loadingEl); loadingEl = null; };
  function scaffold() {
    var main = document.querySelector("main"); if (!main) return;
    if (!main.id) main.id = "main"; main.setAttribute("tabindex", "-1");
    if (!document.querySelector("a.skip")) { var a = document.createElement("a"); a.className = "skip"; a.href = "#" + main.id; a.textContent = "Ugrás a tartalomra"; document.body.insertBefore(a, document.body.firstChild); }
    shell();
    if (!document.body.hasAttribute("data-static") && (pending > 0 || !seen)) {      // data-static: az oldal nem tölt adatot (Módszertan, Rólunk), nincs betöltésjelző
      loadingEl = document.createElement("div"); loadingEl.className = "loading"; loadingEl.setAttribute("role", "status"); loadingEl.textContent = "Adatok betöltése…";
      var nav = main.querySelector("nav.subnav2") || main.querySelector("nav.subnav"); if (nav && nav.nextSibling) main.insertBefore(loadingEl, nav.nextSibling); else main.insertBefore(loadingEl, main.firstChild);
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
  GF.nf = function (v, d) { if (v == null || Number.isNaN(v)) return "–"; return new Intl.NumberFormat("hu-HU", { minimumFractionDigits: d || 0, maximumFractionDigits: d == null ? 2 : d }).format(v).replace(/^-/, "−"); };
  // Adatminőségi címke: jel + szöveg (nem csak szín). A magyarázat a Módszertan "minőség" pontján van.
  var Q = {
    final: ["●", "Végleges", "Az ENTSO-E közlése, 90 napnál régebbi: a GridFlow konvenciója szerint végleges."],
    prelim: ["◐", "Előzetes", "Az ENTSO-E közlése az utolsó 90 napból: később még módosulhat."],
    est: ["≈", "Becsült", "Becsült tényezőt vagy feltevést tartalmazó számítás."],
    calc: ["ƒ", "Számított", "A GridFlow számolta közölt adatokból; a képlet a Módszertanban van."],
    miss: ["○", "Hiányzó", "Nincs közölt adat; az érték üres, nem nulla."]
  };
  // Minőségi címke. plain=true: nem hivatkozás (másik hivatkozáson, pl. kártyán belül nem lehet beágyazott link).
  GF.q = function (kind, root, plain) {
    var q = Q[kind] || Q.miss, inner = '<span aria-hidden="true">' + q[0] + "</span> " + q[1];
    if (plain) return '<span class="q q-' + kind + '" title="' + GF.esc(q[2]) + '">' + inner + "</span>";
    return '<a class="q q-' + kind + '" href="' + (root || document.body.getAttribute("data-root") || "") + 'modszertan.html#minoseg" title="' + GF.esc(q[2]) + '">' + inner + "</a>";
  };
  GF.QUALITY = Q;
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
