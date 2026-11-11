import nextCoreWebVitals from 'eslint-config-next/core-web-vitals';
import nextTypescript from 'eslint-config-next/typescript';

// Layer rules: docs/frontend-architecture.md §3.
// `@/api/schema` is deliberately not restricted: it is a generated .d.ts, so
// only types can come from it.
const layer = (message, ...groups) => ({
  'no-restricted-imports': ['error', { patterns: groups.map((group) => (Array.isArray(group) ? { group, message } : { ...group, message })) }],
});

const noPrototype = ['**/prototype', '**/prototype/**'];
// The whole API layer except the generated schema (types only).
// (The bare barrel is its own group: a gitignore-style parent match would defeat the negation.)
const apiBarrel = { regex: '(^|/)api$' };
const apiRuntime = ['@/api/**', '!@/api/schema', '**/api/**', '!**/api/schema'];
const state = ['@/state', '@/state/**', '**/state/**'];
const features = ['@/features', '@/features/**', '**/features/**'];
const app = ['@/app', '@/app/**', '**/app/**'];
const components = ['@/components', '@/components/**', '**/components/**'];
const designSystem = ['@/design-system', '@/design-system/**', '**/design-system/**'];
const lib = ['@/lib', '@/lib/**', '**/lib/**'];
const api = ['@/api', '@/api/**', '**/api', '**/api/**'];

const config = [
  { ignores: ['.next/**', 'node_modules/**', 'prototype/**', 'test-results/**', 'next-env.d.ts'] },
  ...nextCoreWebVitals,
  ...nextTypescript,
  {
    files: ['src/**/*.{ts,tsx}'],
    rules: layer('The prototype is a read-only reference and must never be imported.', noPrototype),
  },
  {
    files: ['src/design-system/**/*.{ts,tsx}'],
    rules: layer(
      'design-system imports nothing internal (architecture §3).',
      noPrototype, ['@/*'], components, features, state, app, lib, api,
    ),
  },
  {
    files: ['src/components/**/*.{ts,tsx}'],
    rules: layer(
      'components are presentational: they may import design-system, lib and types from api/schema only (architecture §3).',
      noPrototype, apiBarrel, apiRuntime, state, features, app,
    ),
  },
  {
    files: ['src/features/**/*.{ts,tsx}'],
    rules: layer('features may import components, api and state only (architecture §3).', noPrototype, app),
  },
  {
    files: ['src/app/**/*.{ts,tsx}'],
    rules: layer(
      'app composes features (and design-system for the F0 placeholder); it must not reach into api or state.',
      noPrototype, apiBarrel, apiRuntime, state, components, lib,
    ),
  },
  {
    files: ['src/api/**/*.{ts,tsx}'],
    rules: layer('api depends on the generated schema only.', noPrototype, designSystem, components, features, state, app, lib),
  },
  {
    files: ['src/lib/**/*.{ts,tsx}'],
    rules: layer('lib is leaf utilities: it must not import api, components, features, state or app.', noPrototype, apiBarrel, apiRuntime, components, features, state, app),
  },
  {
    files: ['src/state/**/*.{ts,tsx}'],
    rules: layer('state must not import components, features or app.', noPrototype, components, features, app),
  },
];

export default config;
