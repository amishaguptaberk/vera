// Local drafts store: unsaved edits to a communication draft survive refetch (local wins until saved/sent)
// and a page refresh (localStorage). Cleared after a successful save or send.
import { useCallback, useSyncExternalStore } from 'react';

export type LocalDraft = { subject?: string; body?: string; channel?: 'email' | 'portal' };

const PREFIX = 'vera.comms.draft.';
const keyOf = (caseId: string, itemId: string) => `${PREFIX}${caseId}.${itemId}`;
const listeners = new Set<() => void>();
const cache = new Map<string, { raw: string | null; value: LocalDraft | null }>();

function read(key: string): LocalDraft | null {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(key);
  } catch {
    raw = null;
  }
  const hit = cache.get(key);
  if (hit && hit.raw === raw) return hit.value;
  let value: LocalDraft | null = null;
  try {
    value = raw ? (JSON.parse(raw) as LocalDraft) : null;
  } catch {
    value = null;
  }
  cache.set(key, { raw, value });
  return value;
}

function write(key: string, value: LocalDraft | null) {
  try {
    if (value) window.localStorage.setItem(key, JSON.stringify(value));
    else window.localStorage.removeItem(key);
  } catch {
    /* storage unavailable: edits stay in memory for this render only */
  }
  listeners.forEach((l) => l());
}

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

export function useLocalDraft(caseId: string, itemId: string) {
  const key = keyOf(caseId, itemId);
  const draft = useSyncExternalStore(
    subscribe,
    () => read(key),
    () => null,
  );
  const update = useCallback((patch: LocalDraft) => write(key, { ...read(key), ...patch }), [key]);
  const clear = useCallback(() => write(key, null), [key]);
  return { draft, update, clear };
}
