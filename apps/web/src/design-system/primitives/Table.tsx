import type { HTMLAttributes, TableHTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from 'react';
import styles from './Table.module.css';

export type TableProps = Omit<TableHTMLAttributes<HTMLTableElement>, 'className'> & {
  /** `plain` is the prototype's .pt (compact), `work` is table.wt (queue/work tables, min-width 900px). */
  variant?: 'plain' | 'work';
};

export function Table({ variant = 'plain', ...rest }: TableProps) {
  return <table className={variant === 'work' ? styles.wt : styles.pt} {...rest} />;
}

export const TableHead = (p: HTMLAttributes<HTMLTableSectionElement>) => <thead {...p} />;
export const TableBody = (p: HTMLAttributes<HTMLTableSectionElement>) => <tbody {...p} />;

/** `selected`: cobalt-wash row with a 3px cobalt left bar (Handoff §9.4). */
export function TableRow({
  selected = false,
  ...rest
}: Omit<HTMLAttributes<HTMLTableRowElement>, 'className'> & { selected?: boolean }) {
  return <tr className={selected ? styles.sel : undefined} aria-selected={selected || undefined} {...rest} />;
}

export const TableHeadCell = ({ scope = 'col', ...p }: ThHTMLAttributes<HTMLTableCellElement>) => <th scope={scope} {...p} />;
export const TableCell = (p: TdHTMLAttributes<HTMLTableCellElement>) => <td {...p} />;
