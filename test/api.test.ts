// End-to-end tests against a real (embedded) PostgreSQL.
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { createPool, migrate, Db } from '../src/db.js';
import { seed, landmarkBlocks } from '../src/seed.js';
import { buildApp } from '../src/server.js';
import { ledgerMismatches, clearEconomyCache, allPlots } from '../src/game.js';
import { config } from '../src/config.js';
import crypto from 'node:crypto';

let db: Db, app: Awaited<ReturnType<typeof buildApp>>;

// test/run.ts starts PostgreSQL in a parent process and passes TEST_DATABASE_URL (npm test).
before(async () => {
  const url = process.env.TEST_DATABASE_URL;
  if (!url) throw new Error('Run with `npm test` (test/run.ts provides the database).');
  db = createPool(url);
  await migrate(db);
  await seed(db, { demo: true });
  app = await buildApp(db, { rateLimit: false });
});
after(async () => { await app?.close(); await db?.end(); });

/** A logged-in player with a nickname. */
async function player(name: string, nick = name) {
  const r = await app.inject({ method: 'POST', url: '/api/auth/dev', payload: { name } });
  assert.equal(r.statusCode, 200, r.body);
  const cookie = String(r.headers['set-cookie']).split(';')[0];
  const call = (method: any, url: string, payload?: any, headers: Record<string, string> = {}) =>
    app.inject({ method, url, payload, headers: { cookie, ...headers } });
  if (nick) {
    const n = await call('POST', '/api/me/nickname', { nickname: nick, confirm16: true });
    assert.equal(n.statusCode, 200, n.body);
  }
  return { call, me: async () => (await call('GET', '/api/me')).json() };
}
const city = async () => (await app.inject({ method: 'GET', url: '/api/city' })).json();
const everyPlot = async () => JSON.parse(JSON.stringify(await allPlots(db))); // all 12 992, empty ones included
async function emptyPlot(zone: string, skip = 0) {
  return (await everyPlot()).filter((p: any) => p.state === 'empty' && p.zone === zone)[skip];
}

test('new player gets 10 000 coins and must pick a nickname first', async () => {
  const a = await player('ali', '');
  const me = await a.me();
  assert.equal(me.balance, 10000);
  assert.equal(me.nickname, null);
  const p = await emptyPlot('res');
  const r = await a.call('POST', `/api/plots/${p.id}/buy`);
  assert.equal(r.statusCode, 428);
  assert.equal(r.json().error, 'nickname_required');
});

test('nickname rules: format, blocked words, taken → suggestions', async () => {
  const a = await player('nick1', '');
  assert.equal((await a.call('POST', '/api/me/nickname', { nickname: 'ab', confirm16: true })).json().error, 'nickname_format');
  assert.equal((await a.call('POST', '/api/me/nickname', { nickname: 'admin_uz', confirm16: true })).json().error, 'nickname_reserved');
  assert.equal((await a.call('POST', '/api/me/nickname', { nickname: 'Ahm0q', confirm16: true })).json().error, 'nickname_blocked');
  const taken = await a.call('POST', '/api/me/nickname', { nickname: 'Malika', confirm16: true }); // demo neighbour
  assert.equal(taken.statusCode, 409);
  assert.equal(taken.json().suggestions.length, 3);
  assert.equal((await a.call('POST', '/api/me/nickname', { nickname: 'Shohrux', confirm16: true })).statusCode, 200);
});

test('buying an empty plot charges the server-side price', async () => {
  const a = await player('buyer1');
  const p = await emptyPlot('res');
  const r = await a.call('POST', `/api/plots/${p.id}/buy`);
  assert.equal(r.statusCode, 200, r.body);
  assert.equal(r.json().plot.owner.nickname, 'buyer1');
  const me = await a.me();
  assert.equal(me.balance, 10000 - p.price);
  assert.deepEqual(me.plots, [p.id]);
});

