import type { Db } from './db.js';
import { tx } from './db.js';
import { cityPlots, DISTRICTS, ZONES, ECONOMY_DEFAULTS, CATALOG, ZoneCode, costOf } from './economy.js';

/** Idempotent: safe to run on every start. */
export async function seed(db: Db, opts: { demo: boolean; log?: (m: string) => void }) {
  const log = opts.log || (() => {});
  await tx(db, async (c) => {
    for (const [i, name] of DISTRICTS.entries()) {
      await c.query('insert into districts(id,name) values ($1,$2) on conflict (id) do update set name = excluded.name', [i, name]);
    }
    for (const [code, z] of Object.entries(ZONES)) {
      await c.query('insert into zones(code,name,base_price) values ($1,$2,$3) on conflict (code) do update set name = excluded.name, base_price = excluded.base_price', [code, z.name, z.base]);
    }
    // building_templates keeps the "active" switch per type (admin can retire one); prices live in the catalog
    const tplRows: [string, string, string[], number, number, number][] = [
      ...Object.entries(CATALOG.types).map(([k, t]) => [k, t.name, t.zones, t.cost[0], t.build[0], t.income[0]] as [string, string, string[], number, number, number]),
      ...Object.entries(CATALOG.landmarks).map(([k, l]) => [k, l.name + ' nusxasi', ['cen'], l.cost, l.build, l.income] as [string, string, string[], number, number, number]),
    ];
    for (const r of tplRows) {
      await c.query(
        `insert into building_templates(code,name,zones,cost,build_seconds,income_per_day) values ($1,$2,$3,$4,$5,$6)
         on conflict (code) do update set name=excluded.name, zones=excluded.zones, cost=excluded.cost, build_seconds=excluded.build_seconds, income_per_day=excluded.income_per_day`, r);
    }
    for (const [k, v] of Object.entries(ECONOMY_DEFAULTS)) {
      await c.query('insert into economy_config(key,value) values ($1,$2) on conflict (key) do nothing', [k, JSON.stringify(v)]);
    }
    // plots: insert the ones this layout adds (first start: all; after the 10× expansion: the outer ring)
    const { rows } = await c.query('select count(*)::int n from plots');
    const all = cityPlots(), add = rows[0].n < all.length ? all : [];
    for (let k = 0; k < add.length; k += 2000) {
      const part = add.slice(k, k + 2000), vals: unknown[] = [];
      const ph = part.map((p, i) => {
        vals.push(p.id, p.district, p.zone, p.x, p.z, p.loc);
        const b = i * 6;
        return `($${b + 1},$${b + 2},$${b + 3},$${b + 4},$${b + 5},$${b + 6})`;
      });
      await c.query(`insert into plots(id,district_id,zone,x,z,location_factor) values ${ph.join(',')} on conflict (id) do nothing`, vals);
    }
    if (add.length) log(`plots: ${rows[0].n} → ${all.length}`);
  });
  if (opts.demo) await seedDemo(db, log);
  await seedLandmarks(db, log);
  await landmarkBlocks(db, log);
}

const NICKS = ['sardor_77', 'Malika', 'jasur.dev', 'Dilnoza', 'bekzod_uz', 'Aziza.k', 'Otabek', 'Shahzoda', 'timur99', 'nodira', 'Ulug‘bek', 'Sevara', 'Javohir', 'Kamola', 'rustam_b', 'Laylo', 'Akmal', 'Madina', 'Sherzod', 'Zarina', 'Bobur', 'Jahongir', 'Islom', 'Feruza'];

