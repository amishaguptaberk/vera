// Same-origin fetch wrapper. `/api/*` is rewritten to the FastAPI service by next.config.mjs, so the
// session cookie and (later) SSE stay same-origin. No retries here: consequential commands are never auto-retried.

const BASE = '/api';

/** Top-level error body of the API (docs/frontend-architecture.md §6). */
export type ApiErrorBody = {
  code: string;
  message: string;
  blocked_reason?: string;
  case_version?: number;
};

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly blockedReason?: string;
  readonly caseVersion?: number;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = 'ApiError';
    this.status = status;
    this.code = body.code;
    this.blockedReason = body.blocked_reason;
    this.caseVersion = body.case_version;
  }
}

function isErrorBody(x: unknown): x is ApiErrorBody {
  return typeof x === 'object' && x !== null && typeof (x as ApiErrorBody).code === 'string' && typeof (x as ApiErrorBody).message === 'string';
}

export type RequestOptions = { body?: unknown; signal?: AbortSignal };

export async function apiRequest<T>(method: 'GET' | 'POST' | 'PATCH' | 'DELETE', path: string, options: RequestOptions = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      credentials: 'same-origin',
      headers: options.body === undefined ? { Accept: 'application/json' } : { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    throw new ApiError(0, { code: 'network_error', message: 'Could not reach the service.' });
  }
  const text = await res.text();
  let json: unknown;
  try {
    json = text ? JSON.parse(text) : undefined;
  } catch {
    json = undefined;
  }
  if (!res.ok) {
    throw new ApiError(res.status, isErrorBody(json) ? json : { code: 'unknown_error', message: `Request failed (${res.status}).` });
  }
  return json as T;
}

export const apiGet = <T>(path: string, signal?: AbortSignal) => apiRequest<T>('GET', path, { signal });
export const apiPost = <T>(path: string, body?: unknown) => apiRequest<T>('POST', path, { body });
