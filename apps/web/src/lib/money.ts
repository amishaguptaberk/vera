/** Display formatting only: integer cents from the API rendered as currency. No arithmetic on amounts. */
export function formatMoney(cents: number, currency = 'USD', whole = false): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: whole ? 0 : 2,
  }).format(cents / 100);
}
