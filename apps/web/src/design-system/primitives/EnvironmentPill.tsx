import styles from './EnvironmentPill.module.css';

export function EnvironmentPill() {
  return (
    <span
      className={styles.envpill}
      data-parity="envpill"
      title="Synthetic data · email, telephony, credit and card services are simulated"
    >
      Synthetic environment
    </span>
  );
}
