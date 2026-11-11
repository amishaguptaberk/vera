import { describe, expect, it } from 'vitest';
import { addPair, type RailPair } from '@/features/decision/rail-state';

const ans = (answer: string, ids: string[] = [], signature?: string) => ({ answer, citations: ids.map((record_id) => ({ record_id, version: 1, field: 'phone' })), refused: false, signature });

describe('Vera rail pairs', () => {
  it('repeating a question with the same signature replaces the earlier pair', () => {
    let pairs: RailPair[] = [];
    pairs = addPair(pairs, 'Who do I call?', ans('The approved contact is Priya Shah · (415) 555-0182.', ['PRF-4418'], 'contact:1'));
    pairs = addPair(pairs, 'Why is credit blocked?', ans('Verification is missing.', [], 'credit_blocked:1'));
    pairs = addPair(pairs, 'who do i call', ans('The approved contact is Priya Shah · (415) 555-0182.', ['PRF-4418'], 'contact:1'));
    expect(pairs.map((p) => p.question)).toEqual(['Why is credit blocked?', 'who do i call']);
  });
  it('a different answer is a new pair', () => {
    let pairs: RailPair[] = [];
    pairs = addPair(pairs, 'Status?', ans('Pending', [], 's:1'));
    pairs = addPair(pairs, 'Status?', ans('Issued', [], 's:2'));
    expect(pairs).toHaveLength(2);
  });
});
