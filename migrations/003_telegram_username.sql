-- Owner name over buildings: the Telegram @username (shown only while show_telegram is on).
alter table users add column telegram_username text;
alter table users add column show_telegram boolean not null default true;
