import type { ButtonHTMLAttributes } from 'react';
import styles from './RefChip.module.css';

export type RefChipProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className'> & {
  /** Selected: inverted ink chip. */
  on?: boolean;
};

/** Reference chip for record IDs (CHG-1042, MSG-2251): never wraps internally. */
export function RefChip({ on = false, type = 'button', ...rest }: RefChipProps) {
  return <button type={type} className={on ? `${styles.ref} ${styles.on}` : styles.ref} aria-pressed={on ? true : undefined} {...rest} />;
}
