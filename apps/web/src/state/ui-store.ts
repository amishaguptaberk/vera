import { useSyncExternalStore } from 'react';

// UI-only state: sidebar width and collapse persist in sessionStorage
// and are never sent to the server. The mobile drawer is in-memory only.
// (The prototype keeps collapse in localStorage; here it is per session.)

import { SIDEBAR_MAX, SIDEBAR_MIN } from '@/design-system/layout';

export { SIDEBAR_MAX, SIDEBAR_MIN };
export const SIDEBAR_DEFAULT = 220;
export const STORAGE_KEY = 'vera-ui';

export type UiState = {
  sidebarWidth: number;
  sidebarCollapsed: boolean;
  navDrawerOpen: boolean;
};

export const clampSidebarWidth = (w: number) => Math.max(SIDEBAR_MIN, Math.min(SIDEBAR_MAX, Math.round(w)));

const initial: UiState = { sidebarWidth: SIDEBAR_DEFAULT, sidebarCollapsed: false, navDrawerOpen: false };

function readPersisted(): Partial<UiState> {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Partial<UiState>;
    const out: Partial<UiState> = {};
    if (typeof parsed.sidebarWidth === 'number' && Number.isFinite(parsed.sidebarWidth)) out.sidebarWidth = clampSidebarWidth(parsed.sidebarWidth);
    if (typeof parsed.sidebarCollapsed === 'boolean') out.sidebarCollapsed = parsed.sidebarCollapsed;
    return out;
  } catch {
    return {};
  }
}

function persist(s: UiState) {
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ sidebarWidth: s.sidebarWidth, sidebarCollapsed: s.sidebarCollapsed }));
  } catch {
    // Storage may be unavailable (private mode, quota): the state just does not persist.
  }
}

let state: UiState = initial;
let hydrated = false;
const listeners = new Set<() => void>();

function ensureHydrated() {
  if (hydrated || typeof window === 'undefined') return;
  hydrated = true;
  state = { ...state, ...readPersisted() };
}

function set(patch: Partial<UiState>) {
  ensureHydrated();
  const next = { ...state, ...patch };
  if (next.sidebarWidth === state.sidebarWidth && next.sidebarCollapsed === state.sidebarCollapsed && next.navDrawerOpen === state.navDrawerOpen) return;
  const persisted = next.sidebarWidth !== state.sidebarWidth || next.sidebarCollapsed !== state.sidebarCollapsed;
  state = next;
  if (persisted) persist(state);
  listeners.forEach((l) => l());
}

export const uiActions = {
  setSidebarWidth: (w: number) => set({ sidebarWidth: clampSidebarWidth(w) }),
  setSidebarCollapsed: (collapsed: boolean) => set({ sidebarCollapsed: collapsed }),
  toggleSidebarCollapsed: () => set({ sidebarCollapsed: !(ensureHydrated(), state.sidebarCollapsed) }),
  setNavDrawerOpen: (open: boolean) => set({ navDrawerOpen: open }),
};

export function getUiState(): UiState {
  ensureHydrated();
  return state;
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

/** Re-reads sessionStorage and notifies subscribers. Test seam: simulates a fresh page load. */
export function reloadUiStateFromStorage() {
  hydrated = false;
  state = { ...initial };
  ensureHydrated();
  listeners.forEach((l) => l());
}

export function useUiState(): UiState {
  // The server (and the hydration pass) renders the defaults; the client then adopts the persisted state.
  return useSyncExternalStore(subscribe, getUiState, () => initial);
}
