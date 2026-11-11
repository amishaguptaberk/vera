import { render } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { StatusSlot, SLOT_STATES } from '@/design-system/primitives';
import { slotMarkup } from '../support/slot-markup';

const css = readFileSync(path.resolve(__dirname, '../../src/design-system/primitives/StatusSlot.module.css'), 'utf8');
const tokens = readFileSync(path.resolve(__dirname, '../../src/design-system/tokens.css'), 'utf8');

/** Declarations of the first rule whose selector list is exactly `selector`. */
function rule(selector: string): string {
  const m = css.match(new RegExp(`(?:^|\\})\\s*${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\{([^}]*)\\}`, 'm'));
  if (!m) throw new Error(`no rule ${selector}`);
  return m[1];
}

describe('StatusSlot', () => {
  it('has the six states', () => {
    expect([...SLOT_STATES]).toEqual(['idle', 'review', 'wait', 'block', 'done', 'work']);
  });

  it.each(SLOT_STATES)('renders the %s state with the same slot element and class-driven size', (state) => {
    const { container } = render(<StatusSlot state={state} />);
    const slot = container.firstElementChild as HTMLElement;
    // Same markup the Playwright measurement uses (class names un-hashed).
    expect(slot.outerHTML.replace(/_([a-z]+)_[0-9a-f]+/g, '$1')).toBe(slotMarkup(state));
    expect(slot.getAttribute('data-state')).toBe(state);
    expect(slot.getAttribute('aria-hidden')).toBe('true');
    expect(slot.children).toHaveLength(SLOT_STATES.length);
    expect(slot.querySelectorAll('[class*="_on_"]')).toHaveLength(1);
  });

  it('the slot box is fixed by the .slot rule (20x20 token, flex none) and no state rule can change it', () => {
    expect(tokens).toMatch(/--slot-size:\s*20px;/);
    const slot = rule('.slot');
    expect(slot).toMatch(/width:\s*var\(--slot-size\)/);
    expect(slot).toMatch(/height:\s*var\(--slot-size\)/);
    expect(slot).toMatch(/flex:\s*none/);
    // State marks are absolutely positioned layers that only fade; the state rules touch pseudo-elements only.
    const mark = rule('.mark');
    expect(mark).toMatch(/position:\s*absolute/);
    expect(mark).toMatch(/opacity:\s*0/);
    expect(rule('.on')).toMatch(/opacity:\s*1/);
    const stateSelectors = [...css.matchAll(/^\.(idle|review|wait|block|done|work)([^{]*)\{/gm)].map((m) => m[0]);
    expect(stateSelectors.length).toBeGreaterThanOrEqual(8);
    for (const sel of stateSelectors) expect(sel).toMatch(/::(before|after)/);
  });

  it('exposes an accessible name only when a label is given', () => {
    const { container, rerender } = render(<StatusSlot state="done" label="Completed" />);
    const slot = container.firstElementChild as HTMLElement;
    expect(slot.getAttribute('role')).toBe('img');
    expect(slot.getAttribute('aria-label')).toBe('Completed');
    rerender(<StatusSlot state="done" />);
    expect(container.firstElementChild!.getAttribute('aria-hidden')).toBe('true');
  });
});
