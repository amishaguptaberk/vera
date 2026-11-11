// Markup of <StatusSlot/> with plain (un-hashed) CSS-module class names. tests/unit/status-slot.test.tsx proves the
// component renders exactly this, and tests/parity/slot.spec.ts measures it in a real browser with the module's CSS.
export const SLOT_STATE_NAMES = ['idle', 'review', 'wait', 'block', 'done', 'work'] as const;

export function slotMarkup(state: (typeof SLOT_STATE_NAMES)[number]): string {
  const marks = SLOT_STATE_NAMES.map((s) => `<span class="mark ${s}${s === state ? ' on' : ''}"></span>`).join('');
  return `<span class="slot" data-state="${state}" aria-hidden="true">${marks}</span>`;
}
