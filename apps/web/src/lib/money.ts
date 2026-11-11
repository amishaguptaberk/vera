/** Display formatting only: integer cents from the API rendered as currency. No arithmetic on amounts. */
export function formatMoney(cents: number, currency = 'USD', digits: boolean | 'cents' = false): string {
  const whole = digits === true;
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: digits === 'cents' ? 2 : 0,
    maximumFractionDigits: whole ? 0 : 2,
  }).format(cents / 100);
}