test('20 players race for the same plot: exactly one wins, nobody loses coins', async () => {
  const players = await Promise.all(Array.from({ length: 20 }, (_, i) => player(`racer${i}`)));
  const p = await emptyPlot('res', 3);
  const res = await Promise.all(players.map((pl) => pl.call('POST', `/api/plots/${p.id}/buy`)));
  const ok = res.filter((r) => r.statusCode === 200);
  assert.equal(ok.length, 1, 'exactly one buyer');
  assert.ok(res.filter((r) => r.statusCode !== 200).every((r) => r.json().error === 'plot_taken'));
  const balances = await Promise.all(players.map((pl) => pl.me().then((m) => m.balance)));
  assert.equal(balances.filter((b) => b === 10000).length, 19);
  assert.deepEqual(await ledgerMismatches(db), []);
});

test('the same request sent twice (double tap) charges once', async () => {
  const a = await player('doubletap');
  const p = await emptyPlot('res', 5);
  const h = { 'idempotency-key': 'buy-' + p.id + '-doubletap' };
  const [r1, r2] = await Promise.all([a.call('POST', `/api/plots/${p.id}/buy`, undefined, h), a.call('POST', `/api/plots/${p.id}/buy`, undefined, h)]);
  assert.equal(r1.statusCode, 200); assert.equal(r2.statusCode, 200);
  assert.equal((await a.me()).balance, 10000 - p.price);
  assert.deepEqual(await ledgerMismatches(db), []);
});

test('plot limit and insufficient funds', async () => {
  const a = await player('rich');
  await db.query("update wallets set balance = balance + 100000 where user_id = (select id from users where nickname='rich')");
  await db.query("insert into transactions(user_id,amount,type,balance_after) select id, 100000, 'admin_adjust', 110000 from users where nickname='rich'");
  for (let i = 0; i < 3; i++) {
    const p = await emptyPlot('res', 10 + i);
    assert.equal((await a.call('POST', `/api/plots/${p.id}/buy`)).statusCode, 200);
  }
  const p4 = await emptyPlot('res', 20);
  const r = await a.call('POST', `/api/plots/${p4.id}/buy`);
  assert.equal(r.json().error, 'plot_limit');

  const poor = await player('poor');
  const cen = (await everyPlot()).filter((p: any) => p.state === 'empty' && p.price > 10000)[0];
  const r2 = await poor.call('POST', `/api/plots/${cen.id}/buy`);
  assert.equal(r2.statusCode, 402);
  assert.equal(r2.json().error, 'insufficient_funds');
  assert.deepEqual(await ledgerMismatches(db), []);
});

test('build: zone rules, colours, cost, one building per plot', async () => {
  const a = await player('builder');
  const p = await emptyPlot('res', 30);
  await a.call('POST', `/api/plots/${p.id}/buy`);
  const bad = await a.call('POST', `/api/plots/${p.id}/build`, { template: 'tower', style: 'hitech', floors: 12, roof: 'antenna', rotation: 0, color: '#cfe3ee', accent: '#2a9d8f' });
  assert.equal(bad.json().error, 'wrong_zone');
  const badColor = await a.call('POST', `/api/plots/${p.id}/build`, { template: 'house', rotation: 0, color: '#ff00ff', accent: '#2a9d8f' });
  assert.equal(badColor.json().error, 'bad_color');
  const ok = await a.call('POST', `/api/plots/${p.id}/build`, { template: 'house', rotation: 2, style: 'milliy', color: '#f2e6d0', accent: '#2a9d8f' });
  assert.equal(ok.statusCode, 200, ok.body);
  assert.equal(ok.json().plot.building.template, 'house');
  assert.equal((await a.me()).balance, 10000 - p.price - 2000);
  const again = await a.call('POST', `/api/plots/${p.id}/build`, { template: 'house', rotation: 0, style: 'milliy', color: '#f2e6d0', accent: '#2a9d8f' });
  assert.equal(again.json().error, 'already_built');
  const other = await player('intruder');
  const steal = await other.call('POST', `/api/plots/${p.id}/build`, { template: 'house', rotation: 0, style: 'milliy', color: '#f2e6d0', accent: '#2a9d8f' });
  assert.equal(steal.statusCode, 403);
});

