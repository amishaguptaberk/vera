import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { Splitter } from '@/design-system/primitives/Splitter';

function Harness({ initial = 220, onChange }: { initial?: number; onChange?: (w: number) => void }) {
  const [w, setW] = useState(initial);
  return (
    <Splitter
      label="Resize navigation"
      orientation="vertical"
      min={220}
      max={320}
      value={w}
      onChange={(v) => {
        setW(v);
        onChange?.(v);
      }}
    />
  );
}

const sep = () => screen.getByRole('separator', { name: 'Resize navigation' });

describe('Splitter keyboard contract', () => {
  it('exposes the separator role, label, orientation, range, value and tabindex', () => {
    render(<Harness initial={260} />);
    const el = sep();
    expect(el.getAttribute('aria-orientation')).toBe('vertical');
    expect(el.getAttribute('aria-valuemin')).toBe('220');
    expect(el.getAttribute('aria-valuemax')).toBe('320');
    expect(el.getAttribute('aria-valuenow')).toBe('260');
    expect(el.getAttribute('tabindex')).toBe('0');
  });

  it.each([
    ['ArrowRight', {}, 260, 276],
    ['ArrowLeft', {}, 260, 244],
    ['ArrowRight', { shiftKey: true }, 240, 304],
    ['ArrowLeft', { shiftKey: true }, 300, 236],
    ['ArrowRight', {}, 316, 320],
    ['ArrowLeft', {}, 224, 220],
    ['ArrowRight', { shiftKey: true }, 300, 320],
    ['ArrowLeft', { shiftKey: true }, 230, 220],
    ['Home', {}, 300, 220],
    ['End', {}, 240, 320],
  ])('%s %j from %i gives %i and prevents default', (key, mods, from, to) => {
    render(<Harness initial={from} />);
    const notPrevented = fireEvent.keyDown(sep(), { key, ...mods });
    expect(notPrevented).toBe(false);
    expect(sep().getAttribute('aria-valuenow')).toBe(String(to));
  });

  it('ignores other keys without preventing default or calling onChange', () => {
    const onChange = vi.fn();
    render(<Harness initial={260} onChange={onChange} />);
    expect(fireEvent.keyDown(sep(), { key: 'ArrowUp' })).toBe(true);
    expect(fireEvent.keyDown(sep(), { key: 'a' })).toBe(true);
    expect(onChange).not.toHaveBeenCalled();
    expect(sep().getAttribute('aria-valuenow')).toBe('260');
  });
});
