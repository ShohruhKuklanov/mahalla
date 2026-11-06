// Starts a throw-away PostgreSQL, runs the API tests against it in a child process, stops it.
import { spawnSync } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import { startEmbedded } from '../src/db.js';

const dir = path.join(os.tmpdir(), `mahalla-test-pg-${process.pid}-${Date.now()}`); // must not exist yet
const port = 54000 + Math.floor(Math.random() * 900);
const pg = await startEmbedded({ port, dir, persistent: false, dbName: 'test' });
const r = spawnSync(process.execPath, ['--import', 'tsx', '--test', '--test-reporter=spec', 'test/api.test.ts'], {
  stdio: 'inherit', env: { ...process.env, TEST_DATABASE_URL: pg.url },
});
await pg.server.stop();
process.exit(r.status ?? 1);
