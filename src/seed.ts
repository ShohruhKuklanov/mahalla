import type { Db } from './db.js';
import { tx } from './db.js';
import { cityPlots, DISTRICTS, ZONES, ECONOMY_DEFAULTS, CATALOG, ZoneCode } from './economy.js';

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
    const { rows } = await c.query('select count(*)::int n from plots');
    if (rows[0].n === 0) {
      const plots = cityPlots();
      // one multi-row insert
      const vals: unknown[] = [];
      const ph = plots.map((p, i) => {
        vals.push(p.id, p.district, p.zone, p.x, p.z, p.loc);
        const b = i * 6;
        return `($${b + 1},$${b + 2},$${b + 3},$${b + 4},$${b + 5},$${b + 6})`;
      });
      await c.query(`insert into plots(id,district_id,zone,x,z,location_factor) values ${ph.join(',')}`, vals);
      log(`seeded ${plots.length} plots`);
    }
  });
  if (opts.demo) await seedDemo(db, log);
}

const NICKS = ['sardor_77', 'Malika', 'jasur.dev', 'Dilnoza', 'bekzod_uz', 'Aziza.k', 'Otabek', 'Shahzoda', 'timur99', 'nodira', 'Ulug‘bek', 'Sevara', 'Javohir', 'Kamola', 'rustam_b', 'Laylo', 'Akmal', 'Madina', 'Sherzod', 'Zarina', 'Bobur', 'Gulnoza', 'Islom', 'Feruza'];

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
