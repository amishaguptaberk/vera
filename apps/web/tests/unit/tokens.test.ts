import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const css = readFileSync(path.resolve(__dirname, '../../src/design-system/tokens.css'), 'utf8');

function token(name: string): string | undefined {
  const m = css.match(new RegExp(`--${name}:\\s*([^;]+);`));
  return m?.[1].trim().toLowerCase();
}

// Handoff §9.1 (and §9.3 / §9.4 literals).
const colors: Record<string, string> = {
  ink: '#0c0a08',
  ink2: '#3b3a39',
  mute: '#6f6c68',
  canvas: '#f4f2f0',
  paper: '#ffffff',
  rule: '#e5e7eb',
  rule2: '#efede9',
  cobalt: '#2446c7',
  'cobalt-wash': '#eef2fc',
  chart: '#e4f222',
  ok: '#1d6a43',
  warn: '#8a5300',
  'warn-icon': '#b7791f',
  bad: '#b42318',
  'btn-dark': '#1a1919',
  'task-card-border': '#d9d6d1',
  'btn-border': '#d3d3d3',
};

describe('tokens.css matches Handoff §9', () => {
  it.each(Object.entries(colors))('--%s is %s', (name, value) => {
    expect(token(name)).toBe(value);
  });

  // Handoff §9.2 typography.
  const typography: Record<string, string> = {
    'font-size-base': '14px',
    'line-height-base': '1.5',
    'font-size-label': '12px',
    'font-size-title-page': '22px',
    'font-size-title-task': '19px',
    'font-size-title-section': '14px',
    'font-size-metric': '22px',
    'font-weight-regular': '400',
    'font-weight-medium': '500',
    'font-weight-semibold': '600',
  };
  // Handoff §9.3 spacing (4px grid, gaps 8/12/16/20/24, gutter 24px) and radius.
  const spacing: Record<string, string> = {
    'space-1': '4px',
    'space-2': '8px',
    'space-3': '12px',
    'space-4': '16px',
    'space-5': '20px',
    'space-6': '24px',
    gutter: '24px',
    'radius-chip': '6px',
    'radius-input': '8px',
    'radius-panel': '12px',
  };
  // Handoff §9.5 motion.
  const motion: Record<string, string> = {
    ease: 'cubic-bezier(0.2, 0.8, 0.2, 1)',
    'duration-local': '220ms',
    'duration-icon': '200ms',
    'duration-drawer': '220ms',
    'duration-connector': '600ms',
  };

  it.each(Object.entries({ ...typography, ...spacing, ...motion }))('--%s is %s', (name, value) => {
    expect(token(name)).toBe(value);
  });

  it('uses the monospace stack and Inter for the font families (§9.2)', () => {
    expect(token('font-sans')).toMatch(/^'inter'/);
    expect(token('font-mono')).toMatch(/^ui-monospace/);
  });

  it('shrinks the page gutter to 16px at <=1279px (§9.3)', () => {
    expect(css).toMatch(/@media \(max-width: 1279px\)\s*\{\s*:root\s*\{\s*--gutter:\s*16px;/);
  });
});
