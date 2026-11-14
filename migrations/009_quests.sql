-- City quests: each finished once per player; the reward is a normal ledger movement.
create table if not exists quest_completions (
  user_id      bigint not null references users(id) on delete cascade,
  quest_id     text   not null,
  reward       integer not null check (reward >= 0),
  completed_at timestamptz not null default now(),
  primary key (user_id, quest_id)
);
alter table transactions drop constraint if exists transactions_type_check;
alter table transactions add constraint transactions_type_check
  check (type in ('signup_bonus','plot_buy','plot_sale','fee','build','income','refund','admin_adjust','car_buy','car_change','quest_reward'));
