import type { Db } from './db.js';
import { tx } from './db.js';
import { cityPlots, DISTRICTS, ZONES, TEMPLATES, ECONOMY_DEFAULTS, COLORS, ZoneCode } from './economy.js';

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
    for (const [code, t] of Object.entries(TEMPLATES)) {
      await c.query(
        `insert into building_templates(code,name,zones,cost,build_seconds,income_per_day) values ($1,$2,$3,$4,$5,$6)
         on conflict (code) do update set name=excluded.name, zones=excluded.zones, cost=excluded.cost, build_seconds=excluded.build_seconds, income_per_day=excluded.income_per_day`,
        [code, t.name, t.zones, t.cost, t.buildSeconds, t.income]);
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
  const pick = <T,>(a: T[]) => a[Math.floor(rnd() * a.length)];
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
    const occ: Record<ZoneCode, number> = { res: 0.55, com: 0.5, cen: 0.38 };
    const plots = (await c.query('select id, zone from plots order by id')).rows as { id: number; zone: ZoneCode }[];
    let n = 0;
    for (const p of plots) {
      if (rnd() >= occ[p.zone]) continue;
      const owner = pick(botIds);
      const opts = Object.keys(TEMPLATES).filter((k) => TEMPLATES[k].zones.includes(p.zone));
      let k = pick(opts);
      if (p.zone === 'res' && rnd() < 0.5) k = rnd() < 0.6 ? 'house' : 'villa';
      if (p.zone === 'cen' && rnd() < 0.22) k = rnd() < 0.5 ? 'tower' : 'office';
      const color = k === 'tower' ? pick(COLORS.glass) : pick(COLORS.wall);
      await c.query("update plots set owner_id=$1, status='owned', purchased_at=now() - interval '20 days' where id=$2", [owner, p.id]);
      await c.query(
        `insert into buildings(plot_id,template,rotation,color,accent,ready_at,last_collected_at)
         values ($1,$2,$3,$4,$5, now() - interval '19 days', now())`,
        [p.id, k, Math.floor(rnd() * 4), color, pick(COLORS.accent)]);
      if (rnd() < 0.07) {
        // a few demo plots are for sale
        await c.query('insert into listings(plot_id,seller_id,price) values ($1,$2,$3)', [p.id, owner, 1]);
      }
      n++;
    }
    // price the demo listings at the system estimate (needs occupancy, so done after placement)
    await c.query(`
      update listings l set price = greatest(100, round(( z.base_price * p.location_factor * 1.25 * 1.25 + t.cost * 0.9) / 100) * 100)
      from plots p join zones z on z.code = p.zone join buildings b on b.plot_id = p.id join building_templates t on t.code = b.template
      where l.plot_id = p.id and l.status = 'active' and l.price = 1`);
    log(`demo city: ${botIds.length} neighbours, ${n} buildings`);
  });
}
