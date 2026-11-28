// Az erőművi modul tiszta logikájának (assets/gfplants.js) tesztje Node-ban, böngésző nélkül.
// Futtatás:  node tests/test_gfplants.js
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm"), assert = require("assert");
const ROOT = path.resolve(__dirname, "..");
const rd = (f) => JSON.parse(fs.readFileSync(path.join(ROOT, f), "utf8"));

function load() {
  const ctx = { console, Math, Date, JSON, Object, Array, Number, String, Error, Intl };
  ctx.window = ctx;
  ctx.GF = { esc: (s) => String(s), nf: (x) => String(x) };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(ROOT, "assets/gfplants.js"), "utf8"), ctx);
  return ctx.GFPlants;
}
let n = 0;
const ok = (c, m) => { assert.ok(c, m); n++; console.log("  ok   " + m); };
const near = (a, b, tol, m) => { assert.ok(Math.abs(a - b) <= tol, m + " (" + a + " vs " + b + ")"); n++; console.log("  ok   " + m); };

const P = load();
const reg = rd("plants.json"), plants = reg.plants;
const geo = rd("hu-geo.json");

// ---------------------------------------------------------------- vetítés
console.log("[vetítés]");
// Hat ismert város (WGS84): a vetületük a hu-geo.json képpontrendszerében a magyar határon belülre kell essen.
const cities = { Budapest: [47.4979, 19.0402], Debrecen: [47.5316, 21.6273], Szeged: [46.253, 20.1414], Pécs: [46.0727, 18.2323], Győr: [47.6875, 17.6504], Miskolc: [48.1035, 20.7784] };
// A hu-geo.json zones.HU mezője SVG útvonal (M/L/Z, képpontban); gyűrűkké bontjuk, és a városok/erőművek vetületét ezzel vetjük össze.
function rings(path) {
  const out = []; let cur = null;
  path.replace(/([MLZ])([^MLZ]*)/g, (_, c, rest) => {
    if (c === "M") { cur = []; out.push(cur); }
    if (c !== "Z") { const [x, y] = rest.split(",").map(Number); cur.push([x, y]); }
    return "";
  });
  return out.filter((r) => r.length > 2);
}
const R = rings(geo.zones.HU);
ok(R.length >= 1, "a hu-geo.json Magyarország-határa legalább egy gyűrű (" + R.length + ")");
function inRing(pt, ring) {
  let c = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
    if (((yi > pt[1]) !== (yj > pt[1])) && (pt[0] < (xj - xi) * (pt[1] - yi) / (yj - yi) + xi)) c = !c;
  }
  return c;
}
const toPx = (lat, lon) => P.project(lat, lon);
Object.keys(cities).forEach((c) => {
  const pt = toPx(cities[c][0], cities[c][1]);
  ok(R.some((r) => inRing(pt, r)), c + " a magyar határon belülre vetül");
});
// kalibráció: 1 fok hosszúság és a szélességi skála (Mercator) – az arány a szélességgel nő
const a = P.project(47, 19), b = P.project(47, 20), c1 = P.project(46, 19), c2 = P.project(48, 19);
near(b[0] - a[0], 74.73, 0.05, "1° hosszúság ≈ 74,73 képpont");
ok(c1[1] > a[1] && a[1] > c2[1], "északra csökken az y (SVG-irány)");
ok((c1[1] - a[1]) < (a[1] - c2[1]), "Mercator: a fok északon hosszabb képpontban");

// ---------------------------------------------------------------- nyilvántartás
console.log("[nyilvántartás]");
ok(plants.length === 22, "22 erőmű van a nyilvántartásban (" + plants.length + ")");
ok(new Set(plants.map((p) => p.id)).size === plants.length, "az azonosítók egyediek");
ok(plants.every((p) => reg.fuels[p.fuel]), "minden erőműnek ismert tüzelőanyag-csoportja van");
ok(plants.every((p) => p.capacity_mw > 0 && Number.isFinite(p.lat) && Number.isFinite(p.lon)), "minden erőműnek van teljesítménye és koordinátája");
ok(plants.every((p) => R.some((r) => inRing(toPx(p.lat, p.lon), r))), "minden erőmű a magyar határon belülre esik");
ok(plants.every((p) => (p.match || []).every((s) => s === P.norm(s) && /^[a-z0-9 ]+$/.test(s))), "a párosító tövek kisbetűs ASCII szövegek");
ok(!plants.some((p) => p.fuel === "wind"), "nincs szélerőmű a nyilvántartásban (nincs ellenőrzött forrás), kitalált sem");

