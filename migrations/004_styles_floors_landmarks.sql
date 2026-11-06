-- Buildings get a style, a floor count and a roof; landmark copies (lm_*) are unique per city.
-- Demo neighbours: only one showcase building per mahalla is kept, the rest of their plots become free land.

alter table buildings add column style  text not null default 'modern' check (style in ('modern','hitech','milliy'));
alter table buildings add column floors int  not null default 1        check (floors between 1 and 60);
alter table buildings add column roof   text not null default 'flat'   check (roof in ('flat','gable','hip','dome','garden','antenna','helipad','spire','none'));

update buildings set style = 'milliy', floors = 1,  roof = 'gable'   where template = 'house';
update buildings set style = 'milliy', floors = 2,  roof = 'hip'     where template = 'villa';
update buildings set style = 'modern', floors = 5,  roof = 'flat'    where template = 'flat';
update buildings set style = 'modern', floors = 2,  roof = 'flat'    where template = 'shop';
update buildings set style = 'milliy', floors = 1,  roof = 'dome'    where template = 'cafe';
update buildings set style = 'hitech', floors = 7,  roof = 'antenna' where template = 'office';
update buildings set style = 'hitech', floors = 16, roof = 'antenna' where template = 'tower';
-- colours must come from the new style palettes
update buildings set color = '#ecd9b4' where style = 'milliy' and color not in ('#ecd9b4','#f2e6d0','#e0bf94','#f6efe2','#d9a882','#eadcc0');
update buildings set color = '#f4f1ea' where style = 'modern' and color not in ('#f4f1ea','#e9e4da','#dfe3e8','#efd9c8','#cfe0ea','#d6e6d4','#3a4049');
update buildings set color = '#cfe3ee' where style = 'hitech' and color not in ('#cfe3ee','#b7d3e3','#d9e2e8','#c2cfdb','#bfdcd5','#e3dccb');

create unique index buildings_landmark_unique on buildings(template) where template like 'lm\_%';

-- ---- demo clean-up (no-op on a fresh database: demo neighbours are seeded after migrations) ----
create temporary table _keep on commit drop as
  select distinct on (p.district_id) p.id, p.district_id
  from plots p join users u on u.id = p.owner_id join buildings b on b.plot_id = p.id
  where u.role = 'bot'
  order by p.district_id, (p.zone = 'res'), p.id;
create temporary table _drop on commit drop as
  select p.id from plots p join users u on u.id = p.owner_id
  where u.role = 'bot' and p.id not in (select id from _keep);

delete from listings where plot_id in (select id from _drop) or seller_id in (select id from users where role = 'bot');
delete from likes     where plot_id in (select id from _drop);
delete from buildings where plot_id in (select id from _drop);
update plots set owner_id = null, status = 'empty', purchased_at = null, version = version + 1 where id in (select id from _drop);

-- one showcase per mahalla, one per style
update buildings b set template = 'cafe',   style = 'milliy', floors = 2,  roof = 'dome',    color = '#ecd9b4', accent = '#2a9d8f'
  from _keep k where b.plot_id = k.id and k.district_id = 0;
update buildings b set template = 'office', style = 'hitech', floors = 12, roof = 'helipad', color = '#b7d3e3', accent = '#1f6fb2'
  from _keep k where b.plot_id = k.id and k.district_id = 1;
update buildings b set template = 'flat',   style = 'modern', floors = 9,  roof = 'garden',  color = '#f4f1ea', accent = '#e08a2c'
  from _keep k where b.plot_id = k.id and k.district_id = 2;