test('income: accrues per day, capped at 1 day, collected once', async () => {
  const a = await player('earner');
  const p = await emptyPlot('res', 40);
  await a.call('POST', `/api/plots/${p.id}/buy`);
  await a.call('POST', `/api/plots/${p.id}/build`, { template: 'house', rotation: 0, style: 'milliy', color: '#f2e6d0', accent: '#2a9d8f' });
  // pretend the house was finished 3 days ago and never collected
  await db.query("update buildings set ready_at = now() - interval '3 days', last_collected_at = now() - interval '3 days' where plot_id = $1", [p.id]);
  const before = (await a.me()).balance;
  const c1 = (await a.call('POST', '/api/me/collect')).json();
  assert.equal(c1.collected, 150, 'capped at one day of a 150/day house');
  assert.equal(c1.balance, before + 150);
  const c2 = (await a.call('POST', '/api/me/collect')).json();
  assert.equal(c2.collected, 0);
  assert.deepEqual(await ledgerMismatches(db), []);
});

test('market: price corridor, new-account rule, sale moves coins and building', async () => {
  const seller = await player('seller');
  const p = await emptyPlot('res', 50);
  await seller.call('POST', `/api/plots/${p.id}/buy`);
  await seller.call('POST', `/api/plots/${p.id}/build`, { template: 'house', rotation: 0, style: 'milliy', color: '#f2e6d0', accent: '#2a9d8f' });
  const tooNew = await seller.call('POST', `/api/plots/${p.id}/list`, { price: 9000 });
  assert.equal(tooNew.json().error, 'account_too_new');
  await db.query("update users set created_at = now() - interval '10 days' where nickname = 'seller'");
  const tooHigh = await seller.call('POST', `/api/plots/${p.id}/list`, { price: 999999 });
  assert.equal(tooHigh.json().error, 'price_out_of_range');
  const { min } = tooHigh.json();
  assert.equal((await seller.call('POST', `/api/plots/${p.id}/list`, { price: min })).statusCode, 200);
  assert.equal((await city()).plots.find((q: any) => q.id === p.id).state, 'sale');

  const sellerBefore = (await seller.me()).balance;
  const buyer = await player('buyer2');
  const r = await buyer.call('POST', `/api/plots/${p.id}/buy`);
  assert.equal(r.statusCode, 200, r.body);
  assert.equal(r.json().plot.owner.nickname, 'buyer2');
  assert.equal(r.json().plot.building.template, 'house', 'building goes with the plot');
  assert.equal((await buyer.me()).balance, 10000 - min);
  const sellerAfter = (await seller.me()).balance;
  assert.ok(sellerAfter - sellerBefore >= min - Math.round(min * 0.05), 'seller gets price minus 5% fee (+ any unclaimed income)');
  assert.deepEqual(await ledgerMismatches(db), []);
});

test('buying a demo neighbour’s listing works and pays the bot', async () => {
  const b = await player('shopper');
  const listing = (await city()).plots.find((p: any) => p.state === 'sale' && p.price <= 10000);
  if (!listing) return; // depends on demo seed
  const r = await b.call('POST', `/api/plots/${listing.id}/buy`);
  assert.equal(r.statusCode, 200, r.body);
  assert.deepEqual(await ledgerMismatches(db), []);
});

