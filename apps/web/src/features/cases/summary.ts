import type { SummaryBody } from '@/api';

/** One summary tile, exactly as the API states it: amount, count, basis and definition are passed through. */
export type SummaryTile = {
  key: string;
  label: string;
  amountCents: number;
  currency: string;
  count: number | null;
  basis: string | null;
  definition: string | null;
  primary: boolean;
};

// Gross is the primary metric; net sits beside it. Order is display order only.
const ORDER: readonly (readonly [string, string])[] = [
  ['gross_exposure', 'Gross exposure'],
  ['net_exposure', 'Net exposure'],
  ['temporary_credit', 'Temporary credit'],
  ['confirmed_recoveries', 'Confirmed recoveries'],
  ['due_today', 'Due today'],
  ['overdue', 'Overdue'],
];

const isObj = (x: unknown): x is Record<string, unknown> => typeof x === 'object' && x !== null;
const num = (x: unknown) => (typeof x === 'number' && Number.isFinite(x) ? x : null);
const str = (x: unknown) => (typeof x === 'string' && x ? x : null);

/** Metrics the body does not contain are not shown; nothing is computed. */
export function summaryTiles(body: SummaryBody | undefined): SummaryTile[] {
  if (!body) return [];
  const out: SummaryTile[] = [];
  for (const [key, label] of ORDER) {
    const m = (body as Record<string, unknown>)[key];
    if (!isObj(m)) continue;
    const amount = num(m.amount_cents);
    if (amount === null) continue;
    out.push({ key, label, amountCents: amount, currency: str(m.currency) ?? 'USD', count: num(m.count), basis: str(m.basis), definition: str(m.definition), primary: key === 'gross_exposure' });
  }
  return out;
}
