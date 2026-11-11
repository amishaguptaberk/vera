import { describe, expect, it } from 'vitest';
import { ApiError } from '@/api';
import { retryTransient } from '@/features/shell/AppProviders';

describe('default query retry', () => {
  it('never retries a 403 or a 404 (denied panel / route not deployed), retries transient failures twice', () => {
    const err = (status: number) => new ApiError(status, { code: 'x', message: 'x' });
    expect(retryTransient(0, err(403))).toBe(false);
    expect(retryTransient(0, err(404))).toBe(false);
    expect(retryTransient(0, err(502))).toBe(true);
    expect(retryTransient(2, err(502))).toBe(false);
    expect(retryTransient(0, new TypeError('fetch failed'))).toBe(true);
  });
});
