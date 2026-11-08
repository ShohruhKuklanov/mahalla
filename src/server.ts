import Fastify, { FastifyReply, FastifyRequest } from 'fastify';
import cookie from '@fastify/cookie';
import websocket from '@fastify/websocket';
import rateLimit from '@fastify/rate-limit';
import fstatic from '@fastify/static';
import { z } from 'zod';
import crypto from 'node:crypto';
import type { Db } from './db.js';
import { tx, rootPath } from './db.js';
import { config } from './config.js';
import { AppError, E } from './errors.js';
import { SESSION_COOKIE, SessionUser, createSession, destroySession, sessionUser, upsertIdentity, verifyTelegram } from './auth.js';
import { checkNickname, isCleanText, suggestions } from './nickname.js';
import * as game from './game.js';
import { DISTRICTS, ZONES, CAR, normalizePlate } from './economy.js';

declare module 'fastify' { interface FastifyRequest { user: SessionUser | null } }

const webDir = rootPath('web');

export async function buildApp(db: Db, opts: { logger?: boolean; rateLimit?: boolean } = {}) {
  const app = Fastify({ logger: opts.logger ?? false, trustProxy: true, bodyLimit: 32 * 1024 });
  await app.register(cookie);
  if (opts.rateLimit !== false) await app.register(rateLimit, { max: config.rateLimitPerMinute, timeWindow: '1 minute' });
  await app.register(websocket);

  // ---------- realtime: everyone sees plots change ----------
  const sockets = new Set<import('ws').WebSocket>();
  const broadcast = (msg: unknown) => { const s = JSON.stringify(msg); for (const ws of sockets) if (ws.readyState === 1) ws.send(s); };
  const pushPlot = async (id: number) => { const p = await game.onePlot(db, id); if (p) broadcast({ type: 'plot', plot: p }); };
  app.get('/ws', { websocket: true }, (socket) => {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
    socket.on('message', () => {}); // read-only channel; actions go through HTTP
  });

  // ---------- session ----------
  app.decorateRequest('user', null);
  app.addHook('preHandler', async (req) => {
    req.user = await sessionUser(db, req.cookies[SESSION_COOKIE]);
    if (req.user && Math.random() < 0.05) db.query('update users set last_seen_at = now() where id = $1', [req.user.id]).catch(() => {});
  });
  const setSession = (reply: FastifyReply, token: string, expires: Date) =>
    reply.setCookie(SESSION_COOKIE, token, { path: '/', httpOnly: true, sameSite: 'lax', secure: config.production, expires });

  // ---------- errors ----------
  app.setErrorHandler((err: any, req, reply) => {
    if (err instanceof AppError) return reply.code(err.status).send({ error: err.code, message: err.message, ...err.extra });
    if (err instanceof z.ZodError) return reply.code(400).send({ error: 'validation', message: 'Ma’lumot noto‘g‘ri.', issues: err.issues });
    if (err.statusCode === 429) return reply.code(429).send({ error: 'rate_limited', message: 'Juda tez. Biroz kuting.' });
    req.log.error(err);
    return reply.code(500).send({ error: 'server', message: 'Serverda xatolik. Keyinroq urinib ko‘ring.' });
  });

  const idem = (req: FastifyRequest) => {
    const k = req.headers['idempotency-key'];
    return typeof k === 'string' && k.length >= 8 && k.length <= 80 ? k : null;
  };
  const plotId = (req: FastifyRequest) => z.coerce.number().int().min(0).parse((req.params as any).id);
  const startCoins = async () => (await game.economy(db)).start_coins;

  // ---------- auth ----------
  const authLimit = { config: { rateLimit: { max: 20, timeWindow: '1 minute' } } };
  app.get('/api/auth/options', async () => ({ dev: config.devLogin, guest: config.guestLogin, telegramBot: config.telegramBotName || null }));

  app.post('/api/auth/dev', authLimit, async (req, reply) => {
    if (!config.devLogin) throw E.forbidden();
    const { name } = z.object({ name: z.string().min(1).max(40) }).parse(req.body);
    const { userId } = await upsertIdentity(db, 'dev', name.toLowerCase(), await startCoins());
    const s = await createSession(db, userId);
    setSession(reply, s.token, s.expires);
    return { ok: true };
  });

  app.post('/api/auth/guest', { config: { rateLimit: { max: 5, timeWindow: '1 minute' } } }, async (_req, reply) => {
    if (!config.guestLogin) throw E.forbidden();
    const { userId } = await upsertIdentity(db, 'guest', crypto.randomUUID(), await startCoins());
    const s = await createSession(db, userId);
    setSession(reply, s.token, s.expires);
    return { ok: true };
  });

  app.post('/api/auth/telegram', authLimit, async (req, reply) => {
    const data = z.record(z.string(), z.union([z.string(), z.number()])).parse(req.body);
    if (!verifyTelegram(data, config.telegramBotToken)) throw new AppError(401, 'bad_telegram', 'Telegram tasdiqlamadi. Qayta urinib ko‘ring.');
    const { userId } = await upsertIdentity(db, 'telegram', String(data.id), await startCoins());
    // keep the @username current (people change it); Telegram usernames are 5–32 of [A-Za-z0-9_]
    const tg = typeof data.username === 'string' && /^[A-Za-z0-9_]{5,32}$/.test(data.username) ? data.username : null;
    await db.query('update users set telegram_username = $2 where id = $1', [userId, tg]);
    const s = await createSession(db, userId);
    setSession(reply, s.token, s.expires);
    return { ok: true };
  });

  app.post('/api/auth/logout', async (req, reply) => {
    await destroySession(db, req.cookies[SESSION_COOKIE]);
    reply.clearCookie(SESSION_COOKIE, { path: '/' });
    return { ok: true };
  });

  // ---------- me ----------
  app.get('/api/me', async (req) => {
    const u = req.user; if (!u) throw E.auth();
    const [w, plots, inc, eco, extra, car] = await Promise.all([
      db.query('select balance from wallets where user_id = $1', [u.id]),
      db.query('select id from plots where owner_id = $1 order by id', [u.id]),
      game.pendingIncome(db, u.id),
      game.economy(db),
      db.query('select telegram_username, show_telegram from users where id = $1', [u.id]),
      game.carOf(db, u.id),
    ]);
    return {
      telegram: extra.rows[0]?.telegram_username ?? null, showTelegram: extra.rows[0]?.show_telegram ?? true,
      id: u.id, nickname: u.nickname, role: u.role, status: u.status,
      balance: w.rows[0]?.balance ?? 0, plots: plots.rows.map((r) => r.id),
      pending: inc.pending, dailyIncome: inc.dailyIncome, plotLimit: eco.plot_limit, car,
    };
  });

  app.post('/api/me/nickname', async (req) => {
    const u = req.user; if (!u) throw E.auth();
    const b = z.object({ nickname: z.string(), avatarId: z.number().int().min(1).max(12).default(1), confirm16: z.literal(true) }).parse(req.body);
    const chk = checkNickname(b.nickname);
    if (!chk.ok) throw E.bad(chk.code, chk.message);
    try {
      await db.query('update users set nickname = $2, nickname_lower = $3, avatar_id = $4, birth_confirmed_16 = true where id = $1', [u.id, chk.nick, chk.lower, b.avatarId]);
    } catch (e: any) {
      if (e.code === '23505') throw E.conflict('nickname_taken', 'Bu nik band. Boshqasini tanlang.', { suggestions: suggestions(chk.nick) });
      throw e;
    }
    if (chk.lower === 'shohruh.97') await game.grantFounderCar(db);
    if (['shaxzamee_5400', 'shaxzomee_5400', 'shaxzoda'].includes(chk.lower)) for (const id of await game.giftShaxzodaHouse(db)) await pushPlot(id);
    return { nickname: chk.nick };
  });

  app.post('/api/me/privacy', async (req) => {
    const u = req.user; if (!u) throw E.auth();
    const { showTelegram } = z.object({ showTelegram: z.boolean() }).parse(req.body);
    await db.query('update users set show_telegram = $2 where id = $1', [u.id, showTelegram]);
    const plots = (await db.query('select id from plots where owner_id = $1', [u.id])).rows;
    for (const p of plots) await pushPlot(p.id); // everyone's labels update live
    return { showTelegram };
  });

  app.get('/api/nickname/available', async (req) => {
    const { n } = z.object({ n: z.string() }).parse(req.query);
    const chk = checkNickname(n);
    if (!chk.ok) return { available: false, reason: chk.message };
    const r = await db.query('select 1 from users where nickname_lower = $1', [chk.lower]);
    return r.rows.length ? { available: false, reason: 'Band', suggestions: suggestions(chk.nick) } : { available: true };
  });

  app.post('/api/me/collect', async (req) => game.collect(db, req.user));

  // ---------- city ----------
  app.get('/api/city', async () => {
    const eco = await game.economy(db);
    return {
      districts: DISTRICTS, zones: ZONES, // building types, styles, prices: the catalog block in index.html
      economy: { plotLimit: eco.plot_limit, saleFee: eco.sale_fee, daySeconds: config.daySeconds, car: CAR },
      stats: { residents: (await db.query("select count(distinct p.owner_id)::int n from plots p join users u on u.id = p.owner_id where u.role <> 'bot'")).rows[0].n },
      ...(await game.cityView(db)),
    };
  });
  // "Hovlimni top": find someone's plots by Telegram @username (only if they show it) or by game nickname
  app.get('/api/find', { config: { rateLimit: { max: 30, timeWindow: '1 minute' } } }, async (req) => {
    const { q } = z.object({ q: z.string().min(1).max(40) }).parse(req.query);
    const name = q.trim().replace(/^@/, '').toLowerCase();
    if (!/^[\p{L}\p{N}_.‘’ʻ]{2,40}$/u.test(name)) return { found: false, plots: [] };
    const u = (await db.query(
      `select id, nickname from users where status = 'active' and role <> 'bot'
       and ((show_telegram and lower(telegram_username) = $1) or nickname_lower = $1) order by (lower(telegram_username) = $1) desc nulls last limit 1`, [name])).rows[0];
    if (!u) return { found: false, plots: [] };
    const plots = (await db.query('select id from plots where owner_id = $1 order by id', [u.id])).rows.map((r) => r.id);
    return { found: plots.length > 0, nickname: u.nickname, plots };
  });

  app.get('/api/plots/:id', async (req) => {
    const p = await game.onePlot(db, plotId(req)); if (!p) throw E.notFound('Uchastka topilmadi'); return p;
  });

  app.post('/api/plots/:id/buy', async (req) => {
    const id = plotId(req);
    const r = await game.buyPlot(db, req.user, id, idem(req));
    await pushPlot(id);
    return { ...r, plot: await game.onePlot(db, id) };
  });
  app.post('/api/plots/:id/build', async (req) => {
    const id = plotId(req);
    const body = z.object({
      template: z.string().max(40), rotation: z.number().int().min(0).max(3).optional(),
      color: z.string().max(9).optional(), accent: z.string().max(9).optional(),
      style: z.string().max(10).optional(), floors: z.number().int().optional(), roof: z.string().max(10).optional(),
    }).parse(req.body);
    const r = await game.buildOnPlot(db, req.user, id, body, idem(req));
    await pushPlot(id);
    return { ...r, plot: await game.onePlot(db, id) };
  });
  app.post('/api/plots/:id/list', async (req) => {
    const id = plotId(req);
    const { price } = z.object({ price: z.number().int().positive() }).parse(req.body);
    const r = await game.listForSale(db, req.user, id, price);
    await pushPlot(id);
    return r;
  });
  app.get('/api/plots/:id/quote', async (req) => game.saleQuote(db, req.user, plotId(req)));
  app.delete('/api/plots/:id/list', async (req) => {
    const id = plotId(req); const r = await game.unlist(db, req.user, id); await pushPlot(id); return r;
  });
  app.post('/api/plots/:id/like', async (req) => game.like(db, req.user, plotId(req)));

  // ---------- cars ----------
  const plateBody = z.object({ kind: z.enum(['random', 'standard', 'custom']), region: z.string().max(2), text: z.string().max(16).optional() });
  const pushCar = async (userId: number) => { const c = await game.carOf(db, userId); if (c) broadcast({ type: 'car', car: c }); };
  app.post('/api/car/buy', async (req) => {
    const body = z.object({ model: z.string().max(20).optional(), color: z.string().max(7), plate: plateBody }).parse(req.body);
    const r = await game.buyCar(db, req.user, body, idem(req));
    if (req.user) await pushCar(req.user.id);
    return r;
  });
  app.post('/api/car/update', async (req) => {
    const body = z.object({ color: z.string().max(7).optional(), plate: plateBody.optional() }).parse(req.body);
    const r = await game.updateCar(db, req.user, body, idem(req));
    if (req.user) await pushCar(req.user.id);
    return r;
  });
  app.get('/api/car/plate', { config: { rateLimit: { max: 60, timeWindow: '1 minute' } } }, async (req) => {
    const q = z.object({ kind: z.enum(['standard', 'custom']), region: z.string().max(2), text: z.string().max(16) }).parse(req.query);
    const n = normalizePlate(q.kind, q.region, q.text);
    if ('error' in n) return { ok: false, reason: n.error };
    const free = await game.plateFree(db, n.region, n.text!, req.user?.id ?? 0);
    return free ? { ok: true, text: n.text } : { ok: false, reason: 'Bu raqam band' };
  });

  app.get('/api/users/:id', async (req) => {
    const id = z.coerce.number().int().parse((req.params as any).id);
    const u = (await db.query("select id, nickname, avatar_id, created_at from users where id = $1 and status = 'active'", [id])).rows[0];
    if (!u) throw E.notFound('Foydalanuvchi topilmadi');
    const plots = (await db.query('select id from plots where owner_id = $1 order by id', [id])).rows.map((r) => r.id);
    const likes = (await db.query('select count(*)::int n from likes l join plots p on p.id = l.plot_id where p.owner_id = $1', [id])).rows[0].n;
    // public profile: no real name, phone, or location — ever
    return { id: u.id, nickname: u.nickname, avatarId: u.avatar_id, since: u.created_at, plots, likes };
  });

  // ---------- reports & moderation ----------
  app.post('/api/reports', { config: { rateLimit: { max: 10, timeWindow: '1 minute' } } }, async (req) => {
    const u = req.user; if (!u) throw E.auth();
    const b = z.object({ targetType: z.enum(['user', 'plot']), targetId: z.number().int(), reason: z.string().min(3).max(300) }).parse(req.body);
    if (!isCleanText(b.reason)) throw E.bad('text_blocked', 'Matnda nomaqbul so‘z bor.');
    await db.query('insert into reports(reporter_id,target_type,target_id,reason) values ($1,$2,$3,$4)', [u.id, b.targetType, b.targetId, b.reason]);
    return { ok: true };
  });

  const staff = (req: FastifyRequest) => {
    const u = req.user; if (!u) throw E.auth();
    if (u.role !== 'admin' && u.role !== 'moderator') throw E.forbidden();
    return u;
  };
  app.get('/api/admin/reports', async (req) => {
    staff(req);
    return (await db.query("select * from reports where status = 'open' order by created_at limit 100")).rows;
  });
  app.post('/api/admin/action', async (req) => {
    const m = staff(req);
    const b = z.object({
      action: z.enum(['ban', 'unban', 'force_rename', 'hide_building', 'resolve_report', 'reject_report']),
      userId: z.number().int().optional(), plotId: z.number().int().optional(), reportId: z.number().int().optional(),
      reason: z.string().max(300).optional(),
    }).parse(req.body);
    await tx(db, async (c) => {
      if (b.action === 'ban' || b.action === 'unban') {
        if (!b.userId) throw E.bad('user_required', 'userId kerak');
        await c.query('update users set status = $2 where id = $1', [b.userId, b.action === 'ban' ? 'banned' : 'active']);
        if (b.action === 'ban') await c.query('delete from sessions where user_id = $1', [b.userId]);
      } else if (b.action === 'force_rename') {
        if (!b.userId) throw E.bad('user_required', 'userId kerak');
        await c.query('update users set nickname = null, nickname_lower = null where id = $1', [b.userId]);
      } else if (b.action === 'hide_building') {
        if (b.plotId == null) throw E.bad('plot_required', 'plotId kerak');
        await c.query("update buildings set status = 'hidden' where plot_id = $1", [b.plotId]);
      } else {
        if (!b.reportId) throw E.bad('report_required', 'reportId kerak');
        await c.query('update reports set status = $2, resolved_by = $3, resolved_at = now() where id = $1',
          [b.reportId, b.action === 'resolve_report' ? 'resolved' : 'rejected', m.id]);
      }
      await c.query('insert into moderation_actions(moderator_id,target_user_id,target_plot_id,action,reason) values ($1,$2,$3,$4,$5)',
        [m.id, b.userId ?? null, b.plotId ?? null, b.action, b.reason ?? null]);
    });
    if (b.plotId != null) await pushPlot(b.plotId);
    return { ok: true };
  });

  // the one-off house gift (see game.giftShaxzodaHouse): checked every 2 minutes too, so it happens whichever way the
  // receiving account signs in, and open clients see the building change hands at once
  const giftTimer = setInterval(async () => { try { for (const id of await game.giftShaxzodaHouse(db)) await pushPlot(id); } catch (_) {} }, 120_000);
  giftTimer.unref(); app.addHook('onClose', async () => clearInterval(giftTimer));

  app.get('/api/health', async () => { await db.query('select 1'); return { ok: true }; });

  // ---------- the 3D client ----------
  await app.register(fstatic, {
    root: webDir, prefix: '/', index: ['index.html'],
    // the page changes with every deploy: always revalidate it, so phones never keep an old city
    setHeaders: (res, filePath) => { if (filePath.endsWith('.html')) res.header('cache-control', 'no-cache'); },
  });

  return app;
}
