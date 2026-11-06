-- Allow "guest" accounts (a new account bound to one browser, for the public beta before Telegram is set up).
alter table auth_identities drop constraint auth_identities_provider_check;
alter table auth_identities add constraint auth_identities_provider_check
  check (provider in ('telegram','google','phone','dev','bot','guest'));