// ---------------------------------------------------------------- névpárosítás
console.log("[névpárosítás]");
const byName = (s) => plants.find((p) => p.name.indexOf(s) === 0);
let m = P.matchName(plants, "PAKS 1", "nuclear");
ok(m && m.plant && m.plant.id === byName("Paksi Atom").id, "„PAKS 1” (atom) → Paksi Atomerőmű");
m = P.matchName(plants, "PAKS 1", "gas");
ok(m === null, "a „PAKS 1” gáz típussal nem párosul (összeférhetetlen tüzelőanyag)");
m = P.matchName(plants, "Ismeretlen Blokk", "gas");
ok(m === null, "ismeretlen név nem párosul");
m = P.matchName(plants, "MÁTRA 2", "coal");
ok(m === null || (m.plant && m.plant.fuel === "coal"), "a Mátra szénblokk, ha párosul, szénerőműhöz kapcsolódik");
// többértelműség: két azonos töves erőmű -> nincs egyedi találat
const dup = [{ id: "a", name: "A", fuel: "gas", match: ["abc"] }, { id: "b", name: "B", fuel: "gas", match: ["abc"] }];
m = P.matchName(dup, "ABC 1", "gas");
ok(m && m.ambiguous && m.ambiguous.length === 2 && !m.plant, "két azonos tövű erőmű: többértelmű, nem választunk");
ok(P.matchName([{ id: "x", name: "X", fuel: "gas", match: [] }], "X 1", "gas") === null, "üres töves erőmű nem párosul");
ok(P.norm("Százhalombatta Á") === "szazhalombatta a", "az ékezetmentesítés és kisbetűsítés működik");

const units = [
  { name: "PAKS 1", group: "nuclear", mw: [450, 450] },
  { name: "PAKS 2", group: "nuclear", mw: [470, 470] },
  { name: "VALAMI MÁS", group: "gas", mw: [10, 10] },
  { name: "ABC 1", group: "gas", mw: [1, 1] }
];
const MU = P.matchUnits(plants.concat(dup), units);
ok((MU.byPlant[byName("Paksi Atom").id] || []).length === 2, "a két Paks-blokk ugyanahhoz az erőműhöz kerül");
ok(MU.unmatched.length === 1 && MU.unmatched[0].name === "VALAMI MÁS", "az ismeretlen egység a nem párosított listába kerül");
ok(MU.ambiguous.length === 1 && MU.ambiguous[0].plants.length === 2, "a többértelmű egység külön listába kerül, nem találgatunk");