test('likes, reports and moderation', async () => {
  const a = await player('liker');
  const owned = (await city()).plots.find((p: any) => p.state === 'owned' && p.building);
  assert.equal((await a.call('POST', `/api/plots/${owned.id}/like`)).statusCode, 200);
  assert.equal((await a.call('POST', '/api/reports', { targetType: 'plot', targetId: owned.id, reason: 'nomaqbul nom' })).statusCode, 200);
  assert.equal((await a.call('GET', '/api/admin/reports')).statusCode, 403);
  await db.query("update users set role = 'moderator' where nickname = 'liker'");
  const reports = (await a.call('GET', '/api/admin/reports')).json();
  assert.ok(reports.length >= 1);
  assert.equal((await a.call('POST', '/api/admin/action', { action: 'hide_building', plotId: owned.id, reason: 'test' })).statusCode, 200);
  assert.equal((await app.inject({ method: 'GET', url: `/api/plots/${owned.id}` })).json().building, null);
  const victim = await player('banme');
  const vid = (await victim.me()).id;
  await a.call('POST', '/api/admin/action', { action: 'ban', userId: vid });
  assert.equal((await victim.call('GET', '/api/me')).statusCode, 401, 'ban ends sessions');
});

test('public profile never exposes private data', async () => {
  const a = await player('private1');
  const id = (await a.me()).id;
  const pub = (await app.inject({ method: 'GET', url: `/api/users/${id}` })).json();
  assert.deepEqual(Object.keys(pub).sort(), ['avatarId', 'id', 'likes', 'nickname', 'plots', 'since']);
});

test('city: 12 992-plot layout (v1 centre ids unchanged), only non-empty plots sent, client-side land prices match', async () => {
  const c = await city();
  assert.equal(c.total, 12992);
  assert.ok(c.plots.every((p: any) => p.state !== 'empty'));
  const p0 = (await app.inject({ method: 'GET', url: '/api/plots/0' })).json();
  assert.deepEqual([p0.x, p0.z], [-267, -211]); // same formula as web/index.html
  const p1216 = (await app.inject({ method: 'GET', url: '/api/plots/1216' })).json();
  assert.deepEqual([p1216.x, p1216.z, p1216.district], [-883, -715, 3]);
  // the client prices empty land as round100(base × loc × (1 + w × occupancy[district]))
  const loc = 0.77, occ = c.land.occupancy[3] || 0;
  assert.equal(p1216.price, Math.round(4000 * loc * (1 + c.land.demandWeight * occ) / 100) * 100);
  clearEconomyCache();
});

test('expansion: a v1 database (1 216 plots) gets the new outer ring on the next start, owners untouched', async () => {
  const before = (await db.query('select count(*)::int n, count(owner_id)::int o from plots where id < 1216')).rows[0];
  await db.query('delete from plots where id >= 1216 and owner_id is null and not exists (select 1 from listings l where l.plot_id = plots.id)');
  const mid = (await db.query('select count(*)::int n from plots')).rows[0].n;
  assert.ok(mid < 12992);
  await seed(db, { demo: false });
  const after = (await db.query('select count(*)::int n from plots')).rows[0].n;
  assert.equal(after, 12992);
  assert.deepEqual((await db.query('select count(*)::int n, count(owner_id)::int o from plots where id < 1216')).rows[0], before);
});

