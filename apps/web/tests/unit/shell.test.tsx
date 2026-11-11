import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { AppShell } from '@/features/shell/AppShell';
import { getUiState } from '@/state';
import { mockFetch, mockMatchMedia, mockSessionApi, renderWithProviders, session } from './helpers';

const pathname = '/cases';
vi.mock('next/navigation', () => ({ usePathname: () => pathname }));

const roleButton = () => screen.findByRole('button', { name: /viewing as/i });

describe('role switch', () => {
  it('issues exactly one POST /api/session/role then refetches GET /api/session, and never a case command', async () => {
    const calls = mockSessionApi(session('analyst'));
    renderWithProviders(<AppShell>{null}</AppShell>);
    const user = userEvent.setup();

    await user.click(await roleButton());
    const menu = await screen.findByRole('menu', { name: 'Demo role' });
    await user.click(within(menu).getByRole('menuitemradio', { name: /Cardholder/ }));

    await waitFor(() => expect(calls.length).toBe(3));
    await screen.findByRole('button', { name: /viewing as cardholder/i });

    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual(['GET /api/session', 'POST /api/session/role', 'GET /api/session']);
    expect(JSON.parse(calls[1].body!)).toEqual({ role: 'cardholder' });
    expect(calls[1].body).toBe('{"role":"cardholder"}');
    for (const c of calls) {
      expect(c.url).not.toContain('/commands');
      expect(c.url).not.toContain('/api/cases');
    }
  });

  it('maps the reviewer option to the reviewer role and does not call the API when the role is unchanged', async () => {
    const calls = mockSessionApi(session('card_admin'));
    renderWithProviders(<AppShell>{null}</AppShell>);
    const user = userEvent.setup();
    // card_admin shows as the reviewer view.
    await user.click(await screen.findByRole('button', { name: /viewing as reviewer/i }));
    const menu = await screen.findByRole('menu');
    expect(within(menu).getByRole('menuitemradio', { name: /Reviewer · card admin/ }).getAttribute('aria-checked')).toBe('true');
    await user.click(within(menu).getByRole('menuitemradio', { name: /Reviewer · card admin/ }));
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual(['GET /api/session']);
  });

  it('shows a skeleton in the role selector while loading and a retry banner on error, with no fallback role', async () => {
    let fail = true;
    const calls = mockFetch(() =>
      fail ? new Response(JSON.stringify({ code: 'unauthenticated', message: 'The session holds no role.' }), { status: 401 }) : session('analyst'),
    );
    renderWithProviders(<AppShell>{null}</AppShell>);
    expect(screen.getByTestId('role-selector-loading')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /viewing as/i })).toBeNull();

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('The session holds no role.');
    expect(screen.queryByRole('button', { name: /viewing as/i })).toBeNull();

    fail = false;
    await userEvent.setup().click(within(alert).getByRole('button', { name: 'Retry' }));
    await roleButton();
    expect(calls.length).toBe(2);
  });
});

