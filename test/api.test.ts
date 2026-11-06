// End-to-end tests against a real (embedded) PostgreSQL.
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { createPool, migrate, Db } from '../src/db.js';
import { seed } from '../src/seed.js';
import { buildApp } from '../src/server.js';
import { ledgerMismatches, clearEconomyCache } from '../src/game.js';
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
async function emptyPlot(zone: string, skip = 0) {
  const c = await city();
  return c.plots.filter((p: any) => p.state === 'empty' && p.zone === zone)[skip];
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
  const cen = (await city()).plots.filter((p: any) => p.state === 'empty' && p.price > 10000)[0];
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
  assert.equal((await city()).plots[p.id].state, 'sale');

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

test('city endpoint returns the same 1 216-plot layout as the 3D client', async () => {
  const c = await city();
  assert.equal(c.plots.length, 1216);
  assert.deepEqual([c.plots[0].x, c.plots[0].z], [-267, -211]); // same formula as web/index.html
  clearEconomyCache();
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
  const p = (await city()).plots.filter((x: any) => x.state === 'empty' && x.zone === 'com')[0];
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

test('landmark copies: all 10 stand in the centre from the start, for sale, one of each', async () => {
  const lm = (await city()).plots.filter((x: any) => x.building && x.building.template.startsWith('lm_'));
  assert.equal(lm.length, 10);
  assert.ok(lm.every((x: any) => x.zone === 'cen' && x.state === 'sale' && x.owner.nickname === 'Shahar hokimligi'));
  const richify = async (nick: string) => {
    await db.query("update wallets set balance = balance + 300000 where user_id = (select id from users where nickname=$1)", [nick]);
    await db.query("insert into transactions(user_id,amount,type,balance_after) select u.id, 300000, 'admin_adjust', w.balance from users u join wallets w on w.user_id = u.id where u.nickname=$1", [nick]);
  };
  const a = await player('tycoon'); await richify('tycoon');
  const res = await emptyPlot('res', 70);
  await a.call('POST', `/api/plots/${res.id}/buy`);
  assert.equal((await a.call('POST', `/api/plots/${res.id}/build`, { template: 'lm_burj' })).json().error, 'wrong_zone');
  const cen = (await city()).plots.filter((x: any) => x.state === 'empty' && x.zone === 'cen');
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