test('Telegram login: signature checked, @username shown over the owner’s plots unless hidden', async () => {
  (config as any).telegramBotToken = '123456:TEST-TOKEN';
  const sign = (d: Record<string, string | number>) => {
    const s = Object.keys(d).sort().map((k) => `${k}=${d[k]}`).join('\n');
    const secret = crypto.createHash('sha256').update(config.telegramBotToken).digest();
    return { ...d, hash: crypto.createHmac('sha256', secret).update(s).digest('hex') };
  };
  const payload = sign({ id: 777001, first_name: 'Shohrux', username: 'shohruh_k', auth_date: Math.floor(Date.now() / 1000) });
  const forged = { ...payload, username: 'someone_else' };
  assert.equal((await app.inject({ method: 'POST', url: '/api/auth/telegram', payload: forged })).statusCode, 401, 'tampered data rejected');
  const r = await app.inject({ method: 'POST', url: '/api/auth/telegram', payload });
  assert.equal(r.statusCode, 200, r.body);
  const cookie = String(r.headers['set-cookie']).split(';')[0];
  const call = (method: any, url: string, body?: any) => app.inject({ method, url, payload: body, headers: { cookie } });
  await call('POST', '/api/me/nickname', { nickname: 'TgShohrux', confirm16: true });
  const p = await emptyPlot('res', 60);
  const bought = (await call('POST', `/api/plots/${p.id}/buy`)).json();
  assert.equal(bought.plot.owner.telegram, 'shohruh_k');
  assert.equal((await call('GET', '/api/me')).json().telegram, 'shohruh_k');
  await call('POST', '/api/me/privacy', { showTelegram: false });
  assert.equal((await app.inject({ method: 'GET', url: `/api/plots/${p.id}` })).json().owner.telegram, null, 'hidden when the owner turns it off');
  assert.equal((await app.inject({ method: 'GET', url: `/api/plots/${p.id}` })).json().owner.nickname, 'TgShohrux');
  (config as any).telegramBotToken = '';
});

test('demo city keeps exactly one showcase building per mahalla', async () => {
  const r = await db.query("select p.district_id, b.style from buildings b join plots p on p.id = b.plot_id join users u on u.id = p.owner_id where u.role = 'bot' and b.template not like 'lm\\_%' order by p.district_id");
  assert.deepEqual(r.rows.map((x) => x.district_id), [0, 1, 2]);
  assert.deepEqual(r.rows.map((x) => x.style).sort(), ['hitech', 'milliy', 'modern']);
});

test('styles, floors and roofs: validated, priced by floors', async () => {
  const a = await player('stylist');
  await db.query("update wallets set balance = balance + 50000 where user_id = (select id from users where nickname='stylist')");
  await db.query("insert into transactions(user_id,amount,type,balance_after) select id, 50000, 'admin_adjust', 60000 from users where nickname='stylist'");
  const p = (await everyPlot()).filter((x: any) => x.state === 'empty' && x.zone === 'com')[0];
  await a.call('POST', `/api/plots/${p.id}/buy`);
  const tryBuild = (b: any) => a.call('POST', `/api/plots/${p.id}/build`, { template: 'office', accent: '#2a9d8f', ...b });
  assert.equal((await tryBuild({ style: 'hitech', floors: 40, roof: 'antenna', color: '#cfe3ee' })).json().error, 'bad_floors');
  assert.equal((await tryBuild({ style: 'hitech', floors: 10, roof: 'gable', color: '#cfe3ee' })).json().error, 'bad_roof');
  assert.equal((await tryBuild({ style: 'gothic', floors: 10, roof: 'antenna', color: '#cfe3ee' })).json().error, 'bad_style');
  assert.equal((await tryBuild({ style: 'milliy', floors: 10, roof: 'antenna', color: '#cfe3ee' })).json().error, 'bad_color', 'colour must match the style palette');
  const before = (await a.me()).balance;
  const ok = await tryBuild({ style: 'hitech', floors: 10, roof: 'helipad', color: '#cfe3ee' });
  assert.equal(ok.statusCode, 200, ok.body);
  assert.equal(ok.json().cost, 6000 + 500 * (10 - 3));
  assert.equal((await a.me()).balance, before - 9500);
  const b = ok.json().plot.building;
  assert.deepEqual([b.template, b.style, b.floors, b.roof], ['office', 'hitech', 10, 'helipad']);
  assert.deepEqual(await ledgerMismatches(db), []);
});

