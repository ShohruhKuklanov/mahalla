// City layout, building templates and price rules.
// The layout MUST stay identical to the 3D client (web/index.html) so plot ids match.

// The city: a 32 × 26 grid of blocks. The original 10 × 8 centre keeps plot ids 0–1215 (layout v1);
// the ring around it (v2, "10× city") is appended after, so existing owners keep their plots.
export const LAYOUT = { P: 10, PB: 4, SW: 2.5, RD: 11, GX: 32, GZ: 26, OX: 11, OZ: 9, CX: 10, CZ: 8 };
const BLK = LAYOUT.PB * LAYOUT.P + 2 * LAYOUT.SW;
const PITCH = BLK + LAYOUT.RD;
const W = LAYOUT.GX * PITCH - LAYOUT.RD, D = LAYOUT.GZ * PITCH - LAYOUT.RD;
const X0 = -W / 2, Z0 = -D / 2;
const inCore = (gx: number, gz: number) => gx >= LAYOUT.OX && gx < LAYOUT.OX + LAYOUT.CX && gz >= LAYOUT.OZ && gz < LAYOUT.OZ + LAYOUT.CZ;
/** Park blocks: the central park and a small square park every 6 blocks outside the centre. */
export const isPark = (gx: number, gz: number) =>
  ((gx === 15 || gx === 16) && (gz === 12 || gz === 13)) || (!inCore(gx, gz) && gx % 6 === 5 && gz % 6 === 4);

export type ZoneCode = 'res' | 'com' | 'cen';
export const DISTRICTS = [
  'Navro‘z mahallasi', 'Ipak yo‘li mahallasi', 'Bog‘ishamol mahallasi',
  // outer ring: 4 × 3 sectors, north (airport side) to south (sea side)
  'Yunusobod mahallasi', 'Bodomzor mahallasi', 'Parvoz mahallasi', 'Qoraqamish mahallasi',
  'Chilonzor mahallasi', 'Olmazor mahallasi', 'Mirobod mahallasi', 'Sebzor mahallasi',
  'Beshyog‘och mahallasi', 'Dengizbo‘yi mahallasi', 'Bandargoh mahallasi', 'Shayxontohur mahallasi',
];
export const ZONES: Record<ZoneCode, { name: string; base: number }> = {
  res: { name: 'Turar-joy', base: 4000 },
  com: { name: 'Savdo', base: 6000 },
  cen: { name: 'Markaz', base: 12000 },
};

export interface PlotSeed { id: number; x: number; z: number; zone: ZoneCode; district: number; loc: number }
interface BlockInfo { zone: ZoneCode; district: number; locK: number }

/** Zone, mahalla and price factor of a block (shared rule with web/index.html). */
export function blockInfo(gx: number, gz: number): BlockInfo {
  if (inCore(gx, gz)) {
    const bx = gx - LAYOUT.OX, bz = gz - LAYOUT.OZ;
    const d = Math.max(Math.abs(bx - 4.5), Math.abs(bz - 3.5));
    return { zone: d <= 1.5 ? 'cen' : d <= 2.5 ? 'com' : 'res', district: bx <= 2 ? 0 : bx <= 6 ? 1 : 2, locK: d <= 1.5 ? 1.3 : 1 };
  }
  const d = Math.max(Math.abs(gx - 15.5), Math.abs(gz - 12.5));
  const seaside = gz >= LAYOUT.GZ - 2;
  const zone: ZoneCode = (seaside && gx >= 12 && gx <= 19) ? 'cen' : (gx % 5 === 2 || gz % 5 === 2 || seaside) ? 'com' : 'res';
  const district = 3 + Math.min(2, Math.floor(gz / 9)) * 4 + Math.min(3, Math.floor(gx / 8));
  const locK = Math.max(0.7, 1.1 - 0.035 * d) * (seaside ? 1.25 : 1);
  return { zone, district, locK };
}

function blockPlots(gx: number, gz: number, out: PlotSeed[]) {
  const b = blockInfo(gx, gz);
  for (let i = 0; i < LAYOUT.PB; i++) for (let j = 0; j < LAYOUT.PB; j++) {
    const x = X0 + gx * PITCH + LAYOUT.SW + LAYOUT.P * i + LAYOUT.P / 2;
    const z = Z0 + gz * PITCH + LAYOUT.SW + LAYOUT.P * j + LAYOUT.P / 2;
    const corner = (i === 0 || i === LAYOUT.PB - 1) && (j === 0 || j === LAYOUT.PB - 1);
    const loc = b.locK * (corner ? 1.1 : 1);
    out.push({ id: out.length, x, z, zone: b.zone, district: b.district, loc: Math.round(loc * 100) / 100 });
  }
}

