import { z } from 'zod';

/**
 * A player's 3D avatar: only choices, never images. The client draws it from the shared MakeHuman bodies
 * (web/people/avatar-{m,f,n}.js). Every field has a default so older or partial drafts still load.
 * Keep the option lists in step with AV_OPTIONS in web/index.html.
 */
const hex = z.string().regex(/^#[0-9a-fA-F]{6}$/, 'rang #rrggbb ko‘rinishida bo‘lsin');
export const AVATAR_VERSION = 1;
export const avatarSchema = z.object({
  v: z.literal(AVATAR_VERSION).default(AVATAR_VERSION),
  body: z.enum(['m', 'f', 'n']).default('n'),                          // presentation: masculine / feminine / neutral
  face: z.enum(['oval', 'round', 'square', 'long', 'heart', 'diamond', 'triangle', 'rect', 'full', 'lean', 'chin']).default('oval'),
  skin: hex.default('#c99a78'),
  eyes: z.enum(['normal', 'big', 'small']).default('normal'),
  eyeColor: hex.default('#4a3426'),
  brows: z.enum(['thin', 'normal', 'thick', 'arched', 'straight', 'angled', 'bushy', 'short', 'uni', 'natural']).default('normal'),
  beard: z.enum(['none', 'stubble', 'mustache', 'goatee', 'chin', 'short', 'full', 'long']).default('none'),
  beardColor: hex.default('#2a1d15'),
  nose: z.enum(['normal', 'narrow', 'wide', 'long']).default('normal'),
  mouth: z.enum(['normal', 'small', 'wide', 'full']).default('normal'),
  hair: z.enum(['short', 'mid', 'long', 'bun', 'bald']).default('short'),
  hairColor: hex.default('#2a1d15'),
  outfit: z.enum(['tee', 'shirt', 'shorts', 'skirt', 'jacket', 'chopon']).default('tee'),
  top: hex.default('#f2f0ea'),
  bottom: hex.default('#2c3e5c'),
  outer: hex.default('#3a4a5c'),
  shoes: hex.default('#1c1c1e'),
  glasses: z.enum(['none', 'round', 'square', 'sun']).default('none'),
  hat: z.enum(['none', 'doppi', 'cap', 'wide']).default('none'),
  hatColor: hex.default('#111111'),
}).strict();
export type Avatar = z.infer<typeof avatarSchema>;

/** Parse stored JSON leniently: anything unreadable becomes null (the editor then starts fresh). */
export function readAvatar(v: unknown): Avatar | null {
  if (v == null) return null;
  const r = avatarSchema.safeParse(v);
  return r.success ? r.data : null;
}
