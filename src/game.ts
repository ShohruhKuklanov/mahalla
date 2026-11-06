// Game rules that move coins or property. Every function here runs in ONE database transaction,
// locks the rows it changes (plot first, then wallets in id order), and writes the ledger.
import type { Db, Tx } from './db.js';
import { tx } from './db.js';
import { config } from './config.js';
import { E } from './errors.js';
import { ECONOMY_DEFAULTS, Economy, TEMPLATES, COLORS, ZoneCode, landPrice, estimate, accrued } from './economy.js';
import type { SessionUser } from './auth.js';

// ---------- economy config (DB overrides, cached briefly) ----------
let ecoCache: { at: number; eco: Economy } | null = null;
export async function economy(db: Db | Tx): Promise<Economy> {
  if (ecoCache && Date.now() - ecoCache.at < 10_000) return ecoCache.eco;
  const eco: any = { ...ECONOMY_DEFAULTS };
  for (const r of (await db.query('select key, value from economy_config')).rows) if (r.key in eco) eco[r.key] = r.value;
  ecoCache = { at: Date.now(), eco };
  return eco;
}
export function clearEconomyCache() { ecoCache = null; }

async function occupancy(c: Db | Tx): Promise<Map<number, number>> {
  const r = await c.query("select district_id, avg((status <> 'empty')::int)::float occ from plots group by district_id");
  return new Map(r.rows.map((x) => [x.district_id, x.occ]));
}

// ---------- read model ----------
export interface PlotDTO {
  id: number; x: number; z: number; zone: ZoneCode; district: number;
  state: 'empty' | 'owned' | 'sale'; price: number | null;
  owner: { id: number; nickname: string | null } | null;
  building: { template: string; rotation: number; color: string; accent: string; level: number; readyAt: string } | null;
  likes: number;
}

const PLOT_SQL = `
  select p.id, p.x, p.z, p.zone, p.district_id, p.location_factor, p.status, p.owner_id, u.nickname as owner_nick,
         b.template, b.rotation, b.color, b.accent, b.level, b.ready_at, b.status as bstatus,
         l.price as listing_price, coalesce(k.n, 0)::int as likes
  from plots p
  left join users u on u.id = p.owner_id
  left join buildings b on b.plot_id = p.id
  left join listings l on l.plot_id = p.id and l.status = 'active'
  left join (select plot_id, count(*) n from likes group by plot_id) k on k.plot_id = p.id`;

function toDTO(r: any, occ: Map<number, number>, eco: Economy): PlotDTO {
  const state = r.status === 'empty' ? 'empty' : r.listing_price != null ? 'sale' : 'owned';
  return {
    id: r.id, x: r.x, z: r.z, zone: r.zone, district: r.district_id, state,
    price: state === 'empty' ? landPrice(r.zone, r.location_factor, occ.get(r.district_id) || 0, eco) : state === 'sale' ? r.listing_price : null,
    owner: r.owner_id ? { id: r.owner_id, nickname: r.owner_nick } : null,
    building: r.template && r.bstatus === 'active'
      ? { template: r.template, rotation: r.rotation, color: r.color, accent: r.accent, level: r.level, readyAt: r.ready_at.toISOString() }
      : null,
    likes: r.likes,
  };
}

export async function allPlots(db: Db): Promise<PlotDTO[]> {
  const [eco, occ, rows] = await Promise.all([economy(db), occupancy(db), db.query(PLOT_SQL + ' order by p.id')]);
  return rows.rows.map((r) => toDTO(r, occ, eco));
}
export async function onePlot(db: Db | Tx, id: number): Promise<PlotDTO | null> {
  const [eco, occ, rows] = await Promise.all([economy(db), occupancy(db), db.query(PLOT_SQL + ' where p.id = $1', [id])]);
  return rows.rows[0] ? toDTO(rows.rows[0], occ, eco) : null;
}

