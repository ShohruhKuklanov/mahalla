// Nickname rules: 3–20 letters/digits/_/. ; no reserved or offensive words.
const RESERVED = ['admin', 'administrator', 'moderator', 'mahalla', 'susambil', 'support', 'system', 'claude'];
// Short starter list (uz/ru/en). Extend from a file in production; matching is substring-based on a normalized form.
const BLOCKED = ['axmoq', 'ahmoq', 'jalab', 'qotoq', 'suka', 'blyat', 'blya', 'pidor', 'xuy', 'huy', 'fuck', 'shit', 'bitch', 'nigger', 'hitler'];

const normalize = (s: string) =>
  s.toLowerCase()
    .replace(/[‘’ʻʼ`']/g, '')
    .replace(/0/g, 'o').replace(/1/g, 'i').replace(/3/g, 'e').replace(/4/g, 'a').replace(/5/g, 's').replace(/7/g, 't')
    .replace(/[._]/g, '');

export function checkNickname(raw: string): { ok: true; nick: string; lower: string } | { ok: false; code: string; message: string } {
  const nick = raw.trim();
  if (!/^[\p{L}\p{N}_.‘’ʻ]{3,20}$/u.test(nick)) {
    return { ok: false, code: 'nickname_format', message: 'Nik 3–20 belgi bo‘lishi kerak: harflar, raqamlar, _ yoki .' };
  }
  const n = normalize(nick);
  if (RESERVED.some((w) => n === w || n.startsWith(w))) return { ok: false, code: 'nickname_reserved', message: 'Bu nik band qilingan.' };
  if (BLOCKED.some((w) => n.includes(w))) return { ok: false, code: 'nickname_blocked', message: 'Bu nik shahar qoidalariga zid.' };
  return { ok: true, nick, lower: nick.toLowerCase() };
}

/** Text typed by users elsewhere (report reasons, later: building names, guestbook). */
export function isCleanText(s: string) {
  const n = normalize(s);
  return !BLOCKED.some((w) => n.includes(w));
}

export function suggestions(nick: string): string[] {
  const base = nick.replace(/[^\p{L}\p{N}_]/gu, '').slice(0, 15) || 'mehmon';
  const y = new Date().getFullYear() % 100;
  return [`${base}_${y}`, `${base}${Math.floor(10 + Math.random() * 89)}`, `${base}.uz`];
}
