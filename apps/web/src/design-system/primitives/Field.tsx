import { useId, type InputHTMLAttributes, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react';
import styles from './Field.module.css';

type Common = { label: string; error?: string };
export type FieldProps =
  | (Common & { multiline?: false } & Omit<InputHTMLAttributes<HTMLInputElement>, 'className' | 'id'>)
  | (Common & { multiline: true } & Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'className' | 'id'>);

/** Label, input or textarea, and an inline error wired with aria-invalid / aria-describedby. */
export function Field(props: FieldProps) {
  const id = useId();
  const errId = `${id}-err`;
  const { label, error, multiline, ...rest } = props;
  const common = {
    id,
    'aria-invalid': error ? true : undefined,
    'aria-describedby': error ? errId : undefined,
  };
  const cls = (extra?: string) => [styles.control, extra, error ? styles.invalid : ''].filter(Boolean).join(' ');
  return (
    <div className={styles.field}>
      <label htmlFor={id} className={styles.label}>
        {label}
      </label>
      {multiline ? (
        <textarea className={cls(styles.textarea)} {...common} {...(rest as TextareaHTMLAttributes<HTMLTextAreaElement>)} />
      ) : (
        <input className={cls()} {...common} {...(rest as InputHTMLAttributes<HTMLInputElement>)} />
      )}
      {error ? (
        <div id={errId} className={styles.err} role="alert">
          {error}
        </div>
      ) : null}
    </div>
  );
}

export type FieldOption = { value: string; label: string };
export type SelectFieldProps = Common & { options: readonly FieldOption[] } & Omit<SelectHTMLAttributes<HTMLSelectElement>, 'className' | 'id'>;

/** Label and a select over fixed options, same look and error wiring as Field. */
export function SelectField({ label, error, options, ...rest }: SelectFieldProps) {
  const id = useId();
  const errId = `${id}-err`;
  return (
    <div className={styles.field}>
      <label htmlFor={id} className={styles.label}>
        {label}
      </label>
      <select id={id} className={[styles.control, error ? styles.invalid : ''].filter(Boolean).join(' ')} aria-invalid={error ? true : undefined} aria-describedby={error ? errId : undefined} {...rest}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {error ? (
        <div id={errId} className={styles.err} role="alert">
          {error}
        </div>
      ) : null}
    </div>
  );
}