export function cityPlots(): PlotSeed[] {
  const out: PlotSeed[] = [];
  // v1 centre first, in its original order (ids 0–1215 unchanged)
  for (let bx = 0; bx < LAYOUT.CX; bx++) for (let bz = 0; bz < LAYOUT.CZ; bz++) {
    const gx = bx + LAYOUT.OX, gz = bz + LAYOUT.OZ;
    if (!isPark(gx, gz)) blockPlots(gx, gz, out);
  }
  for (let gx = 0; gx < LAYOUT.GX; gx++) for (let gz = 0; gz < LAYOUT.GZ; gz++) {
    if (!inCore(gx, gz) && !isPark(gx, gz)) blockPlots(gx, gz, out);
  }
  return out;
}

// ---------- building catalog ----------
// Single source of truth: the <script id="catalog"> block in web/index.html (the 3D client reads the same block).
import fs from 'node:fs';
import { rootPath } from './db.js';

export interface TypeDef { name: string; zones: ZoneCode[]; floors: [number, number]; w: number; d: number; cost: [number, number]; income: [number, number]; build: [number, number]; roofs: string[] }
export interface LandmarkDef { name: string; city: string; realHeight: number; cost: number; income: number; build: number; spot?: [number, number] }
export interface Catalog {
  floorHeight: number;
  styles: Record<string, { name: string; walls: string[] }>;
  accents: string[];
  roofs: Record<string, string>;
  types: Record<string, TypeDef>;
  landmarkScale: number;
  landmarks: Record<string, LandmarkDef>;
}
function loadCatalog(): Catalog {
  const html = fs.readFileSync(rootPath('web') + '/index.html', 'utf8');
  const m = html.match(/<script id="catalog" type="application\/json">([\s\S]*?)<\/script>/);
  if (!m) throw new Error('web/index.html: catalog block not found');
  return JSON.parse(m[1]);
}
export const CATALOG: Catalog = loadCatalog();
export const isLandmark = (t: string) => Object.prototype.hasOwnProperty.call(CATALOG.landmarks, t);

export interface BuildSpec { template: string; style: string; floors: number; roof: string; color: string; accent: string; rotation: number }

/** Fill defaults and validate a build request; throws a message (Uzbek) on the first problem. Zone is checked by the caller. */
export function normalizeSpec(b: Partial<BuildSpec> & { template: string }): BuildSpec | { error: string; code: string } {
  const rotation = Number.isInteger(b.rotation) && b.rotation! >= 0 && b.rotation! <= 3 ? b.rotation! : 0;
  if (isLandmark(b.template)) {
    // landmark copies have a fixed design; colour fields are kept for the record
    return { template: b.template, style: 'hitech', floors: 1, roof: 'none', color: b.color || '#cfe3ee', accent: b.accent || CATALOG.accents[0], rotation };
  }
  const t = CATALOG.types[b.template];
  if (!t) return { code: 'bad_template', error: 'Bunday bino turi yo‘q.' };
  const style = b.style ?? 'modern';
  if (!CATALOG.styles[style]) return { code: 'bad_style', error: 'Bunday uslub yo‘q.' };
  const floors = b.floors ?? t.floors[0];
  if (!Number.isInteger(floors) || floors < t.floors[0] || floors > t.floors[1]) {
    return { code: 'bad_floors', error: `${t.name}: qavatlar soni ${t.floors[0]}–${t.floors[1]} bo‘lishi kerak.` };
  }
  const roof = b.roof ?? t.roofs[0];
  if (!t.roofs.includes(roof)) return { code: 'bad_roof', error: `${t.name} uchun bu tom turi mavjud emas.` };
  const color = b.color ?? CATALOG.styles[style].walls[0], accent = b.accent ?? CATALOG.accents[0];
  if (!CATALOG.styles[style].walls.includes(color) || !CATALOG.accents.includes(accent)) return { code: 'bad_color', error: 'Bu rang ro‘yxatda yo‘q.' };
  return { template: b.template, style, floors, roof, color, accent, rotation };
}
export function zonesOf(template: string): ZoneCode[] { return isLandmark(template) ? ['cen'] : CATALOG.types[template]?.zones ?? []; }
export function costOf(template: string, floors: number) {
  if (isLandmark(template)) return CATALOG.landmarks[template].cost;
  const t = CATALOG.types[template]; return t.cost[0] + t.cost[1] * (floors - t.floors[0]);
}
export function incomeOf(template: string, floors: number) {
  if (isLandmark(template)) return CATALOG.landmarks[template].income;
  const t = CATALOG.types[template]; if (!t) return 0; return t.income[0] + t.income[1] * (Math.max(floors, t.floors[0]) - t.floors[0]);
}
export function buildSecondsOf(template: string, floors: number) {
  if (isLandmark(template)) return CATALOG.landmarks[template].build;
  const t = CATALOG.types[template]; return t.build[0] + t.build[1] * (floors - t.floors[0]);
}

