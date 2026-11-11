import nextCoreWebVitals from 'eslint-config-next/core-web-vitals';
import nextTypescript from 'eslint-config-next/typescript';

// Layer rules between design-system, components, features, api, state and app.
// `@/api/schema` is deliberately not restricted: it is a generated .d.ts, so
// only types can come from it.
const layer = (message, ...groups) => ({
  'no-restricted-imports': ['error', { patterns: groups.map((group) => (Array.isArray(group) ? { group, message } : { ...group, message })) }],
});

const noPrototype = ['**/prototype', '**/prototype/**'];
// The whole API layer except the generated schema (types only).
// (The bare barrel is its own group: a gitignore-style parent match would defeat the negation.)
const apiBarrel = { regex: '(^|/)api/?$' };
const apiRuntime = ['@/api/**', '!@/api/schema', '**/api/**', '!**/api/schema'];
const state = ['@/state', '@/state/**', '**/state/**'];
const features = ['@/features', '@/features/**', '**/features/**'];
const app = ['@/app', '@/app/**', '**/app/**'];
const components = ['@/components', '@/components/**', '**/components/**'];
const designSystem = ['@/design-system', '@/design-system/**', '**/design-system/**'];
const lib = ['@/lib', '@/lib/**', '**/lib/**'];
const api = ['@/api', '@/api/**', '**/api', '**/api/**'];

// Dynamic import() bypasses no-restricted-imports, so the same layers are closed off with a syntax rule.
// `names` are the layer directories a file must not reach; api/schema (types only) stays allowed.
const noDynamicImport = (message, ...names) => {
  const alt = names.map((n) => (n === 'api' ? 'api(\\/(?!schema$).*)?' : `${n}(\\/.*)?`)).join('|');
  return {
    'no-restricted-syntax': ['error', { selector: `ImportExpression[source.value=/(^|\\/)(${alt})$/]`, message }],
  };
};

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
      'design-system imports nothing internal.',
      noPrototype, ['@/*'], components, features, state, app, lib, api,
    ),
  },
  {
    files: ['src/components/**/*.{ts,tsx}'],
    rules: layer(
      'components are presentational: they may import design-system, lib and types from api/schema only.',
      noPrototype, apiBarrel, apiRuntime, state, features, app,
    ),
  },
  {
    files: ['src/features/**/*.{ts,tsx}'],
    rules: layer('features may import components, api and state only.', noPrototype, app),
  },
  {
    files: ['src/app/**/*.{ts,tsx}'],
    rules: layer(
      'app composes features (and design-system); it must not reach into api or state.',
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
  {
    files: ['src/components/**/*.{ts,tsx}'],
    rules: noDynamicImport('components must not dynamic-import api, state, features or app.', 'api', 'state', 'features', 'app'),
  },
  {
    files: ['src/app/**/*.{ts,tsx}'],
    rules: noDynamicImport('app must not dynamic-import api, state, components or lib.', 'api', 'state', 'components', 'lib'),
  },
  {
    files: ['src/lib/**/*.{ts,tsx}'],
    rules: noDynamicImport('lib must not dynamic-import api, components, features, state or app.', 'api', 'components', 'features', 'state', 'app'),
  },
];

export default config;
