// Game rules that move coins or property. Every function here runs in ONE database transaction,
// locks the rows it changes (plot first, then wallets in id order), and writes the ledger.
import type { Db, Tx } from './db.js';
import { tx } from './db.js';
import { config } from './config.js';
import { E } from './errors.js';
import { ECONOMY_DEFAULTS, Economy, ZoneCode, landPrice, estimate, accrued, normalizeSpec, zonesOf, costOf, incomeOf, buildSecondsOf, isLandmark, CAR, PlateKind, normalizePlate, plateCost, randomPlateText, isHexColor } from './economy.js';
import { isCleanText } from './nickname.js';
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
  // city land around the skyscrapers (owned by the city, no building) does not push land prices up
  const r = await c.query(`select p.district_id, avg((p.status <> 'empty' and not coalesce(u.nickname_lower = 'shahar hokimligi' and b.id is null, false))::int)::float occ
                             from plots p left join users u on u.id = p.owner_id left join buildings b on b.plot_id = p.id group by p.district_id`);
  return new Map(r.rows.map((x) => [x.district_id, x.occ]));
}

// ---------- read model ----------
export interface PlotDTO {
  id: number; x: number; z: number; zone: ZoneCode; district: number;
  state: 'empty' | 'owned' | 'sale'; price: number | null;
  /** telegram = @username without @, only when the owner allows it */
  owner: { id: number; nickname: string | null; telegram: string | null } | null;
  building: { template: string; style: string; floors: number; roof: string; rotation: number; color: string; accent: string; level: number; readyAt: string } | null;
  likes: number;
}

