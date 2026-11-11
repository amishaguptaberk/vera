'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useRef, type ReactNode } from 'react';
import { useResetDemo, useSession, useSwitchRole, type Role } from '@/api';
import { Sidebar, TopBar, type RoleViewId } from '@/components/shell';
import { Banner } from '@/design-system/primitives';
import { uiActions, useUiState } from '@/state';
import { contextTitle, viewForRole } from './role-view';
import styles from './AppShell.module.css';

/** The prototype's role views map onto the human session roles the server accepts. */
const ROLE_FOR_VIEW: Record<RoleViewId, Role> = { analyst: 'analyst', cardholder: 'cardholder', reviewer: 'reviewer' };

/**
 * Wires the session query, the role mutation and the ui-store into the presentational shell.
 * Role switching goes only through POST /api/session/role (then GET /api/session); it never issues a case command.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? '/';
  const router = useRouter();
  const session = useSession();
  const switchRole = useSwitchRole();
  const reset = useResetDemo();
  const ui = useUiState();
  const menuButton = useRef<HTMLButtonElement | null>(null);

  const data = session.data;
  const view = data ? viewForRole(data.active_role) : null;
  // The sidebar belongs to the analyst view (prototype `showSide`). Until the session is known the default
  // (analyst) layout is shown; this is layout only, no role or data is assumed.
  const hasSidebar = view === null || view === 'analyst';
  const synthetic = data?.environment === 'synthetic';

  return (
    <div className={styles.app}>
      <div className={styles.frame}>
        {hasSidebar ? (
          <Sidebar
            pathname={pathname}
            width={ui.sidebarWidth}
            collapsed={ui.sidebarCollapsed}
            drawerOpen={ui.navDrawerOpen}
            returnFocusRef={menuButton}
            onWidthChange={uiActions.setSidebarWidth}
            onToggleCollapsed={uiActions.toggleSidebarCollapsed}
            onCloseDrawer={() => uiActions.setNavDrawerOpen(false)}
          />
        ) : null}
        <div className={styles.content}>
          <TopBar
            title={contextTitle(view, pathname)}
            hasSidebar={hasSidebar}
            navOpen={ui.navDrawerOpen}
            menuButtonRef={menuButton}
            onToggleNav={() => uiActions.setNavDrawerOpen(!ui.navDrawerOpen)}
            synthetic={synthetic}
            role={{
              loading: session.isPending,
              selected: view,
              pending: switchRole.isPending,
              // After the server confirms the role, go to that role's landing (prototype `setView`).
              onSelect: (id) => switchRole.mutate(ROLE_FOR_VIEW[id], { onSuccess: () => router.push('/') }),
            }}
            onReset={synthetic ? () => reset.mutate() : undefined}
            resetPending={reset.isPending}
          />
          {session.isError ? (
            <Banner tone="bad" title="Session unavailable." action={{ label: 'Retry', onClick: () => void session.refetch() }}>
              {session.error.message}
            </Banner>
          ) : null}
          {switchRole.isError ? <Banner tone="bad" title="Role not changed.">{switchRole.error.message}</Banner> : null}
          {reset.isError ? <Banner tone="bad" title="Reset failed.">{reset.error.message}</Banner> : null}
          {children}
        </div>
      </div>
    </div>
  );
}