test('landmark copies: all 13 stand from the start (skyscrapers in the centre), for sale, one of each', async () => {
  const lm = (await city()).plots.filter((x: any) => x.building && x.building.template.startsWith('lm_'));
  assert.equal(lm.length, 13);
  assert.ok(lm.every((x: any) => x.state === 'sale' && x.owner.nickname === 'Shahar hokimligi'));
  assert.ok(lm.filter((x: any) => !['lm_hilton', 'lm_chorsu', 'lm_tvtower'].includes(x.building.template)).every((x: any) => x.zone === 'cen'), 'the skyscrapers stand in the centre');
  const richify = async (nick: string) => {
    await db.query("update wallets set balance = balance + 300000 where user_id = (select id from users where nickname=$1)", [nick]);
    await db.query("insert into transactions(user_id,amount,type,balance_after) select u.id, 300000, 'admin_adjust', w.balance from users u join wallets w on w.user_id = u.id where u.nickname=$1", [nick]);
  };
  const a = await player('tycoon'); await richify('tycoon');
  const res = await emptyPlot('res', 70);
  await a.call('POST', `/api/plots/${res.id}/buy`);
  assert.equal((await a.call('POST', `/api/plots/${res.id}/build`, { template: 'lm_burj' })).json().error, 'wrong_zone');
  const cen = (await everyPlot()).filter((x: any) => x.state === 'empty' && x.zone === 'cen');
  await a.call('POST', `/api/plots/${cen[0].id}/buy`);
  const dup = await a.call('POST', `/api/plots/${cen[0].id}/build`, { template: 'lm_burj' });
  assert.equal(dup.statusCode, 409); assert.equal(dup.json().error, 'landmark_taken', 'a second Burj Khalifa is refused');
  const lotte = lm.find((x: any) => x.building.template === 'lm_lotte');
  const before = (await a.me()).balance;
  const r = await a.call('POST', `/api/plots/${lotte.id}/buy`);
  assert.equal(r.statusCode, 200, r.body);
  assert.equal(r.json().plot.owner.nickname, 'tycoon');
  assert.equal(r.json().plot.building.template, 'lm_lotte');
  assert.equal((await a.me()).balance, before - lotte.price);
  assert.deepEqual(await ledgerMismatches(db), []);
});

test('skyscraper copies: each alone in its own block, the rest of the block is city land; a crowded one is moved', async () => {
  const blockOf = (id: number) => Math.floor(id / 16);
  const check = async () => {
    const all = await everyPlot();
    const lm = all.filter((x: any) => x.building && x.building.template.startsWith('lm_'));
    assert.equal(lm.length, 13);
    assert.equal(new Set(lm.map((x: any) => blockOf(x.id))).size, 13, 'one block each');
    for (const [key, spot] of [['lm_hilton', [330, -260]], ['lm_chorsu', [-340, 140]], ['lm_tvtower', [140, -470]]] as [string, number[]][]) {
      const l = lm.find((x: any) => x.building.template === key);
      const ps = all.filter((y: any) => blockOf(y.id) === blockOf(l.id));
      const cx = ps.reduce((s: number, p: any) => s + p.x, 0) / ps.length, cz = ps.reduce((s: number, p: any) => s + p.z, 0) / ps.length;
      assert.ok(Math.hypot(cx - spot[0], cz - spot[1]) < 80, `${key} stands near its spot`);
    }
    for (const l of lm) for (const q of all.filter((y: any) => blockOf(y.id) === blockOf(l.id) && y.id !== l.id)) {
      assert.ok(!q.building, 'no other building in a skyscraper block');
    }
    return lm;
  };
  const lm = await check();
  // a player's building appears in Shanghai Tower's block (e.g. an old city): the tower moves, the player keeps the plot
  const sh = lm.find((x: any) => x.building.template === 'lm_shanghai');
  const neighbour = (await everyPlot()).find((y: any) => blockOf(y.id) === blockOf(sh.id) && y.id !== sh.id);
  const me = (await db.query("select id from users where role <> 'bot' limit 1")).rows[0].id;
  await db.query("update plots set owner_id = $1, status = 'owned' where id = $2", [me, neighbour.id]);
  await db.query("insert into buildings(plot_id,template,style,floors,roof,rotation,color,accent,ready_at,last_collected_at) values ($1,'house','milliy',1,'gable',0,'#ecd9b4','#2a9d8f',now(),now())", [neighbour.id]);
  await landmarkBlocks(db);
  const after = await check();
  const sh2 = after.find((x: any) => x.building.template === 'lm_shanghai');
  assert.notEqual(blockOf(sh2.id), blockOf(sh.id), 'moved to a free block');
  assert.equal(sh2.state, sh.state); assert.equal(sh2.owner.nickname, sh.owner.nickname);
  const kept = (await db.query('select owner_id from plots where id = $1', [neighbour.id])).rows[0];
  assert.equal(Number(kept.owner_id), Number(me), 'the player keeps their plot');
  assert.deepEqual(await ledgerMismatches(db), []);
});

