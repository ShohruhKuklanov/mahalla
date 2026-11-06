-- Mahalla: initial schema
-- Money rule: every coin movement is a row in `transactions`; wallets.balance is the running total
-- and can never go negative.

create table users (
  id              bigserial primary key,
  nickname        text,
  nickname_lower  text unique,
  avatar_id       int  not null default 1,
  role            text not null default 'user'   check (role in ('user','moderator','admin','bot')),
  status          text not null default 'active' check (status in ('active','banned')),
  level           int  not null default 1,
  birth_confirmed_16 boolean not null default false,
  created_at      timestamptz not null default now(),
  last_seen_at    timestamptz not null default now()
);

create table auth_identities (
  id         bigserial primary key,
  user_id    bigint not null references users(id) on delete cascade,
  provider   text   not null check (provider in ('telegram','google','phone','dev','bot')),
  subject    text   not null,
  created_at timestamptz not null default now(),
  unique (provider, subject)
);

create table sessions (
  id          bigserial primary key,
  user_id     bigint not null references users(id) on delete cascade,
  token_hash  text   not null unique,
  created_at  timestamptz not null default now(),
  expires_at  timestamptz not null
);
create index sessions_user_idx on sessions(user_id);

create table wallets (
  user_id    bigint primary key references users(id) on delete cascade,
  balance    bigint not null check (balance >= 0),
  updated_at timestamptz not null default now()
);

create table transactions (
  id              bigserial primary key,
  user_id         bigint not null references users(id) on delete cascade,
  amount          bigint not null,
  type            text   not null check (type in ('signup_bonus','plot_buy','plot_sale','fee','build','income','refund','admin_adjust')),
  ref_type        text,
  ref_id          bigint,
  balance_after   bigint not null,
  idempotency_key text,
  created_at      timestamptz not null default now(),
  unique (user_id, idempotency_key)
);
create index transactions_user_idx on transactions(user_id, created_at desc);

create table districts (
  id     int primary key,
  name   text not null,
  status text not null default 'open' check (status in ('open','locked'))
);

create table zones (
  code       text primary key check (code in ('res','com','cen')),
  name       text not null,
  base_price int  not null check (base_price > 0)
);

create table plots (
  id              int primary key,
  district_id     int  not null references districts(id),
  zone            text not null references zones(code),
  x               real not null,
  z               real not null,
  size            text not null default 'S' check (size in ('S','M','L')),
  location_factor real not null default 1,
  owner_id        bigint references users(id),
  status          text not null default 'empty' check (status in ('empty','owned','frozen')),
  purchased_at    timestamptz,
  version         int  not null default 0,
  unique (x, z),
  check ((status = 'empty') = (owner_id is null) or status = 'frozen')
);
create index plots_owner_idx on plots(owner_id);

create table building_templates (
  code           text primary key,
  name           text not null,
  zones          text[] not null,
  cost           int  not null check (cost > 0),
  build_seconds  int  not null check (build_seconds >= 0),
  income_per_day int  not null check (income_per_day >= 0),
  active         boolean not null default true
);

create table buildings (
  id                bigserial primary key,
  plot_id           int not null unique references plots(id),
  template          text not null references building_templates(code),
  level             int not null default 1 check (level between 1 and 3),
  rotation          smallint not null default 0 check (rotation between 0 and 3),
  color             text not null,
  accent            text not null,
  custom_name       text,
  status            text not null default 'active' check (status in ('active','hidden')),
  built_at          timestamptz not null default now(),
  ready_at          timestamptz not null,
  last_collected_at timestamptz not null
);

create table listings (
  id         bigserial primary key,
  plot_id    int    not null references plots(id),
  seller_id  bigint not null references users(id),
  price      bigint not null check (price > 0),
  status     text   not null default 'active' check (status in ('active','sold','cancelled')),
  buyer_id   bigint references users(id),
  created_at timestamptz not null default now(),
  sold_at    timestamptz
);
create unique index listings_one_active on listings(plot_id) where status = 'active';

create table likes (
  user_id    bigint not null references users(id) on delete cascade,
  plot_id    int    not null references plots(id),
  created_at timestamptz not null default now(),
  primary key (user_id, plot_id)
);

create table reports (
  id          bigserial primary key,
  reporter_id bigint not null references users(id),
  target_type text   not null check (target_type in ('user','plot')),
  target_id   bigint not null,
  reason      text   not null,
  status      text   not null default 'open' check (status in ('open','resolved','rejected')),
  created_at  timestamptz not null default now(),
  resolved_by bigint references users(id),
  resolved_at timestamptz
);
create index reports_open_idx on reports(status, created_at);

create table moderation_actions (
  id             bigserial primary key,
  moderator_id   bigint not null references users(id),
  target_user_id bigint references users(id),
  target_plot_id int references plots(id),
  action         text not null check (action in ('warn','force_rename','ban','unban','hide_building','resolve_report','reject_report')),
  reason         text,
  created_at     timestamptz not null default now()
);

create table economy_config (
  key        text primary key,
  value      jsonb not null,
  updated_at timestamptz not null default now()
);
