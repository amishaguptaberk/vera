// Maps the session's active role onto the role selector's three prototype views. Derived on every render;
// no role is stored client-side (the server session is the source of truth).
export type RoleView = 'analyst' | 'cardholder' | 'reviewer';

const VIEW_BY_ROLE: Record<string, RoleView> = {
  analyst: 'analyst',
  ops_admin: 'analyst',
  cardholder: 'cardholder',
  reviewer: 'reviewer',
  card_admin: 'reviewer',
};

export const viewForRole = (role: string): RoleView | null => VIEW_BY_ROLE[role] ?? null;

/** Prototype `ctxTitle` (Main.dc.html:2875); `pageTitle` is the case title the open case screen lends the shell. */
export function contextTitle(view: RoleView | null, pathname: string, pageTitle: string | null = null): string {
  if (view === 'cardholder') return 'Charge review';
  if (view === 'reviewer') return 'Approvals';
  if (pathname === '/automations' || pathname.startsWith('/automations/')) return 'Automations';
  return pageTitle ?? '';
}
