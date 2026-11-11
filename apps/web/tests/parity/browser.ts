import { existsSync } from 'node:fs';

const SYSTEM_CHROME = process.env.VERA_CHROME_PATH ?? '/usr/bin/google-chrome';

/** Launch options: system Chrome when present (offline dev boxes), else Playwright's bundled chromium (CI). */
export const launchOptions = existsSync(SYSTEM_CHROME)
  ? { executablePath: SYSTEM_CHROME, args: ['--no-sandbox'] }
  : {};