describe('environment pill', () => {
  it('appears exactly once, inside the top bar, in the synthetic environment', async () => {
    mockSessionApi(session('analyst', 'synthetic'));
    renderWithProviders(
      <AppShell>
        <main>page content</main>
      </AppShell>,
    );
    await roleButton();
    const pills = screen.getAllByText('Synthetic environment');
    expect(pills).toHaveLength(1);
    expect(pills[0].closest('header')).toBe(screen.getByRole('banner'));
    expect(within(screen.getByRole('banner')).getByText('Synthetic environment')).toBe(pills[0]);
  });

  it('is absent in any other environment', async () => {
    mockSessionApi(session('analyst', 'production'));
    renderWithProviders(<AppShell>{null}</AppShell>);
    await roleButton();
    expect(screen.queryByText('Synthetic environment')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Reset' })).toBeNull();
  });
});

describe('demo reset', () => {
  it('calls POST /api/demo/reset then refetches the session', async () => {
    const calls = mockSessionApi(session('analyst'));
    renderWithProviders(<AppShell>{null}</AppShell>);
    await roleButton();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Reset' }));
    await waitFor(() => expect(calls.length).toBe(3));
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual(['GET /api/session', 'POST /api/demo/reset', 'GET /api/session']);
  });
});

describe('shell layout by role', () => {
  it('shows the sidebar for the analyst view and the brand in the top bar for the cardholder view', async () => {
    mockSessionApi(session('analyst'));
    renderWithProviders(<AppShell>{null}</AppShell>);
    await roleButton();
    expect(screen.getByRole('navigation', { name: 'Sections' })).toBeTruthy();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /viewing as/i }));
    await user.click(screen.getByRole('menuitemradio', { name: /Cardholder/ }));
    await screen.findByRole('button', { name: /viewing as cardholder/i });
    expect(screen.queryByRole('navigation', { name: 'Sections' })).toBeNull();
    expect(within(screen.getByRole('banner')).getByAltText('Vera')).toBeTruthy();
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Charge review');
  });
});

describe('mobile navigation drawer', () => {
  it('opens from the menu button, closes on scrim click and Escape, and returns focus to the menu button', async () => {
    mockMatchMedia((q) => q === '(max-width: 760px)');
    mockSessionApi(session('analyst'));
    renderWithProviders(<AppShell>{null}</AppShell>);
    await roleButton();
    const user = userEvent.setup();
    const menuButton = screen.getByRole('button', { name: 'Open navigation' });
    expect(menuButton.getAttribute('aria-expanded')).toBe('false');
    // Closed: off-canvas and inert, no scrim.
    expect(document.querySelector('aside')!.hasAttribute('inert')).toBe(true);
    expect(screen.queryByRole('button', { name: 'Close navigation' })).toBeNull();

    await user.click(menuButton);
    const drawer = screen.getByRole('dialog', { name: 'Product navigation' });
    expect(drawer.hasAttribute('inert')).toBe(false);
    expect(menuButton.getAttribute('aria-expanded')).toBe('true');
    expect(drawer.contains(document.activeElement)).toBe(true);

    await user.click(screen.getByRole('button', { name: 'Close navigation' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(menuButton);

    await user.click(menuButton);
    expect(screen.getByRole('dialog')).toBeTruthy();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(menuButton);
  });

  it('Collapse inside the open drawer closes it and leaves the stored desktop collapse unchanged', async () => {
    mockMatchMedia((q) => q === '(max-width: 760px)');
    mockSessionApi(session('analyst'));
    renderWithProviders(<AppShell>{null}</AppShell>);
    await roleButton();
    const before = getUiState().sidebarCollapsed;
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Open navigation' }));
    const drawer = screen.getByRole('dialog', { name: 'Product navigation' });
    await user.click(within(drawer).getByRole('button', { name: 'Collapse navigation' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(getUiState().navDrawerOpen).toBe(false);
    expect(getUiState().sidebarCollapsed).toBe(before);
  });

  it('traps Tab inside the open drawer', async () => {
    mockMatchMedia((q) => q === '(max-width: 760px)');
    mockSessionApi(session('analyst'));
    renderWithProviders(<AppShell>{null}</AppShell>);
    await roleButton();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Open navigation' }));
    const drawer = screen.getByRole('dialog');
    for (let i = 0; i < 8; i++) {
      await user.tab();
      expect(drawer.contains(document.activeElement)).toBe(true);
    }
    await user.tab({ shift: true });
    expect(drawer.contains(document.activeElement)).toBe(true);
  });

  it('does not use the dialog role or a scrim on wide screens', async () => {
    mockMatchMedia(() => false);
    mockSessionApi(session('analyst'));
    renderWithProviders(<AppShell>{null}</AppShell>);
    await roleButton();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByRole('complementary', { name: 'Product navigation' }).hasAttribute('inert')).toBe(false);
  });
});
