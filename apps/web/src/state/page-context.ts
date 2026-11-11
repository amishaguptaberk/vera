import { useSyncExternalStore } from 'react';

// In-memory context a page lends to the shell: the top bar title (prototype `ctxTitle` for a case) and the
// Vera rail toggle (prototype `.vera-b`, shown in the top bar below 1280px). Never persisted or sent anywhere.
export type PageContext = { title: string | null; rail: boolean; railOpen: boolean };

const initial: PageContext = { title: null, rail: false, railOpen: false };
let state: PageContext = initial;
const listeners = new Set<() => void>();

function set(patch: Partial<PageContext>) {
  const next = { ...state, ...patch };
  if (next.title === state.title && next.rail === state.rail && next.railOpen === state.railOpen) return;
  state = next;
  listeners.forEach((l) => l());
}

export const pageContextActions = {
  /** A page claims the shell context; returns the cleanup that releases it. */
  claim: (title: string | null, rail: boolean) => {
    set({ title, rail });
    return () => set({ title: null, rail: false, railOpen: false });
  },
  setRailOpen: (open: boolean) => set({ railOpen: open }),
  toggleRail: () => set({ railOpen: !state.railOpen }),
};

export const getPageContext = () => state;

function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function usePageContext(): PageContext {
  return useSyncExternalStore(subscribe, getPageContext, () => initial);
}