// ---------------------------------------------------------------- érték, energia
console.log("[érték és energia]");
const ts = []; for (let i = 0; i < 48; i++) ts.push(new Date(Date.UTC(2026, 10, 20, i)).toISOString());   // 2026-11-20 00:00Z …
const u1 = { name: "PAKS 1", group: "nuclear", mw: new Array(48).fill(null) };
for (let i = 0; i < 30; i++) u1.mw[i] = 450;
let L = P.latest(u1, ts, null);
ok(L && L.i === 29 && L.mw === 450, "a legutóbbi közölt óra a 29. index");
L = P.latest(u1, ts, +new Date(ts[10]));
ok(L && L.i === 10, "az upTo határ után eső (jövőbeli) értékeket kihagyja");
ok(P.latest({ mw: [null, NaN, null] }, ts, null) === null, "csupa hiányzó érték → nincs legutóbbi érték (nem nulla)");
const u0 = { name: "X", group: "gas", mw: [0, 0, 0] };
L = P.latest(u0, ts, null);
ok(L && L.mw === 0, "a közölt 0 MW érték különbözik a hiányzótól");
let E = P.energy24([u1], 29);
ok(E.mwh === 24 * 450 && E.n === 24, "24 érvényes óra × 450 MW = 10 800 MWh");
const u2 = { name: "PAKS 2", group: "nuclear", mw: u1.mw.slice() };
for (let i = 10; i < 20; i++) u2.mw[i] = null;       // 10 hiányzó óra
E = P.energy24([u1, u2], 29);
ok(E.mwh === null && E.n === 14, "10 hiányzó óránál (14 érvényes) nem számol energiát, nem tölt ki nullával");
const u3 = { name: "PAKS 3", group: "nuclear", mw: u1.mw.slice() };
for (let i = 8; i < 11; i++) u3.mw[i] = null;        // 3 hiányzó óra, 21 érvényes
E = P.energy24([u3], 29);
ok(E.mwh === 21 * 450 && E.n === 21, "3 hiányzó óránál (21 érvényes) kiszámol, a hiányzó órák kimaradnak");
ok(P.energy24([], 29).mwh === null && P.energy24([u1], null).mwh === null, "egység nélkül vagy végindex nélkül nincs energia");

// ---------------------------------------------------------------- állapotok
console.log("[állapotok]");
const PK = byName("Paksi Atom"), TI = byName("Tiszai"), DU = byName("Dunamenti");
const nowMs = +new Date(ts[29]) + 20 * 6e4;                                  // 29. óra után 20 perccel
const engine = {
  generated_utc: new Date(nowMs).toISOString(), hourly_ts: ts,
  units: [
    { name: "PAKS 1", group: "nuclear", mw: u1.mw.map((v) => (v == null ? v : 400)) },
    { name: "PAKS 2", group: "nuclear", mw: u1.mw.map((v) => (v == null ? v : 500)) },
    { name: TI.match[0].toUpperCase() + " 1", group: TI.fuel === "gas" ? "gas" : "other", mw: u1.mw.map((v) => (v == null ? v : 0)) },
    { name: DU.match[0].toUpperCase() + " G", group: "gas", mw: new Array(48).fill(null).map((_, i) => (i < 12 ? 300 : null)) }     // utolsó adat 17 órával korábbi → elavult
  ],
  unit_capacity: [{ name: "PAKS 1", group: "nuclear", mw: 500 }, { name: "PAKS 2", group: "nuclear", mw: 500 }],
  outages_gen: [{ name: "PAKS 2", group: "nuclear", start: new Date(nowMs - 36e5).toISOString(), end: new Date(nowMs + 36e5 * 48).toISOString(), avail_mw: 0, planned: true }]
};
const S = P.plantStates(plants, engine, { now: nowMs });
const sPK = S.states[PK.id], sTI = S.states[TI.id], sDU = S.states[DU.id];
ok(sPK.state === "producing" && sPK.mw === 900, "Paks: termel, két blokk összege 900 MW");
ok(Math.abs(sPK.frac - 0.9) < 1e-9 && sPK.capKnown === 1000, "Paks: terhelés 900/1000 MW = 90 % (mindkét blokk A71 kapacitása ismert)");
ok(sPK.mwh === 24 * 900 && sPK.mwhN === 24, "Paks: 24 órás energia 21 600 MWh");
ok(sPK.outageNow === true && sPK.outages.length === 1, "Paks: a folyamatban lévő tervezett kiesés látszik");
ok(sTI.state === "idle" && sTI.mw === 0, "közölt 0 MW → „áll” (idle), nem „nincs adat”");
ok(sDU.state === "stale" && sDU.t != null, "17 órával korábbi utolsó érték → elavult (stale)");
const others = plants.filter((p) => [PK.id, TI.id, DU.id].indexOf(p.id) < 0);
ok(others.every((p) => S.states[p.id].state === "nodata" && S.states[p.id].mw === null && S.states[p.id].frac === null), "egységadat nélküli erőműnél nincs állapot és nincs érték (nem nulla)");
ok(S.unmatched.length === 0 && S.ambiguous.length === 0, "ebben a készletben nincs párosítatlan egység");
// terhelés csak ha minden párosított egység kapacitása ismert
const e2 = JSON.parse(JSON.stringify(engine)); e2.unit_capacity = [{ name: "PAKS 1", group: "nuclear", mw: 500 }];
ok(P.plantStates(plants, e2, { now: nowMs }).states[PK.id].frac === null, "ha az egyik blokk kapacitása hiányzik, nincs terhelés %");
const e3 = JSON.parse(JSON.stringify(engine)); e3.unit_capacity.push({ name: "PAKS 1", group: "nuclear", mw: 480 });
ok(P.plantStates(plants, e3, { now: nowMs }).states[PK.id].frac === null, "kétértelmű kapacitás-bejegyzésnél nincs terhelés %");
// nincs ENTSO-E adat egyáltalán
const S0 = P.plantStates(plants, null, { now: nowMs });
ok(plants.every((p) => S0.states[p.id].state === "nodata"), "ENTSO-E adat nélkül minden erőmű „nincs adat” (nem termel, nem áll)");
ok(P.plantStates(plants, { hourly_ts: [], units: [] }, { now: nowMs }).unmatched.length === 0, "üres egységlistával sem hibázik");
// ismeretlen / többértelmű egységek megjelennek
const e4 = JSON.parse(JSON.stringify(engine)); e4.units.push({ name: "TELJESEN ISMERETLEN", group: "gas", mw: [5] });
ok(P.plantStates(plants, e4, { now: nowMs }).unmatched.length === 1, "az ismeretlen ENTSO-E egység a nem párosított listába kerül");
// elavultság: a múltbeli „most”
const old = P.plantStates(plants, engine, { now: nowMs + 36e5 * 10 }).states[PK.id];
ok(old.state === "stale", "10 órával később már elavult az adat (a 6 órás határ felett)");

