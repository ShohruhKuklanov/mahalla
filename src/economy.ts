// City layout, building templates and price rules.
// The layout MUST stay identical to the 3D client (web/index.html) so plot ids match.

export const LAYOUT = { P: 10, PB: 4, SW: 2.5, RD: 11, NBX: 10, NBZ: 8 };
const BLK = LAYOUT.PB * LAYOUT.P + 2 * LAYOUT.SW;
const PITCH = BLK + LAYOUT.RD;
const W = LAYOUT.NBX * PITCH - LAYOUT.RD, D = LAYOUT.NBZ * PITCH - LAYOUT.RD;
const X0 = -W / 2, Z0 = -D / 2;
const isPark = (bx: number, bz: number) => (bx === 4 || bx === 5) && (bz === 3 || bz === 4);

export type ZoneCode = 'res' | 'com' | 'cen';
export const DISTRICTS = ['Navro‘z mahallasi', 'Ipak yo‘li mahallasi', 'Bog‘ishamol mahallasi'];
export const ZONES: Record<ZoneCode, { name: string; base: number }> = {
  res: { name: 'Turar-joy', base: 4000 },
  com: { name: 'Savdo', base: 6000 },
  cen: { name: 'Markaz', base: 12000 },
};

export interface PlotSeed { id: number; x: number; z: number; zone: ZoneCode; district: number; loc: number }

export function cityPlots(): PlotSeed[] {
  const out: PlotSeed[] = [];
  for (let bx = 0; bx < LAYOUT.NBX; bx++) for (let bz = 0; bz < LAYOUT.NBZ; bz++) {
    if (isPark(bx, bz)) continue;
    const d = Math.max(Math.abs(bx - 4.5), Math.abs(bz - 3.5));
    const zone: ZoneCode = d <= 1.5 ? 'cen' : d <= 2.5 ? 'com' : 'res';
    const district = bx <= 2 ? 0 : bx <= 6 ? 1 : 2;
    for (let i = 0; i < LAYOUT.PB; i++) for (let j = 0; j < LAYOUT.PB; j++) {
      const x = X0 + bx * PITCH + LAYOUT.SW + LAYOUT.P * i + LAYOUT.P / 2;
      const z = Z0 + bz * PITCH + LAYOUT.SW + LAYOUT.P * j + LAYOUT.P / 2;
      const corner = (i === 0 || i === LAYOUT.PB - 1) && (j === 0 || j === LAYOUT.PB - 1);
      const loc = (d <= 1.5 ? 1.3 : 1) * (corner ? 1.1 : 1);
      out.push({ id: out.length, x, z, zone, district, loc: Math.round(loc * 100) / 100 });
    }
  }
  return out;
}

export const TEMPLATES: Record<string, { name: string; zones: ZoneCode[]; cost: number; buildSeconds: number; income: number }> = {
  house:  { name: 'Kichik uy',       zones: ['res'],               cost: 2000,  buildSeconds: 30,  income: 150 },
  villa:  { name: 'Ikki qavatli uy', zones: ['res'],               cost: 4000,  buildSeconds: 60,  income: 260 },
  flat:   { name: 'Ko‘p qavatli uy', zones: ['res', 'com'],        cost: 6500,  buildSeconds: 120, income: 420 },
  shop:   { name: 'Do‘kon',          zones: ['com', 'cen'],        cost: 3000,  buildSeconds: 45,  income: 400 },
  cafe:   { name: 'Choyxona',        zones: ['com', 'cen', 'res'], cost: 3500,  buildSeconds: 60,  income: 480 },
  office: { name: 'Ofis',            zones: ['com', 'cen'],        cost: 7000,  buildSeconds: 180, income: 650 },
  tower:  { name: 'Biznes markaz',   zones: ['cen'],               cost: 15000, buildSeconds: 300, income: 1200 },
};

/** Defaults; overridable at runtime through the economy_config table (admin), no deploy needed. */
export const ECONOMY_DEFAULTS = {
  start_coins: 10000,
  plot_limit: 3,
  sale_fee: 0.05,
  sale_min_ratio: 0.5,
  sale_max_ratio: 3.0,
  min_account_age_to_sell_hours: 24 * 7,
  income_cap_days: 1,
  demand_weight: 0.5,
  demolish_refund: 0.5,
};
export type Economy = typeof ECONOMY_DEFAULTS;

export const COLORS = {
  wall: ['#f2e6d0', '#e8d4ae', '#f6f3ec', '#e3b49c', '#cfe0ea', '#d6e6d4', '#efd9c8'],
  glass: ['#dfe9f2', '#cfe3e6', '#e9e4da', '#d5dcef'],
  accent: ['#2a9d8f', '#3a6ea5', '#c0503b', '#e08a2c', '#3f9a5a', '#7b5ea7'],
};

const round100 = (n: number) => Math.round(n / 100) * 100;

/** Land price = zone base × location × (1 + weight × district occupancy). */
export function landPrice(zone: ZoneCode, loc: number, districtOccupancy: number, eco: Economy) {
  return round100(ZONES[zone].base * loc * (1 + eco.demand_weight * districtOccupancy));
}

/** System estimate of a plot with its building; resale price must stay within a corridor around it. */
export function estimate(land: number, template: string | null) {
  return round100(land * 1.25 + (template ? TEMPLATES[template].cost * 0.9 : 0));
}

/** Income accrued since `from`, capped, for a building that became ready at `readyAt`. */
export function accrued(incomePerDay: number, readyAt: Date, from: Date, now: Date, daySeconds: number, capDays: number) {
  const start = Math.max(readyAt.getTime(), from.getTime());
  if (now.getTime() <= start) return 0;
  const secs = Math.min((now.getTime() - start) / 1000, capDays * daySeconds);
  return Math.floor((incomePerDay * secs) / daySeconds);
}
