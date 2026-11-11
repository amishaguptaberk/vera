import { afterEach, beforeEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import { reloadUiStateFromStorage } from '@/state/ui-store';

beforeEach(() => {
  window.sessionStorage.clear();
  reloadUiStateFromStorage();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