test('"Hovlimni top": find plots by nickname or shown Telegram @username', async () => {
  const byNick = (await app.inject({ method: 'GET', url: '/api/find?q=buyer1' })).json();
  assert.equal(byNick.found, true); assert.equal(byNick.plots.length, 1);
  // the Telegram test user hid their @username, so it must not be findable by it
  assert.equal((await app.inject({ method: 'GET', url: '/api/find?q=@shohruh_k' })).json().found, false);
  await db.query("update users set show_telegram = true where telegram_username = 'shohruh_k'");
  const byTg = (await app.inject({ method: 'GET', url: '/api/find?q=@SHOHRUH_K' })).json();
  assert.equal(byTg.found, true); assert.equal(byTg.nickname, 'TgShohrux');
  assert.equal((await app.inject({ method: 'GET', url: '/api/find?q=nobody_here' })).json().found, false);
  assert.equal((await app.inject({ method: 'GET', url: '/api/find?q=Shahar' })).json().found, false, 'bots are not people');
  assert.ok((await city()).stats.residents >= 5);
});

test('guest login is off unless GUEST_LOGIN=1', async () => {
  const r = await app.inject({ method: 'POST', url: '/api/auth/guest' });
  assert.equal(r.statusCode, 403);
});

test('rate limit protects login', async () => {
  const limited = await buildApp(db);
  const codes: number[] = [];
  for (let i = 0; i < 25; i++) codes.push((await limited.inject({ method: 'POST', url: '/api/auth/dev', payload: { name: 'spam' + i } })).statusCode);
  assert.ok(codes.includes(429));
  await limited.close();
});