// ---------- ledger helper ----------
async function move(c: Tx, userId: number, amount: number, type: string, refType: string | null, refId: number | null, key: string | null = null) {
  const r = await c.query('update wallets set balance = balance + $2, updated_at = now() where user_id = $1 returning balance', [userId, amount]);
  if (!r.rows.length) throw E.notFound('Hamyon topilmadi');
  await c.query(
    'insert into transactions(user_id,amount,type,ref_type,ref_id,balance_after,idempotency_key) values ($1,$2,$3,$4,$5,$6,$7)',
    [userId, amount, type, refType, refId, r.rows[0].balance, key]);
  return r.rows[0].balance as number;
}
async function lockWallets(c: Tx, ids: number[]) {
  const sorted = [...new Set(ids)].sort((a, b) => a - b);
  const r = await c.query('select user_id, balance from wallets where user_id = any($1) order by user_id for update', [sorted]);
  return new Map<number, number>(r.rows.map((x) => [x.user_id, x.balance]));
}
async function alreadyDone(c: Tx, userId: number, key: string | null) {
  if (!key) return false;
  const r = await c.query('select 1 from transactions where user_id = $1 and idempotency_key = $2', [userId, key]);
  return r.rows.length > 0;
}
const isUnique = (e: any) => e && e.code === '23505' && String(e.constraint || '').includes('idempotency');

function requirePlayer(u: SessionUser | null): SessionUser {
  if (!u) throw E.auth();
  if (u.status === 'banned') throw E.banned();
  if (!u.nickname) throw E.nickRequired();
  return u;
}

// ---------- buy ----------
export async function buyPlot(db: Db, user: SessionUser | null, plotId: number, key: string | null) {
  const u = requirePlayer(user);
  try {
    return await tx(db, async (c) => {
      const p = (await c.query('select * from plots where id = $1 for update', [plotId])).rows[0];
      // checked after the row lock, so a duplicate request waiting on the lock sees the first one's result
      if (await alreadyDone(c, u.id, key)) return { replayed: true };
      if (!p) throw E.notFound('Uchastka topilmadi');
      if (p.status === 'frozen') throw E.conflict('plot_frozen', 'Bu uchastka vaqtincha yopilgan.');
      if (p.owner_id === u.id) throw E.conflict('already_yours', 'Bu uchastka allaqachon sizniki.');
      const listing = (await c.query("select * from listings where plot_id = $1 and status = 'active' for update", [plotId])).rows[0];
      if (p.status === 'owned' && !listing) throw E.conflict('plot_taken', 'Afsus, bu uchastka band bo‘ldi.');
      const eco = await economy(c);
      const mine = (await c.query('select count(*)::int n from plots where owner_id = $1', [u.id])).rows[0].n;
      if (mine >= eco.plot_limit) throw E.conflict('plot_limit', `Ko‘pi bilan ${eco.plot_limit} ta uchastka olish mumkin.`, { limit: eco.plot_limit });

      const price = listing ? Number(listing.price) : landPrice(p.zone, p.location_factor, (await occupancy(c)).get(p.district_id) || 0, eco);
      const seller = listing ? Number(listing.seller_id) : null;
      const bal = await lockWallets(c, seller ? [u.id, seller] : [u.id]);
      const have = bal.get(u.id) ?? 0;
      if (have < price) throw E.funds(price - have);

      await move(c, u.id, -price, 'plot_buy', 'plot', plotId, key);
      if (listing && seller) {
        // the seller keeps income earned up to the moment of sale
        const b = (await c.query('select b.*, t.income_per_day from buildings b join building_templates t on t.code = b.template where plot_id = $1 for update', [plotId])).rows[0];
        if (b) {
          const now = new Date();
          const inc = accrued(b.income_per_day, b.ready_at, b.last_collected_at, now, config.daySeconds, eco.income_cap_days);
          if (inc > 0) await move(c, seller, inc, 'income', 'plot', plotId);
          await c.query('update buildings set last_collected_at = greatest(ready_at, $2) where id = $1', [b.id, now]);
        }
        const fee = Math.round(price * eco.sale_fee);
        await move(c, seller, price, 'plot_sale', 'plot', plotId);
        if (fee > 0) await move(c, seller, -fee, 'fee', 'plot', plotId);
        await c.query("update listings set status = 'sold', buyer_id = $2, sold_at = now() where id = $1", [listing.id, u.id]);
      }
      await c.query("update plots set owner_id = $2, status = 'owned', purchased_at = now(), version = version + 1 where id = $1", [plotId, u.id]);
      return { replayed: false, price };
    });
  } catch (e) {
    if (isUnique(e)) return { replayed: true };
    throw e;
  }
}

