-- Demo neighbour "Gulnoza" becomes "Jahongir" (same bot, same house; only the name over it changes).
-- Skipped if a real player already uses the name Jahongir.
update users set nickname = 'Jahongir', nickname_lower = 'jahongir'
 where role = 'bot' and nickname_lower = 'gulnoza'
   and not exists (select 1 from users u2 where u2.nickname_lower = 'jahongir');
update auth_identities set subject = 'Jahongir'
 where provider = 'bot' and subject = 'Gulnoza'
   and exists (select 1 from users u where u.id = auth_identities.user_id and u.nickname_lower = 'jahongir');
