import type { WebSocket } from 'ws';
import { z } from 'zod';
import type { Db } from './db.js';
import { readAvatar, type Avatar } from './avatar.js';
import { CAR } from './economy.js';

/**
 * Who is out walking or driving in the city right now. A walking player's client sends its position over the
 * websocket a few times a second; everyone gets one compact list of all walkers five times a second, plus each
 * walker's nickname and 3D avatar when they appear or change it. Only signed-in players with a nickname are shown;
 * nothing is stored. Positions are clamped and rate-limited, so one client cannot flood the others.
 */
export type Player = { id: number; nick: string; avatar: Avatar | null; x: number; y: number; z: number; yaw: number;
  mode: 'walk' | 'drive'; speed: number; car: { model: string; color: string } | null; t: number; sock: WebSocket };

const num = (lo: number, hi: number) => z.number().finite().min(lo).max(hi);
const posMsg = z.object({
  type: z.literal('pos'), x: num(-6000, 6000), y: num(-20, 200), z: num(-6000, 6000), yaw: num(-1000, 1000),
  mode: z.enum(['walk', 'drive']), speed: num(-60, 60),
  car: z.object({ model: z.string().max(24), color: z.string().regex(/^#[0-9a-fA-F]{6}$/) }).nullable().optional(),
});

export function createPresence(db: Db, broadcast: (msg: unknown, except?: WebSocket) => void) {
  const players = new Map<number, Player>();
  const pav = (p: Player) => ({ type: 'pav', id: p.id, nick: p.nick, avatar: p.avatar });
  const remove = (id: number) => { if (players.delete(id)) broadcast({ type: 'pgone', id }); };
  async function loadAvatar(id: number) {
    const r = await db.query('select avatar3d from users where id = $1', [id]);
    return readAvatar(r.rows[0]?.avatar3d);
  }
  return {
    players,
    snapshot: () => ({ type: 'pinit', players: [...players.values()].map(pav) }),
    /** a message from a signed-in socket; returns nothing, answers by broadcast */
    async message(sock: WebSocket, user: { id: number; nickname: string | null }, raw: unknown) {
      if (!user.nickname) return;
      const m = raw as any;
      if (m && m.type === 'leave') { const p = players.get(user.id); if (p && p.sock === sock) remove(user.id); return; }
      if (m && m.type === 'avatar') {
        const p = players.get(user.id); if (!p) return;
        p.avatar = await loadAvatar(user.id); broadcast(pav(p)); return;
      }
      const r = posMsg.safeParse(raw); if (!r.success) return;
      const d = r.data, now = Date.now();
      let p = players.get(user.id);
      if (p && now - p.t < 60) return;                                     // at most ~16 updates a second
      const car = d.mode === 'drive' && d.car && (CAR.models as Record<string, unknown>)[d.car.model] ? { model: d.car.model, color: d.car.color.toLowerCase() } : null;
      if (!p) {
        p = { id: user.id, nick: user.nickname, avatar: await loadAvatar(user.id), x: d.x, y: d.y, z: d.z, yaw: d.yaw, mode: d.mode, speed: d.speed, car, t: now, sock };
        players.set(user.id, p); broadcast(pav(p));
      } else Object.assign(p, { x: d.x, y: d.y, z: d.z, yaw: d.yaw, mode: d.mode, speed: d.speed, car, t: now, sock });
    },
    closed(sock: WebSocket) { for (const p of players.values()) if (p.sock === sock) remove(p.id); },
    /** five times a second: everyone's positions; quiet walkers (no update for 15 s) are dropped */
    tick() {
      const now = Date.now();
      for (const p of [...players.values()]) if (now - p.t > 15000) remove(p.id);
      if (!players.size) return;
      const r1 = (v: number) => Math.round(v*10)/10, r2 = (v: number) => Math.round(v*100)/100;
      broadcast({ type: 'players', list: [...players.values()].map((p) => [p.id, r1(p.x), r2(p.y), r1(p.z), r2(p.yaw), p.mode, r1(p.speed), p.car ? p.car.model : null, p.car ? p.car.color : null]) });
    },
  };
}
