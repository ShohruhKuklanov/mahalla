import crypto from 'node:crypto';
import type { Db, Tx } from './db.js';
import { tx } from './db.js';
import { config } from './config.js';

export const SESSION_COOKIE = 'sid';
const sha256 = (s: string) => crypto.createHash('sha256').update(s).digest('hex');

export interface SessionUser {
  id: number; nickname: string | null; role: string; status: string; created_at: Date;
}

/** Find or create the user behind an external identity. New users get the signup bonus in the ledger. */
export async function upsertIdentity(db: Db, provider: string, subject: string, startCoins: number): Promise<{ userId: number; created: boolean }> {
  return tx(db, async (c) => {
    const found = await c.query('select user_id from auth_identities where provider=$1 and subject=$2', [provider, subject]);
    if (found.rows.length) return { userId: found.rows[0].user_id, created: false };
    const u = await c.query('insert into users default values returning id');
    const userId = u.rows[0].id as number;
    try {
      await c.query('insert into auth_identities(user_id,provider,subject) values ($1,$2,$3)', [userId, provider, subject]);
    } catch (e: any) {
      if (e.code === '23505') { // same identity created concurrently: use that one
        throw Object.assign(new Error('retry'), { retry: true });
      }
      throw e;
    }
    await c.query('insert into wallets(user_id,balance) values ($1,$2)', [userId, startCoins]);
    await c.query("insert into transactions(user_id,amount,type,balance_after) values ($1,$2,'signup_bonus',$2)", [userId, startCoins]);
    return { userId, created: true };
  }).catch(async (e) => {
    if (e.retry) return upsertIdentity(db, provider, subject, startCoins);
    throw e;
  });
}

export async function createSession(db: Db | Tx, userId: number) {
  const token = crypto.randomBytes(32).toString('base64url');
  const expires = new Date(Date.now() + config.sessionDays * 86400_000);
  await db.query('insert into sessions(user_id,token_hash,expires_at) values ($1,$2,$3)', [userId, sha256(token), expires]);
  return { token, expires };
}

export async function sessionUser(db: Db, token: string | undefined): Promise<SessionUser | null> {
  if (!token) return null;
  const r = await db.query(
    `select u.id, u.nickname, u.role, u.status, u.created_at from sessions s join users u on u.id = s.user_id
     where s.token_hash = $1 and s.expires_at > now()`, [sha256(token)]);
  return r.rows[0] || null;
}

export async function destroySession(db: Db, token: string | undefined) {
  if (token) await db.query('delete from sessions where token_hash = $1', [sha256(token)]);
}

/**
 * Telegram Login Widget check (https://core.telegram.org/widgets/login#checking-authorization):
 * secret = SHA256(bot_token); hash = HMAC_SHA256(data_check_string, secret).
 */
export function verifyTelegram(data: Record<string, string | number>, botToken: string, maxAgeSec = 86400): boolean {
  if (!botToken || !data.hash) return false;
  const checkString = Object.keys(data).filter((k) => k !== 'hash').sort().map((k) => `${k}=${data[k]}`).join('\n');
  const secret = crypto.createHash('sha256').update(botToken).digest();
  const hmac = crypto.createHmac('sha256', secret).update(checkString).digest('hex');
  const a = Buffer.from(hmac), b = Buffer.from(String(data.hash));
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return false;
  const age = Date.now() / 1000 - Number(data.auth_date);
  return age >= 0 && age < maxAgeSec;
}
