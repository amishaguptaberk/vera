import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import {
  Banner,
  Button,
  Field,
  FilterTabs,
  Menu,
  RefChip,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeadCell,
  TableRow,
  Tabs,
  Tooltip,
} from '@/design-system/primitives';

describe('Button', () => {
  it('is type=button by default, supports variant combinations and disabled', async () => {
    const onClick = vi.fn();
    const { rerender } = render(<Button variant={['sm', 'ghost']} onClick={onClick}>Reset</Button>);
    const b = screen.getByRole('button', { name: 'Reset' });
    expect(b.getAttribute('type')).toBe('button');
    expect(b.className).toMatch(/_sm_/);
    expect(b.className).toMatch(/_ghost_/);
    await userEvent.setup().click(b);
    expect(onClick).toHaveBeenCalledTimes(1);
    rerender(<Button disabled onClick={onClick}>Reset</Button>);
    await userEvent.setup().click(screen.getByRole('button'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it.each(['default', 'go', 'dark', 'ghost', 'sm', 'demo', 'icon'] as const)('renders the %s variant', (variant) => {
    render(<Button variant={variant}>x</Button>);
    expect(screen.getByRole('button').className).toMatch(variant === 'default' ? /_btn_/ : new RegExp(`_${variant}_`));
  });
});

describe('RefChip', () => {
  it('renders the id and reports selection', () => {
    render(<RefChip on>CHG-1042</RefChip>);
    expect(screen.getByRole('button', { name: 'CHG-1042' }).getAttribute('aria-pressed')).toBe('true');
  });
});

describe('Tabs', () => {
  it('selects with click and moves with arrow keys, Home and End', async () => {
    const onChange = vi.fn();
    render(<Tabs label="Case" value="b" onChange={onChange} items={[{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }, { id: 'c', label: 'C' }]} />);
    const tabs = screen.getAllByRole('tab');
    expect(tabs.map((t) => t.getAttribute('aria-selected'))).toEqual(['false', 'true', 'false']);
    fireEvent.keyDown(tabs[1], { key: 'ArrowRight' });
    expect(onChange).toHaveBeenLastCalledWith('c');
    fireEvent.keyDown(tabs[1], { key: 'Home' });
    expect(onChange).toHaveBeenLastCalledWith('a');
    fireEvent.keyDown(tabs[1], { key: 'End' });
    expect(onChange).toHaveBeenLastCalledWith('c');
  });
});

describe('FilterTabs', () => {
  it('is a labelled group of toggle buttons with counts', async () => {
    const onChange = vi.fn();
    render(<FilterTabs label="Filter cases" value="all" onChange={onChange} items={[{ id: 'all', label: 'All', count: 8 }, { id: 'due', label: 'Due today' }]} />);
    const group = screen.getByRole('group', { name: 'Filter cases' });
    expect(within(group).getByRole('button', { name: /All/ }).getAttribute('aria-pressed')).toBe('true');
    await userEvent.setup().click(within(group).getByRole('button', { name: 'Due today' }));
    expect(onChange).toHaveBeenCalledWith('due');
  });
});

describe('Table', () => {
  it('renders a semantic table with a selected row', () => {
    render(
      <Table>
        <TableHead>
          <tr><TableHeadCell>Step</TableHeadCell></tr>
        </TableHead>
        <TableBody>
          <TableRow selected><TableCell>One</TableCell></TableRow>
        </TableBody>
      </Table>,
    );
    expect(screen.getByRole('columnheader', { name: 'Step' }).getAttribute('scope')).toBe('col');
    expect(screen.getByRole('row', { name: 'One' }).getAttribute('aria-selected')).toBe('true');
  });
});

describe('Menu', () => {
  const items = [{ id: 'a', label: 'A' }, { id: 'b', label: 'B', checked: true }, { id: 'c', label: 'C' }];

  it('is a role=menu of menuitemradio, focuses the checked item and moves with arrows', async () => {
    render(<Menu label="Demo role" items={items} onSelect={() => {}} onClose={() => {}} />);
    const menu = screen.getByRole('menu', { name: 'Demo role' });
    const radios = within(menu).getAllByRole('menuitemradio');
    expect(radios.map((r) => r.getAttribute('aria-checked'))).toEqual(['false', 'true', 'false']);
    expect(document.activeElement).toBe(radios[1]);
    const user = userEvent.setup();
    await user.keyboard('{ArrowDown}');
    expect(document.activeElement).toBe(radios[2]);
    await user.keyboard('{ArrowDown}');
    expect(document.activeElement).toBe(radios[0]);
    await user.keyboard('{ArrowUp}');
    expect(document.activeElement).toBe(radios[2]);
    await user.keyboard('{Home}');
    expect(document.activeElement).toBe(radios[0]);
    await user.keyboard('{End}');
    expect(document.activeElement).toBe(radios[2]);
  });

  it('selects with Enter and Space and closes with Escape', async () => {
    const onSelect = vi.fn();
    const onClose = vi.fn();
    render(<Menu label="m" items={items} onSelect={onSelect} onClose={onClose} />);
    const user = userEvent.setup();
    await user.keyboard('{ArrowDown}{Enter}');
    expect(onSelect).toHaveBeenLastCalledWith('c');
    await user.keyboard('{ArrowUp}{ }');
    expect(onSelect).toHaveBeenLastCalledWith('b');
    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe('Tooltip', () => {
  it('describes its trigger while visible and disappears on leave', async () => {
    const user = userEvent.setup();
    render(<Tooltip label="Cases"><button>Go</button></Tooltip>);
    const btn = screen.getByRole('button', { name: 'Go' });
    expect(btn.hasAttribute('aria-describedby')).toBe(false);
    await user.hover(btn);
    expect(screen.getByRole('tooltip').textContent).toBe('Cases');
    expect(btn.getAttribute('aria-describedby')).toBe(screen.getByRole('tooltip').id);
    await user.unhover(btn);
    expect(screen.queryByRole('tooltip')).toBeNull();
  });
});

describe('Field', () => {
  it('labels the input and wires an error with aria-invalid and aria-describedby', () => {
    const { rerender } = render(<Field label="Reason" />);
    expect(screen.getByLabelText('Reason').getAttribute('aria-invalid')).toBeNull();
    rerender(<Field label="Reason" error="Required" />);
    const input = screen.getByLabelText('Reason');
    expect(input.getAttribute('aria-invalid')).toBe('true');
    expect(document.getElementById(input.getAttribute('aria-describedby')!)!.textContent).toBe('Required');
  });

  it('renders a textarea when multiline', () => {
    render(<Field label="Note" multiline />);
    expect(screen.getByLabelText('Note').tagName).toBe('TEXTAREA');
  });
});

describe('Skeleton', () => {
  it('is a decorative sized block', () => {
    const { container } = render(<Skeleton width={120} height={20} />);
    const el = container.firstElementChild as HTMLElement;
    expect(el.getAttribute('aria-hidden')).toBe('true');
    expect(el.style.width).toBe('120px');
    expect(el.style.height).toBe('20px');
  });
});

describe('Banner', () => {
  it('announces errors with role=alert, others as status, and runs its action', async () => {
    const onClick = vi.fn();
    const { rerender } = render(<Banner tone="bad" title="Failed." action={{ label: 'Retry', onClick }}>Try again.</Banner>);
    expect(screen.getByRole('alert').textContent).toContain('Failed. Try again.');
    await userEvent.setup().click(screen.getByRole('button', { name: 'Retry' }));
    expect(onClick).toHaveBeenCalledTimes(1);
    rerender(<Banner>Heads up</Banner>);
    expect(screen.getByRole('status').textContent).toBe('Heads up');
  });
});