// ---------- build ----------
export async function buildOnPlot(db: Db, user: SessionUser | null, plotId: number,
  body: { template: string; rotation: number; color: string; accent: string }, key: string | null) {
  const u = requirePlayer(user);
  const t = TEMPLATES[body.template];
  if (!t) throw E.bad('bad_template', 'Bunday bino shabloni yo‘q.');
  const palette = body.template === 'tower' ? COLORS.glass : COLORS.wall;
  if (!palette.includes(body.color) || !COLORS.accent.includes(body.accent)) throw E.bad('bad_color', 'Bu rang ro‘yxatda yo‘q.');
  try {
    return await tx(db, async (c) => {
      const p = (await c.query('select * from plots where id = $1 for update', [plotId])).rows[0];
      // checked after the row lock, so a duplicate request waiting on the lock sees the first one's result
      if (await alreadyDone(c, u.id, key)) return { replayed: true };
      if (!p) throw E.notFound('Uchastka topilmadi');
      if (p.owner_id !== u.id) throw E.forbidden();
      if ((await c.query('select 1 from buildings where plot_id = $1', [plotId])).rows.length) throw E.conflict('already_built', 'Bu uchastkada bino bor.');
      const tpl = (await c.query('select * from building_templates where code = $1 and active', [body.template])).rows[0];
      if (!tpl) throw E.bad('bad_template', 'Bu shablon hozir mavjud emas.');
      if (!tpl.zones.includes(p.zone)) throw E.bad('wrong_zone', `${tpl.name} bu zonada qurilmaydi.`);
      const bal = await lockWallets(c, [u.id]);
      const have = bal.get(u.id) ?? 0;
      if (have < tpl.cost) throw E.funds(tpl.cost - have);
      await move(c, u.id, -tpl.cost, 'build', 'plot', plotId, key);
      const readyAt = new Date(Date.now() + tpl.build_seconds * 1000);
      await c.query(
        'insert into buildings(plot_id,template,rotation,color,accent,ready_at,last_collected_at) values ($1,$2,$3,$4,$5,$6,$6)',
        [plotId, body.template, body.rotation, body.color, body.accent, readyAt]);
      return { replayed: false, readyAt: readyAt.toISOString() };
    });
  } catch (e) {
    if (isUnique(e)) return { replayed: true };
    throw e;
  }
}

// ---------- income ----------
async function pendingRows(c: Db | Tx, userId: number, lock: boolean) {
  return (await c.query(
    `select b.id, b.ready_at, b.last_collected_at, t.income_per_day from buildings b
     join plots p on p.id = b.plot_id join building_templates t on t.code = b.template
     where p.owner_id = $1 and b.status = 'active' ${lock ? 'for update of b' : ''}`, [userId])).rows;
}
export async function pendingIncome(db: Db, userId: number) {
  const eco = await economy(db); const now = new Date();
  const rows = await pendingRows(db, userId, false);
  return {
    pending: rows.reduce((s, b) => s + accrued(b.income_per_day, b.ready_at, b.last_collected_at, now, config.daySeconds, eco.income_cap_days), 0),
    dailyIncome: rows.filter((b) => b.ready_at <= now).reduce((s, b) => s + b.income_per_day, 0),
  };
}
export async function collect(db: Db, user: SessionUser | null) {
  const u = requirePlayer(user);
  return tx(db, async (c) => {
    await lockWallets(c, [u.id]);
    const eco = await economy(c); const now = new Date();
    let total = 0;
    for (const b of await pendingRows(c, u.id, true)) {
      const inc = accrued(b.income_per_day, b.ready_at, b.last_collected_at, now, config.daySeconds, eco.income_cap_days);
      if (inc <= 0) continue;
      total += inc;
      await c.query('update buildings set last_collected_at = $2 where id = $1', [b.id, now]);
    }
    const balance = total > 0 ? await move(c, u.id, total, 'income', null, null)
      : (await c.query('select balance from wallets where user_id = $1', [u.id])).rows[0].balance;
    return { collected: total, balance };
  });
}

