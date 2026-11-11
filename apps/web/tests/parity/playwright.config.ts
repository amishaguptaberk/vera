import { defineConfig } from '@playwright/test';
import path from 'node:path';
import { launchOptions } from './browser';

/** Ports are configurable so several checkouts can run parity side by side. */
export const APP_PORT = Number(process.env.VERA_APP_PORT ?? 3100);
export const PROTOTYPE_PORT = Number(process.env.VERA_PROTOTYPE_PORT ?? 3101);

const webRoot = path.resolve(__dirname, '../..');
const prototypeDir = path.join(webRoot, 'prototype');

export default defineConfig({
  testDir: __dirname,
  testMatch: '*.spec.ts',
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  outputDir: path.join(webRoot, 'test-results'),
  use: { launchOptions },
  webServer: [
    {
      // Requires `npm run build` first (documented in README).
      command: `npx next start -p ${APP_PORT} -H 127.0.0.1`,
      cwd: webRoot,
      url: `http://127.0.0.1:${APP_PORT}/`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `python3 -m http.server ${PROTOTYPE_PORT} --bind 127.0.0.1 --directory ${prototypeDir}`,
      url: `http://127.0.0.1:${PROTOTYPE_PORT}/Main.dc.html`,
      stdout: 'ignore',
      stderr: 'ignore',
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
