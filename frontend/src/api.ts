/* Thin fetch wrapper: bearer token, JSON, readable error messages from FastAPI's `detail`. */
const TOKEN_KEY = 'psa-token';

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
export function setToken(t: string | null) {
  try { if (t) localStorage.setItem(TOKEN_KEY, t); else localStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) { onUnauthorized = fn; }

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
  let res: Response;
  try {
    res = await fetch(path, { method, headers, body: payload });
  } catch {
    throw new ApiError(0, 'The server could not be reached. Check that the backend is running.');
  }
  if (res.status === 401 && !path.endsWith('/auth/login')) onUnauthorized();
  if (!res.ok) {
    let msg = `Request failed (${res.status}).`;
    try {
      const j = await res.json();
      if (typeof j.detail === 'string') msg = j.detail;
      else if (Array.isArray(j.detail)) msg = j.detail.map((d: { msg: string }) => d.msg).join(' ');
    } catch { /* not JSON */ }
    throw new ApiError(res.status, msg);
  }
  const ct = res.headers.get('content-type') || '';
  return (ct.includes('application/json') ? res.json() : res.text()) as Promise<T>;
}

export const api = {
  get: <T>(p: string) => request<T>('GET', p),
  post: <T>(p: string, b?: unknown) => request<T>('POST', p, b ?? {}),
  put: <T>(p: string, b?: unknown) => request<T>('PUT', p, b),
  patch: <T>(p: string, b?: unknown) => request<T>('PATCH', p, b),
  del: <T>(p: string) => request<T>('DELETE', p),
  upload: <T>(p: string, files: File[], field = 'file', extra: Record<string, string> = {}) => {
    const fd = new FormData();
    files.forEach((f) => fd.append(field, f));
    Object.entries(extra).forEach(([k, v]) => fd.append(k, v));
    return request<T>('POST', p, fd);
  },
};

/** Open an authenticated file (PDF, CSV) in a new tab or as a download. */
export async function openFile(path: string, download?: string) {
  const res = await fetch(path, { headers: { Authorization: `Bearer ${getToken() ?? ''}` } });
  if (!res.ok) throw new ApiError(res.status, 'The file could not be opened.');
  const url = URL.createObjectURL(await res.blob());
  if (download) {
    const a = document.createElement('a');
    a.href = url; a.download = download; a.click();
  } else {
    window.open(url, '_blank', 'noopener');
  }
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