// ---------- market ----------
export async function listForSale(db: Db, user: SessionUser | null, plotId: number, price: number) {
  const u = requirePlayer(user);
  return tx(db, async (c) => {
    const p = (await c.query('select * from plots where id = $1 for update', [plotId])).rows[0];
    if (!p) throw E.notFound('Uchastka topilmadi');
    if (p.owner_id !== u.id) throw E.forbidden();
    const eco = await economy(c);
    const ageH = (Date.now() - new Date(u.created_at).getTime()) / 3600_000;
    if (ageH < eco.min_account_age_to_sell_hours) {
      throw E.conflict('account_too_new', `Yangi hisoblar ${Math.ceil(eco.min_account_age_to_sell_hours / 24)} kundan keyin sota oladi.`);
    }
    if ((await c.query("select 1 from listings where plot_id = $1 and status = 'active'", [plotId])).rows.length) {
      throw E.conflict('already_listed', 'Bu uchastka allaqachon sotuvda.');
    }
    const b = (await c.query('select template from buildings where plot_id = $1', [plotId])).rows[0];
    const land = landPrice(p.zone, p.location_factor, (await occupancy(c)).get(p.district_id) || 0, eco);
    const est = estimate(land, b ? b.template : null);
    const min = Math.ceil(est * eco.sale_min_ratio), max = Math.floor(est * eco.sale_max_ratio);
    if (!Number.isInteger(price) || price < min || price > max) {
      throw E.bad('price_out_of_range', `Narx ${min} – ${max} tanga oralig‘ida bo‘lishi kerak.`, { min, max, estimate: est });
    }
    await c.query('insert into listings(plot_id,seller_id,price) values ($1,$2,$3)', [plotId, u.id, price]);
    return { price, estimate: est };
  });
}
export async function unlist(db: Db, user: SessionUser | null, plotId: number) {
  const u = requirePlayer(user);
  const r = await db.query("update listings set status = 'cancelled' where plot_id = $1 and seller_id = $2 and status = 'active' returning id", [plotId, u.id]);
  if (!r.rows.length) throw E.notFound('Faol e’lon topilmadi');
  return { ok: true };
}

export async function like(db: Db, user: SessionUser | null, plotId: number) {
  const u = requirePlayer(user);
  const p = (await db.query('select owner_id from plots where id = $1', [plotId])).rows[0];
  if (!p) throw E.notFound('Uchastka topilmadi');
  if (p.owner_id === u.id) throw E.bad('own_plot', 'O‘z uchastkangizni yoqtira olmaysiz.');
  await db.query('insert into likes(user_id,plot_id) values ($1,$2) on conflict do nothing', [u.id, plotId]);
  return { likes: (await db.query('select count(*)::int n from likes where plot_id = $1', [plotId])).rows[0].n };
}

/** Invariant used by tests and the nightly check: every wallet equals the sum of its ledger. */
export async function ledgerMismatches(db: Db) {
  return (await db.query(
    `select w.user_id, w.balance, coalesce(sum(t.amount),0)::bigint as ledger from wallets w
     left join transactions t on t.user_id = w.user_id group by w.user_id, w.balance
     having w.balance <> coalesce(sum(t.amount),0)`)).rows;
}
