import { Button, StatusSlot, type SlotState } from '@/design-system/primitives';
import styles from './Money.module.css';

export type TrackRow = {
  key: 'dispute' | 'controls';
  name: string;
  /** Server status label, verbatim. */
  status: string;
  slot: SlotState;
  /** The track in focus (prototype `.trk-r.on`). */
  on: boolean;
  /** Shown only when the server offers an action on this track and it is not in focus. */
  canGo: boolean;
};

export type ParallelTracksProps = { tracks: readonly TrackRow[]; onFocus: (key: TrackRow['key']) => void };

/** Prototype `.trk`: dispute and controls tracks side by side, each with its own status. */
export function ParallelTracks({ tracks, onFocus }: ParallelTracksProps) {
  if (!tracks.length) return null;
  return (
    <div className={styles.trk} role="list" aria-label="Work after the decision">
      <div className={styles.trkH}>Running in parallel · close waits for both</div>
      {tracks.map((t) => (
        <div key={t.key} className={`${styles.trkR}${t.on ? ` ${styles.on}` : ''}`} role="listitem">
          <StatusSlot state={t.slot} />
          <span className={styles.trkN}>{t.name}</span>
          <span className={styles.trkS}>{t.status}</span>
          {t.canGo ? (
            <Button variant={['sm', 'ghost']} onClick={() => onFocus(t.key)}>
              Work on this next
            </Button>
          ) : null}
        </div>
      ))}
    </div>
  );
}