/** Demo neighbours (role = 'bot') so a new city is not empty. Deterministic; runs only once. */
async function seedDemo(db: Db, log: (m: string) => void) {
  const { rows } = await db.query("select count(*)::int n from users where role = 'bot'");
  if (rows[0].n > 0) return;
  let s = 20261105;
  const rnd = () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
  await tx(db, async (c) => {
    const botIds: number[] = [];
    for (const nick of NICKS) {
      const u = await c.query(
        "insert into users(nickname,nickname_lower,role,avatar_id,birth_confirmed_16,created_at) values ($1,$2,'bot',$3,true, now() - interval '30 days') returning id",
        [nick, nick.toLowerCase(), 1 + Math.floor(rnd() * 12)]);
      const id = u.rows[0].id;
      botIds.push(id);
      await c.query("insert into auth_identities(user_id,provider,subject) values ($1,'bot',$2)", [id, nick]);
      await c.query('insert into wallets(user_id,balance) values ($1,0)', [id]);
    }
    // one showcase building per mahalla (one per style); everything else is free land for real players
    const show = [
      { district: 0, template: 'cafe',   style: 'milliy', floors: 2,  roof: 'dome',    color: '#ecd9b4', accent: '#2a9d8f' },
      { district: 1, template: 'office', style: 'hitech', floors: 12, roof: 'helipad', color: '#b7d3e3', accent: '#1f6fb2' },
      { district: 2, template: 'flat',   style: 'modern', floors: 9,  roof: 'garden',  color: '#f4f1ea', accent: '#e08a2c' },
    ];
    let n = 0;
    for (const sh of show) {
      const p = (await c.query("select id from plots where district_id = $1 and zone <> 'res' and status = 'empty' order by id limit 1", [sh.district])).rows[0];
      if (!p) continue;
      const owner = botIds[n % botIds.length];
      await c.query("update plots set owner_id=$1, status='owned', purchased_at=now() - interval '20 days' where id=$2", [owner, p.id]);
      await c.query(
        `insert into buildings(plot_id,template,style,floors,roof,rotation,color,accent,ready_at,last_collected_at)
         values ($1,$2,$3,$4,$5,$6,$7,$8, now() - interval '19 days', now())`,
        [p.id, sh.template, sh.style, sh.floors, sh.roof, Math.floor(rnd() * 4), sh.color, sh.accent]);
      n++;
    }
    log(`demo city: ${botIds.length} neighbours, ${n} buildings`);
  });
}

/**
 * The landmark copies (the 10 tallest buildings plus Hilton Tashkent City) stand around the central park from day one, owned by the city and for sale.
 * Idempotent: a landmark that already exists anywhere (city-owned or bought by a player) is skipped.
 * Placement: empty centre-zone plots nearest the park, at least 40 m apart (the 3D client uses the same rule offline).
 */
export async function seedLandmarks(db: Db, log: (m: string) => void = () => {}) {
  await tx(db, async (c) => {
    const have = new Set((await c.query("select template from buildings where template like 'lm\\_%'")).rows.map((r) => r.template));
    const missing = Object.keys(CATALOG.landmarks).filter((k) => !have.has(k));
    if (!missing.length) return;
    let city = (await c.query("select id from users where nickname_lower = 'shahar hokimligi'")).rows[0]?.id;
    if (!city) {
      city = (await c.query("insert into users(nickname,nickname_lower,role,birth_confirmed_16,created_at) values ('Shahar hokimligi','shahar hokimligi','bot',true, now() - interval '60 days') returning id")).rows[0].id;
      await c.query("insert into auth_identities(user_id,provider,subject) values ($1,'bot','city')", [city]);
      await c.query('insert into wallets(user_id,balance) values ($1,0)', [city]);
    }
    const free = (await c.query("select id, x, z from plots where zone = 'cen' and status = 'empty' order by (x*x + z*z), id")).rows as { id: number; x: number; z: number }[];
    const taken = (await c.query("select p.x, p.z from buildings b join plots p on p.id = b.plot_id where b.template like 'lm\\_%'")).rows as { x: number; z: number }[];
    let n = 0;
    for (const key of missing) {
      const spot = free.find((p) => taken.every((t) => Math.hypot(t.x - p.x, t.z - p.z) >= 40));
      if (!spot) break;
      taken.push(spot); free.splice(free.indexOf(spot), 1);
      await c.query("update plots set owner_id = $1, status = 'owned', purchased_at = now() where id = $2", [city, spot.id]);
      await c.query(
        `insert into buildings(plot_id,template,style,floors,roof,rotation,color,accent,ready_at,last_collected_at)
         values ($1,$2,'hitech',1,'none',0,'#cfe3ee','#2a9d8f', now() - interval '1 day', now())`, [spot.id, key]);
      await c.query('insert into listings(plot_id,seller_id,price) values ($1,$2,$3)', [spot.id, city, Math.round(costOf(key, 1) * 1.25 / 1000) * 1000]);
      n++;
    }
    if (n) log(`landmarks placed: ${n}`);
  });
}

