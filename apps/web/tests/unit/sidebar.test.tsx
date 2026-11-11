import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Sidebar, type SidebarProps } from '@/components/shell';
import { clampSidebarWidth, getUiState, reloadUiStateFromStorage, uiActions } from '@/state';

const props = (over: Partial<SidebarProps> = {}): SidebarProps => ({
  pathname: '/cases',
  width: 220,
  collapsed: false,
  drawerOpen: false,
  onWidthChange: () => {},
  onToggleCollapsed: () => {},
  onCloseDrawer: () => {},
  ...over,
});

describe('Sidebar', () => {
  it('renders the prototype nav as real links with the active item from the pathname', () => {
    render(<Sidebar {...props()} />);
    const cases = screen.getByRole('link', { name: 'Cases' });
    expect(cases.getAttribute('href')).toBe('/cases');
    expect(cases.getAttribute('aria-current')).toBe('page');
    expect(screen.getByRole('link', { name: 'Automations' }).getAttribute('href')).toBe('/automations/workflows');
    expect(screen.queryByRole('link', { name: 'Specialists' })).toBeNull();
  });

  it('treats the app root as the Cases landing route', () => {
    render(<Sidebar {...props({ pathname: '/' })} />);
    expect(screen.getByRole('link', { name: 'Cases' }).getAttribute('aria-current')).toBe('page');
  });

  it('expands the Automations sub-navigation on /automations/* with the current page marked', () => {
    render(<Sidebar {...props({ pathname: '/automations/policies' })} />);
    expect(screen.getByRole('link', { name: 'Automations' }).getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByRole('link', { name: 'Policies' }).getAttribute('aria-current')).toBe('page');
    expect(screen.getByRole('link', { name: 'Workflows' }).getAttribute('href')).toBe('/automations/workflows');
    expect(screen.getByRole('link', { name: 'Specialists' }).getAttribute('href')).toBe('/automations/specialists');
    expect(screen.getByRole('link', { name: 'Cases' }).hasAttribute('aria-current')).toBe(false);
  });

  it('shows the splitter with the expanded width, and hides it when collapsed (canResize = !collapsed)', () => {
    const { rerender } = render(<Sidebar {...props({ width: 260 })} />);
    expect(screen.getByRole('separator', { name: 'Resize navigation' }).getAttribute('aria-valuenow')).toBe('260');
    rerender(<Sidebar {...props({ width: 260, collapsed: true })} />);
    expect(screen.queryByRole('separator', { name: 'Resize navigation' })).toBeNull();
  });

  it('the splitter keys call onWidthChange', () => {
    const onWidthChange = vi.fn();
    render(<Sidebar {...props({ onWidthChange })} />);
    fireEvent.keyDown(screen.getByRole('separator', { name: 'Resize navigation' }), { key: 'End' });
    expect(onWidthChange).toHaveBeenLastCalledWith(320);
  });

  it('the collapse toggle calls back and is labelled for its state', async () => {
    const onToggleCollapsed = vi.fn();
    const { rerender } = render(<Sidebar {...props({ onToggleCollapsed })} />);
    await userEvent.setup().click(screen.getByRole('button', { name: 'Collapse navigation' }));
    expect(onToggleCollapsed).toHaveBeenCalledTimes(1);
    rerender(<Sidebar {...props({ collapsed: true })} />);
    expect(screen.getByRole('button', { name: 'Expand navigation' })).toBeTruthy();
  });

  it('shows a tooltip on collapsed rail items (hover and keyboard focus) but not when expanded', async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Sidebar {...props()} />);
    await user.hover(screen.getByRole('link', { name: 'Cases' }));
    expect(screen.queryByRole('tooltip')).toBeNull();
    rerender(<Sidebar {...props({ collapsed: true })} />);
    const cases = screen.getByRole('link', { name: 'Cases' });
    await user.hover(cases);
    expect(screen.getByRole('tooltip').textContent).toBe('Cases');
    expect(cases.getAttribute('aria-describedby')).toBe(screen.getByRole('tooltip').id);
    await user.unhover(cases);
    expect(screen.queryByRole('tooltip')).toBeNull();
    await user.tab();
    await user.tab();
    expect(screen.getByRole('tooltip')).toBeTruthy();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('tooltip')).toBeNull();
  });
});

describe('ui-store', () => {
  it('defaults to 220px, expanded, drawer closed', () => {
    expect(getUiState()).toEqual({ sidebarWidth: 220, sidebarCollapsed: false, navDrawerOpen: false });
  });

  it('clamps the width to 220-320', () => {
    expect(clampSidebarWidth(100)).toBe(220);
    expect(clampSidebarWidth(999)).toBe(320);
    uiActions.setSidebarWidth(500);
    expect(getUiState().sidebarWidth).toBe(320);
    uiActions.setSidebarWidth(10);
    expect(getUiState().sidebarWidth).toBe(220);
  });

  it('persists width and collapse in sessionStorage and restores them on a fresh load', () => {
    uiActions.setSidebarWidth(260);
    uiActions.setSidebarCollapsed(true);
    expect(JSON.parse(window.sessionStorage.getItem('vera-ui')!)).toEqual({ sidebarWidth: 260, sidebarCollapsed: true });
    expect(window.localStorage.getItem('vera-ui')).toBeNull();
    reloadUiStateFromStorage();
    expect(getUiState()).toMatchObject({ sidebarWidth: 260, sidebarCollapsed: true });
  });

  it('keeps the mobile drawer open flag in memory only', () => {
    uiActions.setNavDrawerOpen(true);
    expect(getUiState().navDrawerOpen).toBe(true);
    expect(window.sessionStorage.getItem('vera-ui')).toBeNull();
    uiActions.setSidebarWidth(240);
    expect(window.sessionStorage.getItem('vera-ui')).not.toContain('navDrawerOpen');
    reloadUiStateFromStorage();
    expect(getUiState().navDrawerOpen).toBe(false);
  });

  it('survives unavailable or corrupt storage (try/catch)', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota');
    });
    expect(() => uiActions.setSidebarWidth(300)).not.toThrow();
    expect(getUiState().sidebarWidth).toBe(300);
    vi.restoreAllMocks();
    window.sessionStorage.setItem('vera-ui', '{not json');
    reloadUiStateFromStorage();
    expect(getUiState().sidebarWidth).toBe(220);
    window.sessionStorage.setItem('vera-ui', JSON.stringify({ sidebarWidth: 9999, sidebarCollapsed: 'yes' }));
    reloadUiStateFromStorage();
    expect(getUiState()).toMatchObject({ sidebarWidth: 320, sidebarCollapsed: false });
  });
});
