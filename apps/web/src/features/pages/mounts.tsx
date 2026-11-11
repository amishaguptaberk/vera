// The one place feature modules are mounted into route slots.
import type { ComponentType } from 'react';
import { RequestPage } from '@/features/comms';
import { CardholderHome } from './CardholderHome';

export type PageMounts = {
  /** `/requests/[id]`: the cardholder's request page. */
  RequestPage: ComponentType<{ requestId: string }> | null;
  /** Resolves the signed-in cardholder's own request (GET /api/requests?mine=true) and renders it. */
  CardholderHome: ComponentType | null;
};

export const pageMounts: PageMounts = {
  RequestPage,
  CardholderHome,
};
