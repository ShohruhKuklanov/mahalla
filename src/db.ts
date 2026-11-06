import pg from 'pg';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// BIGINT columns come back as strings by default; balances fit safely in a JS number.
pg.types.setTypeParser(20, (v) => Number(v));

export type Db = pg.Pool;
export type Tx = pg.PoolClient;

export function createPool(connectionString: string): Db {
  return new pg.Pool({ connectionString, max: 20 });
}

/** Run `fn` in a transaction; rolls back on any error. */
export async function tx<T>(db: Db, fn: (c: Tx) => Promise<T>): Promise<T> {
  const c = await db.connect();
  try {
    await c.query('begin');
    const r = await fn(c);
    await c.query('commit');
    return r;
  } catch (e) {
    await c.query('rollback').catch(() => {});
    throw e;
  } finally {
    c.release();
  }
}

/** Project-root folder, both when running from src/ (tsx) and from dist/src/ (built). */
export function rootPath(name: string) {
  const here = path.dirname(fileURLToPath(import.meta.url));
  for (const up of ['..', '../..']) { const p = path.join(here, up, name); if (fs.existsSync(p)) return p; }
  return path.join(here, '..', name);
}
const migrationsDir = rootPath('migrations');

export async function migrate(db: Db, log: (m: string) => void = () => {}) {
  await db.query('create table if not exists schema_migrations (name text primary key, applied_at timestamptz not null default now())');
  const done = new Set((await db.query('select name from schema_migrations')).rows.map((r) => r.name));
  const files = fs.readdirSync(migrationsDir).filter((f) => f.endsWith('.sql')).sort();
  for (const f of files) {
    if (done.has(f)) continue;
    const sql = fs.readFileSync(path.join(migrationsDir, f), 'utf8');
    await tx(db, async (c) => {
      await c.query(sql);
      await c.query('insert into schema_migrations(name) values ($1)', [f]);
    });
    log(`migration applied: ${f}`);
  }
}

/** Start an in-process PostgreSQL for local development and tests. */
export async function startEmbedded(opts: { port: number; dir: string; persistent: boolean; dbName: string }) {
  const { default: EmbeddedPostgres } = await import('embedded-postgres');
  const fresh = !fs.existsSync(path.join(opts.dir, 'PG_VERSION'));
  const server = new EmbeddedPostgres({
    databaseDir: opts.dir, user: 'postgres', password: 'mahalla', port: opts.port,
    persistent: opts.persistent, onLog: () => {}, onError: () => {},
  });
  if (fresh) await server.initialise();
  await server.start();
  if (fresh) await server.createDatabase(opts.dbName);
  return { server, url: `postgres://postgres:mahalla@localhost:${opts.port}/${opts.dbName}` };
}
