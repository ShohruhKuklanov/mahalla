/** Errors shown to players carry a stable code (for the client) and an Uzbek message (for people). */
export class AppError extends Error {
  constructor(public status: number, public code: string, message: string, public extra: Record<string, unknown> = {}) {
    super(message);
  }
}
export const E = {
  auth: () => new AppError(401, 'unauthorized', 'Avval tizimga kiring.'),
  banned: () => new AppError(403, 'banned', 'Hisobingiz bloklangan.'),
  forbidden: () => new AppError(403, 'forbidden', 'Bu amal uchun ruxsat yo‘q.'),
  nickRequired: () => new AppError(428, 'nickname_required', 'Avval nik tanlang.'),
  notFound: (what = 'Topilmadi') => new AppError(404, 'not_found', what),
  funds: (need: number) => new AppError(402, 'insufficient_funds', `Tanga yetmaydi: yana ${need} kerak.`, { need }),
  bad: (code: string, msg: string, extra?: Record<string, unknown>) => new AppError(400, code, msg, extra),
  conflict: (code: string, msg: string, extra?: Record<string, unknown>) => new AppError(409, code, msg, extra),
};
