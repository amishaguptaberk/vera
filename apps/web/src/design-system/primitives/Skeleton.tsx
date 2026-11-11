import type { CSSProperties } from 'react';
import styles from './Skeleton.module.css';

export type SkeletonProps = { width?: number | string; height?: number | string; radius?: number | string; className?: string };

/** Placeholder block for content that has not loaded yet. Decorative: the owner announces loading via aria-busy. */
export function Skeleton({ width = '100%', height = 14, radius, className }: SkeletonProps) {
  const style: CSSProperties = { width, height, ...(radius !== undefined ? { borderRadius: radius } : {}) };
  return <span aria-hidden="true" data-skeleton="" className={className ? `${styles.skel} ${className}` : styles.skel} style={style} />;
}
