// A böngészős adatréteg (assets/gfhist.js) tesztje Node-ban, a demo-hist/ és a demo-history.json fájlokkal.
// Futtatás:  node tests/test_gfhist.js
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm"), assert = require("assert");
const ROOT = path.resolve(__dirname, "..");
function load() {
  const ctx = { console, Intl, Date, Math, Promise, JSON, Object, Array, Number, String, Error, setTimeout };
  ctx.window = ctx;
  ctx.fetch = async (url) => {
    const p = path.join(ROOT, url.split("?")[0]);
    if (!fs.existsSync(p)) return { ok: false, status: 404, json: async () => { throw new Error("404"); } };
    return { ok: true, status: 200, json: async () => JSON.parse(fs.readFileSync(p, "utf8")) };
  };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(ROOT, "assets/gfhist.js"), "utf8"), ctx);
  return ctx.GFHist;
}
const same = (a, b, m) => assert.strictEqual(JSON.stringify(a), JSON.stringify(b), m);   // a vm-környezet tömbjei más prototípusúak
const rd = (f) => JSON.parse(fs.readFileSync(path.join(ROOT, f), "utf8"));

(async () => {
  // ---- 1. hist mód
  let H = load();
  let info = await H.init({ root: "demo-hist/", fallbackUrl: "demo-history.json" });
  assert.strictEqual(info.mode, "hist");
  same(H.zones().sort(), ["AT", "CZ", "DE_LU", "HR", "HU", "RO", "RS", "SI", "SK", "UA"]);
  assert.ok(["generation", "load", "price_da", "flow_physical", "net_import", "co2", "ramp"].every((c) => H.cats("HU").includes(c)));
  assert.ok(!H.cats("AT").includes("flow_physical"));
  assert.ok(H.hasHourly("HU", "load") && H.hasQuarter("HU", "load") && !H.hasQuarter("HU", "generation"));
  same(H.tiersOf("HU", "ramp"), ["d", "w", "m", "y"]);
  console.log("1. hist mód: zónák, kategóriák, elérhetőség rendben");

  // ---- 2. napi lekérdezés = a fájl szeletelése; energia = átlag × órák
  let q = await H.query({ zone: "HU", cat: "generation", res: "d", from: "2025-07-01", to: "2025-07-31", series: ["solar", "nuclear"] });
  assert.strictEqual(q.keys.length, 31);
  const raw = rd("demo-hist/d/HU/generation.json"), i0 = raw.keys.indexOf("2025-07-01");
  same(q.series.solar, raw.series.solar.avg.slice(i0, i0 + 31));
  const qe = await H.query({ zone: "HU", cat: "generation", res: "d", from: "2025-07-01", to: "2025-07-03", series: ["solar"], stat: "energy" });
  assert.ok(Math.abs(qe.series.solar[0] - raw.series.solar.avg[i0] * 24 / 1000) < 0.001 && qe.unit === "GWh");
  console.log("2. napi szelet és energia (MW × óra) rendben");

  // ---- 3. DST: a helyi napok 23 / 25 órások
  const dst = await H.query({ zone: "HU", cat: "load", res: "d", from: "2026-03-28", to: "2026-03-30" });
  same(dst.h, [24, 23, 24]);
  const dst2 = await H.query({ zone: "HU", cat: "load", res: "d", from: "2026-10-24", to: "2026-10-26" });
  same(dst2.h, [24, 25, 24]);
  const hr = await H.query({ zone: "HU", cat: "load", res: "h", from: "2026-03-28", to: "2026-03-30" });
  assert.strictEqual(hr.keys.length, 71, "24 + 23 + 24 óra");
  assert.strictEqual(hr.keys[1] - hr.keys[0], 3600);
  assert.ok(hr.series.load.every((v) => v != null));
  const hr2 = await H.query({ zone: "HU", cat: "load", res: "h", from: "2026-10-25", to: "2026-10-25" });
  assert.strictEqual(hr2.keys.length, 25);
  assert.strictEqual(H.labelHour(hr2.keys[2]), H.labelHour(hr2.keys[3]), "az ismétlődő helyi óra azonos címkét kap");
  console.log("3. DST-napok órái (23/25) és az óránkénti szelet rendben");

  // ---- 4. hét, hónap, év, jövő
  const wk = await H.query({ zone: "HU", cat: "load", res: "w", from: "2026-03-23", to: "2026-03-29" });
  same(wk.keys, ["2026-W13"]); assert.strictEqual(wk.h[0], 167);
  const mo = await H.query({ zone: "HU", cat: "load", res: "m", from: "2026-09-01", to: "2026-11-30" });
  same(mo.keys, ["2026-09", "2026-10", "2026-11"]);
  assert.ok(mo.n.load[2] < mo.h[2] && mo.n.load[2] / mo.h[2] >= 0.7 && mo.series.load[2] != null, "a folyó hó részleges, de 70 % felett: van értéke");
  const mo2 = await H.query({ zone: "HU", cat: "load", res: "m", from: "2026-11-01", to: "2026-11-30" });
  assert.strictEqual(mo2.n.load[0], mo.n.load[2]);
  const fut = await H.query({ zone: "HU", cat: "load", res: "h", from: "2026-11-25", to: "2026-11-26" });
  assert.strictEqual(fut.keys.length, 0, "az utolsó mért óra utáni jövő nem kerül vissza (nem 'hiányzó adat', nem nulla)");
  const lastDay = await H.query({ zone: "HU", cat: "load", res: "h", from: "2026-11-23", to: "2026-11-24" });
  const lastKey = lastDay.keys[lastDay.keys.length - 1];
  assert.strictEqual(lastKey, H.manifest().zones.HU.cats.load.last, "az órás szelet pontosan az utolsó mért órával ér véget");
  assert.ok(lastDay.keys.length < 24 && lastDay.series.load.filter((v) => v != null).length > 0, "a folyamatban lévő nap rövidebb, csak mért órákkal");
  const lq = await H.query({ zone: "HU", cat: "price_da", res: "q", from: "2026-11-23", to: "2026-11-24" });
  assert.ok(lq.keys[lq.keys.length - 1] < H.manifest().zones.HU.cats.price_da.last + 3600, "a negyedórás szelet sem lóg túl az utolsó mért órán");
  const before = await H.query({ zone: "HU", cat: "load", res: "h", from: "2023-12-01", to: "2023-12-31" });
  assert.strictEqual(before.keys.length, 0, "az első mért óra előtti rész sem kerül vissza");
  assert.strictEqual(H.isoWeekKey("2026-12-31"), "2026-W53"); assert.strictEqual(H.isoWeekKey("2027-01-01"), "2026-W53"); assert.strictEqual(H.isoWeekKey("2027-01-04"), "2027-W01");
  console.log("4. heti/havi/éves szelet, folyamatban lévő hó, a mért időszakon túli rész nincs a válaszban");

  // ---- 5. igazítás: azonos naptári nap / szökőnap / DST-átállás
  const base = await H.query({ zone: "HU", cat: "load", res: "d", from: "2024-02-01", to: "2024-02-29" });
  const oth = await H.query({ zone: "HU", cat: "load", res: "d", from: "2025-02-01", to: "2025-02-28" });
  const al = H.alignTo(base, oth);
  assert.strictEqual(al.load.length, 29); assert.strictEqual(al.load[28], null, "február 29. nincs az előző évben");
  assert.strictEqual(al.load[0], oth.series.load[0]); assert.strictEqual(al.load[27], oth.series.load[27]);
  assert.strictEqual(H.shiftYear("2024-02-29", -1), "2023-02-28"); assert.strictEqual(H.shiftYear("2026-03-15", -1), "2025-03-15");
  const b = { res: "h", keys: [], series: { x: [] } }, o2 = { res: "h", keys: [], series: { x: [] } };
  for (let i = 0; i < 25; i++) { b.keys.push(H.midnight("2026-10-25") + i * 3600); b.series.x.push(i); }
  for (let i = 0; i < 24; i++) { o2.keys.push(H.midnight("2025-10-25") + i * 3600); o2.series.x.push(100 + i); }
  const ah = H.alignTo(b, o2);
  assert.strictEqual(ah.x.length, 25); assert.strictEqual(ah.x.filter((v) => v == null).length, 1, "a 25. (ismétlődő) óra nem talál párt");
  assert.strictEqual(ah.x[0], 100); assert.strictEqual(ah.x[1], 101);
  console.log("5. igazítás (szökőnap, DST-nap) rendben");

  // ---- 6. negatív órák, szórás nélküli kategóriák
  const ng = await H.query({ zone: "HU", cat: "price_da", res: "m", from: "2026-04-01", to: "2026-08-31", stat: "neg" });
  assert.strictEqual(ng.unit, "óra"); assert.ok(ng.series.price.some((v) => v > 0));
  console.log("6. negatív órák száma rendben");

  // ---- 7. havi tartalék (history.json)
  H = load();
  info = await H.init({ root: "nincs-ilyen/", fallbackUrl: "demo-history.json" });
  assert.strictEqual(info.mode, "monthly");
  same(H.tiersOf("HU", "load"), ["m", "y"]);
  assert.ok(!H.hasHourly("HU", "load"));
  assert.ok(H.zones().includes("AT") && H.cats("AT").join() === "price_da", H.cats("AT"));
  assert.ok(!H.avail("HU", "flow_physical").series.includes("UA"));
  const hist = rd("demo-history.json");
  const g = await H.query({ zone: "HU", cat: "generation", res: "m", from: "2025-01-01", to: "2025-12-31", series: ["solar"] });
  assert.strictEqual(g.keys.length, 12);
  const hrs = g.h[6];                                       // július: 744 óra
  assert.strictEqual(hrs, 744);
  assert.ok(Math.abs(g.series.solar[6] - hist.months["2025-07"].gen.solar * 1000 / 744) < 0.06);
  const y = await H.query({ zone: "HU", cat: "load", res: "y", from: "2024-01-01", to: "2025-12-31" });
  same(y.keys, ["2024", "2025"]); assert.ok(y.series.load[0] > 3000 && y.series.load[0] < 8000);
  const cur = await H.query({ zone: "HU", cat: "load", res: "y", from: "2026-01-01", to: "2026-12-31" });
  assert.strictEqual(cur.series.load[0], null, "a folyó év nem teljes: nincs éves érték");
  const co2 = await H.query({ zone: "HU", cat: "co2", res: "m", from: "2025-07-01", to: "2025-07-31" });
  assert.ok(co2.series.intensity[0] > 50 && co2.series.intensity[0] < 600, co2.series.intensity);
  const ni = await H.query({ zone: "HU", cat: "net_import", res: "m", from: "2025-07-01", to: "2025-07-31" });
  assert.ok(Math.abs(ni.series.net[0] - hist.months["2025-07"].imp_gwh * 1000 / 744) < 0.06);
  console.log("7. havi tartalék: óraszámok, súlyozás, folyó év, CO₂, nettó import rendben");

  // ---- 8. nincs adat
  H = load();
  info = await H.init({ root: "nincs-ilyen/", fallbackUrl: "nincs-ilyen.json" });
  assert.strictEqual(info.mode, "none"); same(H.zones(), []);
  console.log("8. adat nélküli állapot kezelve");
  console.log("Minden gfhist teszt rendben.");
})().catch((e) => { console.error("HIBA:", e && e.stack || e); process.exit(1); });