/** Defaults; overridable at runtime through the economy_config table (admin), no deploy needed. */
export const ECONOMY_DEFAULTS = {
  start_coins: 10000,
  plot_limit: 3,
  sale_fee: 0.05,
  sale_min_ratio: 0.5,
  sale_max_ratio: 3.0,
  min_account_age_to_sell_hours: 1,               // a brand-new account waits an hour before it can sell (anti coin-farming)
  income_cap_days: 1,
  demand_weight: 0.5,
  demolish_refund: 0.5,
};
export type Economy = typeof ECONOMY_DEFAULTS;


const round100 = (n: number) => Math.round(n / 100) * 100;

/** Land price = zone base × location × (1 + weight × district occupancy). */
export function landPrice(zone: ZoneCode, loc: number, districtOccupancy: number, eco: Economy) {
  return round100(ZONES[zone].base * loc * (1 + eco.demand_weight * districtOccupancy));
}

/** System estimate of a plot with its building; resale price must stay within a corridor around it. */
export function estimate(land: number, buildingCost: number) {
  return round100(land * 1.25 + buildingCost * 0.9);
}

/** Income accrued since `from`, capped, for a building that became ready at `readyAt`. */
export function accrued(incomePerDay: number, readyAt: Date, from: Date, now: Date, daySeconds: number, capDays: number) {
  const start = Math.max(readyAt.getTime(), from.getTime());
  if (now.getTime() <= start) return 0;
  const secs = Math.min((now.getTime() - start) / 1000, capDays * daySeconds);
  return Math.floor((incomePerDay * secs) / daySeconds);
}

// ---------- cars: one model (Chevrolet Tracker), any colour, Uzbek plates ----------
export const CAR = {
  /** the showroom: add a model here (and its 3D model in the client's CAR_MODELS) to sell it */
  models: { tracker: { name: 'Chevrolet Tracker', price: 5000 }, coupe: { name: 'Susambil GT', price: 15000 }, gtpro: { name: 'Susambil GT Pro', price: 25000 }, roadster: { name: 'Susambil Shamol', price: 30000 }, kometa: { name: 'Susambil Kometa', price: 40000 } } as Record<string, { name: string; price: number }>,
  price: 5000,          // default model's price (older clients)
  repaint: 300,         // a new colour later
  plate: { random: 0, standard: 500, custom: 2000 },
  plateChangeRandom: 100,
  regions: ['01', '10', '20', '25', '30', '40', '50', '60', '70', '75', '80', '85', '90', '95'],
};
export type PlateKind = 'random' | 'standard' | 'custom';
const STD_PLATE = /^[A-Z][0-9]{3}[A-Z]{2}$/;          // personal cars: Y 095 AB
export function normalizePlate(kind: PlateKind, region: string, text: string | undefined):
  { region: string; text: string | null; kind: 'standard' | 'custom' } | { code: string; error: string } {
  if (!CAR.regions.includes(region)) return { code: 'bad_region', error: 'Viloyat kodi noto‘g‘ri.' };
  if (kind === 'random') return { region, text: null, kind: 'standard' };
  const t = String(text ?? '').toUpperCase().replace(/[\s-]/g, '');
  if (kind === 'standard'){
    if (!STD_PLATE.test(t)) return { code: 'bad_plate', error: 'Raqam shakli: harf, 3 ta raqam, 2 ta harf (masalan, Y 095 AB).' };
    return { region, text: t, kind: 'standard' };
  }
  if (!/^[A-Z0-9]{1,8}$/.test(t)) return { code: 'bad_plate', error: 'Yozuvda 1–8 ta lotin harfi yoki raqam bo‘lsin.' };
  if (!/[A-Z]/.test(t) && t.length < 3) return { code: 'bad_plate', error: 'Yozuv juda qisqa.' };
  return { region, text: t, kind: 'custom' };
}
export const plateCost = (kind: PlateKind) => CAR.plate[kind];
export function randomPlateText(rnd: () => number = Math.random) {
  const L = 'ABCDEFGHIJKLMNOPQRSTUVXYZ', l = () => L[Math.floor(rnd() * L.length)];
  return l() + String(Math.floor(rnd() * 1000)).padStart(3, '0') + l() + l();
}
export const isHexColor = (c: string) => /^#[0-9a-f]{6}$/.test(c);
