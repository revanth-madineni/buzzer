const BASE = '/api';

function authHeader(): Record<string, string> {
  const token = localStorage.getItem('token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * Error text from a failed response. The backend sends {error, message} for
 * BuzzerError, {detail: string} for HTTPException, and {detail: [...]} for
 * request validation.
 */
async function errorMessage(res: Response): Promise<string> {
  const body = (await res.json().catch(() => ({}))) as { message?: unknown; detail?: unknown };
  if (typeof body.message === 'string') return body.message;
  if (typeof body.detail === 'string') return body.detail;
  if (Array.isArray(body.detail)) return 'Invalid input';
  return `HTTP ${res.status}`;
}

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(await errorMessage(res));
  const text = await res.text();
  return (text ? JSON.parse(text) : {}) as T;
}

async function apiFetch<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      ...authHeader(),
      ...((opts.headers as Record<string, string>) ?? {}),
    },
  });
  return parse<T>(res);
}

function withBody(method: string, body?: unknown): RequestInit {
  return { method, body: body !== undefined ? JSON.stringify(body) : undefined };
}

/** Trigger a file download, named from the Content-Disposition header. */
async function download(path: string): Promise<void> {
  const res = await fetch(`${BASE}${path}`, { headers: authHeader() });
  if (!res.ok) throw new Error(await errorMessage(res));
  const disposition = res.headers.get('Content-Disposition') ?? '';
  const match = disposition.match(/filename="([^"]+)"/);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = match ? match[1] : 'download';
  a.click();
  URL.revokeObjectURL(url);
}

export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, body?: unknown) => apiFetch<T>(path, withBody('POST', body)),
  put: <T>(path: string, body?: unknown) => apiFetch<T>(path, withBody('PUT', body)),
  patch: <T>(path: string, body?: unknown) => apiFetch<T>(path, withBody('PATCH', body)),
  delete: <T>(path: string) => apiFetch<T>(path, { method: 'DELETE' }),
  /** POST multipart/form-data (file uploads); the browser sets Content-Type. */
  postForm: async <T>(path: string, form: FormData) =>
    parse<T>(await fetch(`${BASE}${path}`, { method: 'POST', headers: authHeader(), body: form })),
  download,
};
