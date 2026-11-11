// The one place feature modules are mounted into route slots (see README of each feature).
import type { ComponentType } from 'react';

export type PageMounts = {
  /** `/requests/[id]`: the cardholder's request page. */
  RequestPage: ComponentType<{ requestId: string }> | null;
  /** Resolves the signed-in cardholder's own request (GET /api/requests?mine=true) and renders it. */
  CardholderHome: ComponentType | null;
};

export const pageMounts: PageMounts = {
  RequestPage: null,
  CardholderHome: null,
};
