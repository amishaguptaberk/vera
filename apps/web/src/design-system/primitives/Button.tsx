import type { ButtonHTMLAttributes } from 'react';
import styles from './Button.module.css';

export type ButtonVariant = 'default' | 'go' | 'dark' | 'ghost' | 'sm' | 'demo' | 'icon';

export type ButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className'> & {
  /** One variant or a combination (the prototype's `btn sm ghost` is `['sm', 'ghost']`). */
  variant?: ButtonVariant | readonly ButtonVariant[];
  className?: string;
};

export function Button({ variant = 'default', className, type = 'button', ...rest }: ButtonProps) {
  const variants = typeof variant === 'string' ? [variant] : variant;
  const classes = [styles.btn, ...variants.filter((v) => v !== 'default').map((v) => styles[v]), className];
  return <button type={type} className={classes.filter(Boolean).join(' ')} {...rest} />;
}
