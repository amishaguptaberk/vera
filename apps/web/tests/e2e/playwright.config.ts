import { defineConfig } from '@playwright/test';
import { launchOptions } from '../parity/browser';

// Real end-to-end: the app on VERA_APP_PORT (default 3210) proxies /api to the real backend at VERA_API_ORIGIN.
const port = Number(process.env.VERA_APP_PORT ?? 3210);
export default defineConfig({
  testDir: '.',
  timeout: 60_000,
  workers: 1,
  use: { launchOptions, baseURL: `http://127.0.0.1:${port}`, viewport: { width: 1440, height: 900 } },
});
