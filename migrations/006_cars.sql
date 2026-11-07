-- Cars: every player may own one car (the Chevrolet Tracker model), parked in front of their house.
-- A plate is unique in the city: region code + text (standard "Y095AB" or a custom inscription).
create table cars (
  id           bigserial primary key,
  owner_id     bigint not null unique references users(id) on delete cascade,
  model        text   not null default 'tracker' check (model in ('tracker')),
  color        text   not null check (color ~ '^#[0-9a-f]{6}$'),
  plate_region text   not null check (plate_region ~ '^[0-9]{2}$'),
  plate_text   text   not null check (plate_text ~ '^[A-Z0-9]{1,8}$'),
  plate_kind   text   not null check (plate_kind in ('standard','custom')),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  unique (plate_region, plate_text)
);

alter table transactions drop constraint if exists transactions_type_check;
alter table transactions add constraint transactions_type_check
  check (type in ('signup_bonus','plot_buy','plot_sale','fee','build','income','refund','admin_adjust','car_buy','car_change'));
