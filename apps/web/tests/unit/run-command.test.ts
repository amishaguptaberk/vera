import { QueryClient, QueryObserver } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, caseKey, caseViewQuery, runCommand } from '@/api';
import intake from '../parity/fixtures/case-CHG-1042-intake.json';
import { mockFetch } from './helpers';

const action = intake.available_actions.find((a) => a.command === 'link_report')!;

afterEach(() => vi.unstubAllGlobals());

describe('runCommand', () => {
  it('posts the server-supplied key, the expected version and defaults merged with user input', async () => {
    const calls = mockFetch(() => ({ status: 'recorded', result: {}, event_ids: ['e1'], case: { ...intake, case_version: 2 } }));
    const qc = new QueryClient();
    const out = await runCommand(qc, 'CHG-1042', 1, action, { statement: 'Same charge' });
    expect(calls[0].method).toBe('POST');
    expect(calls[0].url).toBe('/api/cases/CHG-1042/commands/link_report');
    expect(JSON.parse(calls[0].body!)).toEqual({
      expected_case_version: 1,
      idempotency_key: 'report:REP-1043',
      payload: { report_id: 'REP-1043', statement: 'Same charge' },
    });
    expect(out.case.case_version).toBe(2);
  });

  it('on 409 stale_case_version refetches the case once and does not retry the command', async () => {
    const calls = mockFetch((c) =>
      c.method === 'POST'
        ? new Response(JSON.stringify({ code: 'stale_case_version', message: 'The case changed.', case_version: 3 }), { status: 409 })
        : { ...intake, case_version: 3 },
    );
    const qc = new QueryClient();
    // The workspace observes the case query (as useCaseView does), seeded with the version the action came from.
    qc.setQueryData(caseKey('CHG-1042'), intake);
    const observer = new QueryObserver(qc, { ...caseViewQuery('CHG-1042'), refetchInterval: false, staleTime: Infinity });
    const unsubscribe = observer.subscribe(() => {});
    const err = await runCommand(qc, 'CHG-1042', 1, intake.available_actions[0]).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe('stale_case_version');
    expect((err as ApiError).caseVersion).toBe(3);
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1);
    expect(calls.filter((c) => c.method === 'GET' && c.url === '/api/cases/CHG-1042')).toHaveLength(1);
    expect((qc.getQueryData(caseKey('CHG-1042')) as { case_version: number }).case_version).toBe(3);
    unsubscribe();
  });
});