const PLOT_SQL = `
  select p.id, p.x, p.z, p.zone, p.district_id, p.location_factor, p.status, p.owner_id, u.nickname as owner_nick,
         case when u.show_telegram then u.telegram_username end as owner_tg,
         b.template, b.style, b.floors, b.roof, b.rotation, b.color, b.accent, b.level, b.ready_at, b.status as bstatus,
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
    owner: r.owner_id ? { id: r.owner_id, nickname: r.owner_nick, telegram: r.owner_tg || null } : null,
    building: r.template && r.bstatus === 'active'
      ? { template: r.template, style: r.style, floors: r.floors, roof: r.roof, rotation: r.rotation, color: r.color, accent: r.accent, level: r.level, readyAt: r.ready_at.toISOString() }
      : null,
    likes: r.likes,
  };
}

export async function allPlots(db: Db): Promise<PlotDTO[]> {
  const [eco, occ, rows] = await Promise.all([economy(db), occupancy(db), db.query(PLOT_SQL + ' order by p.id')]);
  return rows.rows.map((r) => toDTO(r, occ, eco));
}
/** City view for the client: only plots that are not empty (empty-land prices are computed by the client
 *  from the same formula, using the occupancy per mahalla sent here). Keeps /api/city small for 13 000 plots. */
export async function cityView(db: Db) {
  const [eco, occ, rows, total] = await Promise.all([economy(db), occupancy(db), db.query(PLOT_SQL + " where p.status <> 'empty' order by p.id"), db.query('select count(*)::int n from plots')]);
  const occ2: Record<number, number> = {}; for (const [k, v] of occ) occ2[k] = v;
  return { total: total.rows[0].n as number, land: { occupancy: occ2, demandWeight: eco.demand_weight }, plots: rows.rows.map((r) => toDTO(r, occ, eco)), cars: await allCars(db) };
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
        const b = (await c.query('select * from buildings where plot_id = $1 for update', [plotId])).rows[0];
        if (b) {
          const now = new Date();
          const inc = accrued(incomeOf(b.template, b.floors), b.ready_at, b.last_collected_at, now, config.daySeconds, eco.income_cap_days);
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
  body: { template: string; rotation?: number; color?: string; accent?: string; style?: string; floors?: number; roof?: string }, key: string | null) {
  const u = requirePlayer(user);
  const spec = normalizeSpec(body);
  if ('error' in spec) throw E.bad(spec.code, spec.error);
  try {
    return await tx(db, async (c) => {
      const p = (await c.query('select * from plots where id = $1 for update', [plotId])).rows[0];
      // checked after the row lock, so a duplicate request waiting on the lock sees the first one's result
      if (await alreadyDone(c, u.id, key)) return { replayed: true };
      if (!p) throw E.notFound('Uchastka topilmadi');
      if (p.owner_id !== u.id) throw E.forbidden();
      if ((await c.query('select 1 from buildings where plot_id = $1', [plotId])).rows.length) throw E.conflict('already_built', 'Bu uchastkada bino bor.');
      const tpl = (await c.query('select * from building_templates where code = $1 and active', [spec.template])).rows[0];
      if (!tpl) throw E.bad('bad_template', 'Bu bino turi hozir mavjud emas.');
      if (!zonesOf(spec.template).includes(p.zone)) throw E.bad('wrong_zone', `${tpl.name} bu zonada qurilmaydi.`);
      if (isLandmark(spec.template) && (await c.query('select 1 from buildings where template = $1', [spec.template])).rows.length) {
        throw E.conflict('landmark_taken', `${tpl.name} nusxasi shaharda allaqachon bor — har biridan bittadan.`);
      }
      const cost = costOf(spec.template, spec.floors);
      const bal = await lockWallets(c, [u.id]);
      const have = bal.get(u.id) ?? 0;
      if (have < cost) throw E.funds(cost - have);
      await move(c, u.id, -cost, 'build', 'plot', plotId, key);
      const readyAt = new Date(Date.now() + buildSecondsOf(spec.template, spec.floors) * 1000);
      await c.query(
        `insert into buildings(plot_id,template,style,floors,roof,rotation,color,accent,ready_at,last_collected_at)
         values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$9)`,
        [plotId, spec.template, spec.style, spec.floors, spec.roof, spec.rotation, spec.color, spec.accent, readyAt]);
      return { replayed: false, cost, readyAt: readyAt.toISOString() };
    });
  } catch (e: any) {
    if (isUnique(e)) return { replayed: true };
    if (e && e.code === '23505' && String(e.constraint || '').includes('landmark')) throw E.conflict('landmark_taken', 'Bu osmono‘par nusxasi allaqachon qurilgan.');
    throw e;
  }
}

// ---------- income ----------
async function pendingRows(c: Db | Tx, userId: number, lock: boolean) {
  return (await c.query(
    `select b.id, b.template, b.floors, b.ready_at, b.last_collected_at from buildings b
     join plots p on p.id = b.plot_id
     where p.owner_id = $1 and b.status = 'active' ${lock ? 'for update of b' : ''}`, [userId])).rows
    .map((b) => ({ ...b, income_per_day: incomeOf(b.template, b.floors) }));
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
      throw E.conflict('account_too_new', `Yangi hisob ${Math.max(1, Math.ceil((eco.min_account_age_to_sell_hours - ageH) * 60))} daqiqadan keyin sota oladi.`);
    }
    if ((await c.query("select 1 from listings where plot_id = $1 and status = 'active'", [plotId])).rows.length) {
      throw E.conflict('already_listed', 'Bu uchastka allaqachon sotuvda.');
    }
    const b = (await c.query('select template, floors from buildings where plot_id = $1', [plotId])).rows[0];
    const land = landPrice(p.zone, p.location_factor, (await occupancy(c)).get(p.district_id) || 0, eco);
    const est = estimate(land, b ? costOf(b.template, b.floors) : 0);
    const min = Math.ceil(est * eco.sale_min_ratio), max = Math.floor(est * eco.sale_max_ratio);
    if (!Number.isInteger(price) || price < min || price > max) {
      throw E.bad('price_out_of_range', `Narx ${min} – ${max} tanga oralig‘ida bo‘lishi kerak.`, { min, max, estimate: est });
    }
    await c.query('insert into listings(plot_id,seller_id,price) values ($1,$2,$3)', [plotId, u.id, price]);
    return { price, estimate: est };
  });
}
/** What the owner may ask for a plot: the price corridor around the estimate, and whether they can sell yet. */
export async function saleQuote(db: Db, user: SessionUser | null, plotId: number) {
  const u = requirePlayer(user);
  const p = (await db.query('select * from plots where id = $1', [plotId])).rows[0];
  if (!p) throw E.notFound('Uchastka topilmadi');
  if (p.owner_id !== u.id) throw E.forbidden();
  const eco = await economy(db);
  const b = (await db.query('select template, floors from buildings where plot_id = $1', [plotId])).rows[0];
  const land = landPrice(p.zone, p.location_factor, (await occupancy(db)).get(p.district_id) || 0, eco);
  const est = estimate(land, b ? costOf(b.template, b.floors) : 0);
  const ageH = (Date.now() - new Date(u.created_at).getTime()) / 3600_000;
  const waitMin = Math.max(0, Math.ceil((eco.min_account_age_to_sell_hours - ageH) * 60));
  const listed = (await db.query("select price from listings where plot_id = $1 and status = 'active'", [plotId])).rows[0];
  return { estimate: est, min: Math.ceil(est * eco.sale_min_ratio), max: Math.floor(est * eco.sale_max_ratio),
           fee: eco.sale_fee, canSell: waitMin === 0, waitMinutes: waitMin, listedPrice: listed ? Number(listed.price) : null };
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

// ---------- cars ----------
export interface CarDTO { owner: { id: number; nickname: string | null; telegram: string | null }; model: string; color: string; plate: { region: string; text: string; kind: string } }
const CAR_SQL = `select c.*, u.nickname, case when u.show_telegram then u.telegram_username end as tg from cars c join users u on u.id = c.owner_id`;
const carDTO = (r: any): CarDTO => ({ owner: { id: Number(r.owner_id), nickname: r.nickname, telegram: r.tg || null }, model: r.model, color: r.color, plate: { region: r.plate_region, text: r.plate_text, kind: r.plate_kind } });
export async function allCars(db: Db | Tx): Promise<CarDTO[]> {
  return (await db.query(CAR_SQL + " where u.status = 'active' order by c.id")).rows.map(carDTO);
}
export async function carOf(db: Db | Tx, userId: number): Promise<CarDTO | null> {
  const r = (await db.query(CAR_SQL + ' where c.owner_id = $1', [userId])).rows[0];
  return r ? carDTO(r) : null;
}
export async function plateFree(db: Db | Tx, region: string, text: string, exceptOwner = 0) {
  return !(await db.query('select 1 from cars where plate_region = $1 and plate_text = $2 and owner_id <> $3', [region, text, exceptOwner])).rows.length;
}
async function pickRandomPlate(c: Tx, region: string) {
  for (let i = 0; i < 50; i++){ const t = randomPlateText(); if (await plateFree(c, region, t)) return t; }
  throw E.conflict('plate_taken', 'Bo‘sh raqam topilmadi, qayta urinib ko‘ring.');
}
function checkPlate(p: { kind: PlateKind; region: string; text?: string }) {
  const n = normalizePlate(p.kind, p.region, p.text);
  if ('error' in n) throw E.bad(n.code, n.error);
  if (n.kind === 'custom' && n.text && !isCleanText(n.text)) throw E.bad('plate_blocked', 'Bu yozuvni qo‘yib bo‘lmaydi.');
  return n;
}
const plateTaken = (e: any) => e && e.code === '23505' && String(e.constraint || '').includes('plate');

export async function buyCar(db: Db, user: SessionUser | null, body: { model?: string; color: string; plate: { kind: PlateKind; region: string; text?: string } }, key: string | null) {
  const u = requirePlayer(user);
  const model = body.model || 'tracker', M = CAR.models[model];
  if (!M) throw E.bad('bad_model', 'Bunday mashina bozorda yo‘q.');
  const color = String(body.color || '').toLowerCase();
  if (!isHexColor(color)) throw E.bad('bad_color', 'Rang noto‘g‘ri.');
  const n = checkPlate(body.plate);
  const cost = M.price + plateCost(body.plate.kind);
  try {
    return await tx(db, async (c) => {
      const bal = await lockWallets(c, [u.id]);
      if (await alreadyDone(c, u.id, key)) return { replayed: true, car: await carOf(c, u.id) };
      if ((await c.query('select 1 from cars where owner_id = $1', [u.id])).rows.length) throw E.conflict('already_have_car', 'Sizda mashina bor. Rangini yoki raqamini o‘zgartirishingiz mumkin.');
      const text = n.text ?? await pickRandomPlate(c, n.region);
      if (!(await plateFree(c, n.region, text))) throw E.conflict('plate_taken', 'Bu raqam band. Boshqasini tanlang.');
      const have = bal.get(u.id) ?? 0;
      if (have < cost) throw E.funds(cost - have);
      const id = (await c.query('insert into cars(owner_id,model,color,plate_region,plate_text,plate_kind) values ($1,$2,$3,$4,$5,$6) returning id', [u.id, model, color, n.region, text, n.kind])).rows[0].id;
      const balance = await move(c, u.id, -cost, 'car_buy', 'car', Number(id), key);
      return { replayed: false, cost, balance, car: await carOf(c, u.id) };
    });
  } catch (e) {
    if (isUnique(e)) return { replayed: true, car: await carOf(db, u.id) };
    if (plateTaken(e)) throw E.conflict('plate_taken', 'Bu raqam band. Boshqasini tanlang.');
    if (e && (e as any).code === '23505') throw E.conflict('already_have_car', 'Sizda mashina bor.');
    throw e;
  }
}
export async function updateCar(db: Db, user: SessionUser | null, body: { color?: string; plate?: { kind: PlateKind; region: string; text?: string } }, key: string | null) {
  const u = requirePlayer(user);
  const color = body.color != null ? String(body.color).toLowerCase() : null;
  if (color != null && !isHexColor(color)) throw E.bad('bad_color', 'Rang noto‘g‘ri.');
  const n = body.plate ? checkPlate(body.plate) : null;
  try {
    return await tx(db, async (c) => {
      const bal = await lockWallets(c, [u.id]);
      if (await alreadyDone(c, u.id, key)) return { replayed: true, car: await carOf(c, u.id) };
      const car = (await c.query('select * from cars where owner_id = $1 for update', [u.id])).rows[0];
      if (!car) throw E.notFound('Sizda hali mashina yo‘q');
      let cost = 0;
      const newColor = color && color !== car.color ? color : null;
      if (newColor) cost += CAR.repaint;
      let plate: { region: string; text: string; kind: string } | null = null;
      if (n && body.plate){
        const text = n.text ?? await pickRandomPlate(c, n.region);
        if (!(n.region === car.plate_region && text === car.plate_text)){
          if (!(await plateFree(c, n.region, text, u.id))) throw E.conflict('plate_taken', 'Bu raqam band. Boshqasini tanlang.');
          plate = { region: n.region, text, kind: n.kind };
          cost += body.plate.kind === 'random' ? CAR.plateChangeRandom : plateCost(body.plate.kind);
        }
      }
      if (!newColor && !plate) return { replayed: false, cost: 0, car: await carOf(c, u.id) };
      const have = bal.get(u.id) ?? 0;
      if (have < cost) throw E.funds(cost - have);
      await c.query(`update cars set color = coalesce($2, color), plate_region = coalesce($3, plate_region), plate_text = coalesce($4, plate_text),
                     plate_kind = coalesce($5, plate_kind), updated_at = now() where id = $1`, [car.id, newColor, plate?.region ?? null, plate?.text ?? null, plate?.kind ?? null]);
      const balance = cost > 0 ? await move(c, u.id, -cost, 'car_change', 'car', Number(car.id), key) : bal.get(u.id);
      return { replayed: false, cost, balance, car: await carOf(c, u.id) };
    });
  } catch (e) {
    if (isUnique(e)) return { replayed: true, car: await carOf(db, u.id) };
    if (plateTaken(e)) throw E.conflict('plate_taken', 'Bu raqam band. Boshqasini tanlang.');
    throw e;
  }
}
/** The founder's white Tracker (90 Y 095 AB) stays with shohruh.97, granted once, free. */
export async function grantFounderCar(db: Db) {
  await db.query(`insert into cars(owner_id,color,plate_region,plate_text,plate_kind)
    select id, '#f2f3f1', '90', 'Y095AB', 'standard' from users
    where (nickname_lower = 'shohruh.97' or lower(telegram_username) = 'shohruh.97') and status = 'active'
    order by (nickname_lower = 'shohruh.97') desc limit 1
    on conflict do nothing`);
}

/**
 * One-off gift asked for by the owner of the game: the house that the account "Shaxzoda" built goes, free, to the
 * same person's account with the nickname shaxzamee_5400. Only plots with a building move; any open listing on them
 * is cancelled; no coins change hands. Idempotent: once "Shaxzoda" owns no building, it does nothing. Runs at start
 * and when the nickname shaxzamee_5400 is taken (the account may not exist yet). Returns the plot ids moved.
 */
let GIFT_LOG: ((m: string) => void) | null = null;
export function setGiftLog(f: ((m: string) => void) | null) { GIFT_LOG = f; }
export async function giftShaxzodaHouse(db: Db): Promise<number[]> {
  return tx(db, async (c) => {
    // the giving account shows as "Shaxzoda" (its nickname, or its Telegram @username); the receiving one is
    // shaxzamee_5400 / shaxzomee_5400 (both spellings were given), as a nickname or a Telegram @username
    const from = (await c.query(
      "select id from users where nickname_lower = 'shaxzoda' or lower(telegram_username) = 'shaxzoda' order by (nickname_lower = 'shaxzoda') desc limit 1")).rows[0]?.id;
    const to = (await c.query(
      `select id from users where status = 'active' and (nickname_lower in ('shaxzamee_5400','shaxzomee_5400') or lower(telegram_username) in ('shaxzamee_5400','shaxzomee_5400'))
        order by (nickname_lower in ('shaxzamee_5400','shaxzomee_5400')) desc, id limit 1`)).rows[0]?.id;
    if (GIFT_LOG) GIFT_LOG(`gift check: Shaxzoda=${from ?? 'not found'}, shaxzamee/shaxzomee_5400=${to ?? 'not found'}`);
    if (!from || !to || from === to) return [];
    const ids = (await c.query(
      'select p.id from plots p join buildings b on b.plot_id = p.id where p.owner_id = $1 for update of p', [from])).rows.map((r) => Number(r.id));
    for (const id of ids) {
      await c.query("update listings set status = 'cancelled' where plot_id = $1 and status = 'active'", [id]);
      await c.query("update plots set owner_id = $2, status = 'owned', purchased_at = now() where id = $1", [id, to]);
    }
    return ids;
  });
}
