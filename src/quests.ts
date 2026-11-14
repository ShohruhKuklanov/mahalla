import { Db, tx } from './db.js';
import { E } from './errors.js';

/**
 * City quests: the steps are played in the client (web/index.html, QUESTS); the server only knows each quest's id and
 * reward, pays it once per player, and remembers which ones are done. Rewards are ordinary coins (the existing economy).
 * Keep ids and rewards in step with QUESTS in web/index.html.
 */
export const QUEST_REWARDS: Record<string, number> = {
  welcome: 150,
  chorsu: 250,
  lost_key: 300,
  tv_tower: 250,
  test_drive: 400,
  port: 200,
};

export async function questsDone(db: Db, userId: number): Promise<string[]> {
  return (await db.query('select quest_id from quest_completions where user_id = $1 order by completed_at', [userId])).rows.map((r) => r.quest_id);
}

export async function completeQuest(db: Db, userId: number, questId: string) {
  const reward = QUEST_REWARDS[questId];
  if (reward === undefined) throw E.notFound('Bunday vazifa yo‘q');
  return tx(db, async (c) => {
    await c.query('select 1 from wallets where user_id = $1 for update', [userId]);
    const ins = await c.query('insert into quest_completions(user_id, quest_id, reward) values ($1,$2,$3) on conflict do nothing returning quest_id', [userId, questId, reward]);
    if (!ins.rows.length) {
      const bal = (await c.query('select balance from wallets where user_id = $1', [userId])).rows[0]?.balance ?? 0;
      return { questId, reward: 0, already: true, balance: bal };
    }
    const r = await c.query('update wallets set balance = balance + $2, updated_at = now() where user_id = $1 returning balance', [userId, reward]);
    if (!r.rows.length) throw E.notFound('Hamyon topilmadi');
    await c.query('insert into transactions(user_id,amount,type,ref_type,ref_id,balance_after,idempotency_key) values ($1,$2,$3,$4,$5,$6,$7)',
      [userId, reward, 'quest_reward', null, null, r.rows[0].balance, null]);
    return { questId, reward, already: false, balance: r.rows[0].balance as number };
  });
}
