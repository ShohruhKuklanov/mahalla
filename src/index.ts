import path from 'node:path';
import { config } from './config.js';
import { createPool, migrate, startEmbedded } from './db.js';
import { seed } from './seed.js';
import { buildApp } from './server.js';
import { grantFounderCar } from './game.js';

async function main() {
  let url = config.databaseUrl;
  let embedded: { stop: () => Promise<void> } | null = null;
  if (config.embeddedDb) {
    const e = await startEmbedded({ port: 54330, dir: path.resolve(process.env.EMBEDDED_DB_DIR || '.data/pg'), persistent: true, dbName: 'mahalla' });
    embedded = e.server; url = e.url;
    console.log('Local PostgreSQL started (development mode, EMBEDDED_DB)');
  }
  const db = createPool(url);
  await migrate(db, console.log);
  await seed(db, { demo: config.seedDemo, log: console.log });
  await grantFounderCar(db);
  const app = await buildApp(db, { logger: config.production });
  await app.listen({ port: config.port, host: config.host });
  console.log(`Mahalla: http://localhost:${config.port}`);

  const stop = async () => { await app.close(); await db.end(); if (embedded) await embedded.stop(); process.exit(0); };
  process.on('SIGINT', stop); process.on('SIGTERM', stop);
}
main().catch((e) => { console.error(e); process.exit(1); });