test('cars: buy one Tracker, any colour, random / chosen / custom plates, unique plates, changes are charged', async () => {
  const a = await player('driver1'), b = await player('driver2'), c = await player('driver3');
  // a: random plate, free
  let r = await a.call('POST', '/api/car/buy', { color: '#C0392B', plate: { kind: 'random', region: '01' } });
  assert.equal(r.statusCode, 200, r.body);
  assert.equal(r.json().cost, 5000);
  assert.match(r.json().car.plate.text, /^[A-Z][0-9]{3}[A-Z]{2}$/);
  assert.equal(r.json().car.color, '#c0392b');
  assert.equal((await a.me()).balance, 5000);
  assert.equal((await a.me()).car.plate.region, '01');
  assert.equal(r.json().car.model, 'tracker');
  assert.equal((await c.call('POST', '/api/car/buy', { model: 'lada', color: '#ffffff', plate: { kind: 'random', region: '01' } })).json().error, 'bad_model');
  assert.ok((await city()).economy.car.models.tracker.price > 0);
  // one car each
  r = await a.call('POST', '/api/car/buy', { color: '#ffffff', plate: { kind: 'random', region: '01' } });
  assert.equal(r.json().error, 'already_have_car');
  // b: chosen standard plate (+500), spaces and lower case are fine
  r = await b.call('POST', '/api/car/buy', { color: '#1f6fb2', plate: { kind: 'standard', region: '10', text: 'a 777 aa' } });
  assert.equal(r.statusCode, 200, r.body);
  assert.equal(r.json().cost, 5500);
  assert.deepEqual(r.json().car.plate, { region: '10', text: 'A777AA', kind: 'standard' });
  // the same plate is taken for c; availability check says so
  assert.equal((await c.call('GET', '/api/car/plate?kind=standard&region=10&text=A777AA')).json().ok, false);
  assert.equal((await c.call('GET', '/api/car/plate?kind=standard&region=20&text=A777AA')).json().ok, true);
  r = await c.call('POST', '/api/car/buy', { color: '#000000', plate: { kind: 'standard', region: '10', text: 'A777AA' } });
  assert.equal(r.json().error, 'plate_taken');
  assert.equal((await c.me()).balance, 10000);
  // bad formats, bad colours, blocked words
  assert.equal((await c.call('POST', '/api/car/buy', { color: '#000000', plate: { kind: 'standard', region: '10', text: '777' } })).json().error, 'bad_plate');
  assert.equal((await c.call('POST', '/api/car/buy', { color: '#000000', plate: { kind: 'custom', region: '33', text: 'SALOM' } })).json().error, 'bad_region');
  assert.equal((await c.call('POST', '/api/car/buy', { color: 'red', plate: { kind: 'random', region: '01' } })).json().error, 'bad_color');
  assert.equal((await c.call('POST', '/api/car/buy', { color: '#000000', plate: { kind: 'custom', region: '01', text: 'AHMOQ' } })).json().error, 'plate_blocked');
  // c: custom inscription (+2000)
  r = await c.call('POST', '/api/car/buy', { color: '#000000', plate: { kind: 'custom', region: '01', text: 'Mahalla' } });
  assert.equal(r.statusCode, 200, r.body);
  assert.equal(r.json().cost, 7000);
  assert.deepEqual(r.json().car.plate, { region: '01', text: 'MAHALLA', kind: 'custom' });
  // changes: colour 300, chosen plate 500, nothing changed = free
  r = await b.call('POST', '/api/car/update', { color: '#ffffff' });
  assert.equal(r.json().cost, 300);
  r = await b.call('POST', '/api/car/update', { color: '#ffffff', plate: { kind: 'standard', region: '10', text: 'A777AA' } });
  assert.equal(r.json().cost, 0);
  r = await b.call('POST', '/api/car/update', { plate: { kind: 'custom', region: '01', text: 'MAHALLA' } });
  assert.equal(r.json().error, 'plate_taken');
  r = await b.call('POST', '/api/car/update', { plate: { kind: 'standard', region: '90', text: 'B001BB' } });
  assert.equal(r.json().cost, 500);
  assert.equal((await b.me()).balance, 10000 - 5500 - 300 - 500);
  // everyone sees the cars in the city
  const cars = (await city()).cars;
  assert.ok(cars.some((x: any) => x.owner.nickname === 'driver2' && x.plate.text === 'B001BB' && x.color === '#ffffff'));
  assert.deepEqual(await ledgerMismatches(db), []);
});

test('cars: the same buy sent twice charges once; the founder keeps the white Tracker 90 Y 095 AB', async () => {
  const a = await player('driver4');
  const key = crypto.randomUUID();
  const [r1, r2] = await Promise.all([1, 2].map(() => a.call('POST', '/api/car/buy', { color: '#2b2f36', plate: { kind: 'random', region: '30' } }, { 'idempotency-key': key })));
  assert.equal(r1.statusCode, 200, r1.body); assert.equal(r2.statusCode, 200, r2.body);
  assert.equal((await a.me()).balance, 5000);
  const f = await player('founder', 'shohruh.97');
  const car = (await f.me()).car;
  assert.deepEqual(car.plate, { region: '90', text: 'Y095AB', kind: 'standard' });
  assert.equal(car.color, '#f2f3f1');
  assert.equal((await f.me()).balance, 10000);
});