// ---------------------------------------------------------------- lefedettség
console.log("[lefedettség]");
const cov = P.coverage(plants, { nuclear: 2000, gas: 2900, coal: 700, solar: 8500, wind: 330, bio: 300, hydro: 60, other: 100 }, reg.fuels);
const cN = cov.find((x) => x.fuel === "nuclear"), cW = cov.find((x) => x.fuel === "wind"), cS = cov.find((x) => x.fuel === "solar");
near(cN.mapped, 1886.8, 0.01, "atom: a térképen 1886,8 MW");
near(cN.share, 1886.8 / 2000, 1e-9, "atom: lefedettség 94,3 %");
ok(cW.n === 0 && cW.mapped === 0 && cW.national === 330 && cW.share === 0, "szél: a térképen 0 erőmű, az országos 330 MW – a hiány látszik");
ok(cS.share != null && cS.share < 0.05, "napelem: a lista a országos kapacitásnak csak kis része (" + (cS.share * 100).toFixed(1) + " %)");
const cov0 = P.coverage(plants, null, reg.fuels);
ok(cov0.every((x) => x.national === null && x.share === null), "országos adat nélkül nincs hányados (nem 0 %)");

// ---------------------------------------------------------------- jelalakok és méret
console.log("[jelalakok]");
const fuels = Object.keys(reg.fuels);
const shapes = fuels.map((f) => P.shape(f, 6));
ok(shapes.every((s) => /^M[-\d.,L]+Z$/.test(s) || s.length > 4), "minden tüzelőanyaghoz van jelalak");
ok(new Set(shapes).size === fuels.length, "a hét tüzelőanyag-csoport jelalakja páronként különbözik (szín nélkül is megkülönböztethető)");
ok(P.radius(0) === 3.4 && P.radius(1886.8) > P.radius(100) && P.radius(100) > P.radius(2), "a jelölő mérete a teljesítménnyel nő");

console.log("\nMINDEN OK (" + n + " ellenőrzés)");
