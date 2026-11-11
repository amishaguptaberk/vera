import { EnvironmentPill } from '@/design-system/primitives';

// F0 placeholder route: renders one design-system primitive on the canvas.
// The row mimics the prototype's top bar (.top / .bar / .dv: white bar with a rule, 56px min height, 10px 24px padding,
// pill right-aligned and centred) so the pill lands on the same sub-pixel position as in the
// prototype; the real TopBar replaces this in F1.
export default function Home() {
  return (
    <main style={{ minHeight: '100vh' }}>
      <header style={{ background: 'var(--paper)', borderBottom: '1px solid var(--rule)' }}>
        <div style={{ display: 'flex', alignItems: 'center', minHeight: 56, padding: '10px var(--gutter)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginLeft: 'auto' }}>
            <EnvironmentPill />
          </div>
        </div>
      </header>
    </main>
  );
}