/**
 * Every skyscraper copy stands alone in its own block (45 × 45 m, real proportions at half the real height).
 * - A copy that shares its block with another building or a player's plot is moved to a block where all 16 plots are
 *   free (nearest to the centre, 'cen' zone first); its owner, listing and likes move with it.
 * - The other free plots of its block become city land (owned by "Shahar hokimligi", not for sale).
 * Players' plots are never taken. Idempotent: runs on every start, does nothing once settled.
 */
export async function landmarkBlocks(db: Db, log: (m: string) => void = () => {}) {
  await tx(db, async (c) => {
    const city = (await c.query("select id from users where nickname_lower = 'shahar hokimligi'")).rows[0]?.id;
    if (!city) return;
    const plots = (await c.query(
      `select p.id, p.x, p.z, p.zone, p.status, p.owner_id, b.template
         from plots p left join buildings b on b.plot_id = p.id order by p.id for update of p`)).rows as
      { id: number; x: number; z: number; zone: string; status: string; owner_id: number | null; template: string | null }[];
    const byId = new Map(plots.map((p) => [p.id, p]));
    const blockOf = (id: number) => Math.floor(id / 16);            // plots are laid out 16 per block, block by block
    const blockPlots = (b: number) => plots.filter((p) => blockOf(p.id) === b);
    const lms = plots.filter((p) => p.template && p.template.startsWith('lm_'))
      .sort((a, b) => (CATALOG.landmarks[b.template!]?.realHeight ?? 0) - (CATALOG.landmarks[a.template!]?.realHeight ?? 0));
    const used = new Set<number>();
    const freeForCity = (p: typeof plots[0]) => (p.status === 'empty' && p.owner_id === null) || (p.owner_id === city && !p.template && p.status === 'owned');
    let moved = 0, claimed = 0;
    for (const lm of lms) {
      let blk = blockOf(lm.id);
      const ok = !used.has(blk) && blockPlots(blk).every((q) => q.id === lm.id || freeForCity(q));
      if (!ok) {
        const cand = new Map<number, typeof plots>();
        for (const p of plots) { const b = blockOf(p.id); if (!cand.has(b)) cand.set(b, []); cand.get(b)!.push(p); }
        const zoneRank = (z: string) => (z === 'cen' ? 0 : z === 'com' ? 1 : 2);
        const choices = [...cand.entries()]
          .filter(([b, ps]) => !used.has(b) && ps.length === 16 && ps.every(freeForCity))
          .map(([b, ps]) => ({ b, ps, cx: ps.reduce((s, p) => s + p.x, 0) / 16, cz: ps.reduce((s, p) => s + p.z, 0) / 16 }))
          .sort((a, b) => zoneRank(a.ps[0].zone) - zoneRank(b.ps[0].zone) || Math.hypot(a.cx, a.cz) - Math.hypot(b.cx, b.cz));
        if (!choices.length) { log(`landmark ${lm.template}: no free block`); used.add(blk); continue; }
        const target = choices[0], anchor = target.ps[5];             // an inner plot of the block
        const old = (await c.query('select owner_id, status, purchased_at from plots where id = $1', [lm.id])).rows[0];
        await c.query('update plots set owner_id = $1, status = $2, purchased_at = $3 where id = $4', [old.owner_id, old.status, old.purchased_at, anchor.id]);
        await c.query('update buildings set plot_id = $1 where plot_id = $2', [anchor.id, lm.id]);
        await c.query("update listings set plot_id = $1 where plot_id = $2 and status = 'active'", [anchor.id, lm.id]);
        await c.query('update likes set plot_id = $1 where plot_id = $2', [anchor.id, lm.id]);
        await c.query("update plots set owner_id = null, status = 'empty', purchased_at = null where id = $1", [lm.id]);
        Object.assign(byId.get(anchor.id)!, { owner_id: old.owner_id, status: old.status, template: lm.template });
        Object.assign(byId.get(lm.id)!, { owner_id: null, status: 'empty', template: null });
        blk = target.b; moved++;
      }
      used.add(blk);
      for (const q of blockPlots(blk)) if (q.status === 'empty' && q.owner_id === null) {
        await c.query("update plots set owner_id = $1, status = 'owned', purchased_at = now() where id = $2 and status = 'empty'", [city, q.id]);
        q.owner_id = city; q.status = 'owned'; claimed++;
      }
    }
    if (moved || claimed) log(`landmark blocks: ${moved} moved, ${claimed} plots reserved`);
  });
}
