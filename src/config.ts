// All settings come from environment variables (see .env.example).
const env = process.env;
const num = (v: string | undefined, d: number) => (v === undefined || v === '' ? d : Number(v));
const bool = (v: string | undefined, d: boolean) => (v === undefined || v === '' ? d : v === '1' || v.toLowerCase() === 'true');

export const config = {
  port: num(env.PORT, 3000),
  host: env.HOST || '0.0.0.0',
  databaseUrl: env.DATABASE_URL || '',
  /** Start a throw-away PostgreSQL inside the process (local development only). */
  embeddedDb: bool(env.EMBEDDED_DB, !env.DATABASE_URL),
  production: env.NODE_ENV === 'production',
  /** Nickname-only login for local testing. Never enable in production. */
  devLogin: bool(env.DEV_LOGIN, env.NODE_ENV !== 'production'),
  /** One-click guest accounts (tied to one browser via its session cookie). Safe in production. */
  guestLogin: bool(env.GUEST_LOGIN, false),
  telegramBotToken: env.TELEGRAM_BOT_TOKEN || '',
  telegramBotName: env.TELEGRAM_BOT_NAME || '',
  sessionDays: num(env.SESSION_DAYS, 30),
  /** Fill the city with demo neighbours on first seed so it doesn't look empty. */
  seedDemo: bool(env.SEED_DEMO, true),
  /** Length of one in-game day in real seconds (income is "per day"). 86400 = real day. */
  daySeconds: num(env.DAY_SECONDS, 86400),
  rateLimitPerMinute: num(env.RATE_LIMIT_PER_MINUTE, 120),
};

if (config.production && config.devLogin) {
  throw new Error('DEV_LOGIN must be off in production');
}
