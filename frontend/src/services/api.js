/**
 * Thin wrapper around the BridgeTalk REST API.
 *
 * Every network call in the app goes through here, which means the auth header,
 * error shape and base URL are defined in exactly one place. A component that
 * calls `fetch` directly is a bug.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';
const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL ?? 'ws://localhost:8000';

const TOKEN_KEY = 'bridgetalk.token';

/**
 * An API error carrying the HTTP status, so callers can distinguish
 * "wrong password" (401) from "the server is down" (no status at all).
 */
export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

// --- token storage ---------------------------------------------------------
// localStorage rather than an httpOnly cookie is a deliberate, documented
// trade-off. httpOnly cookies resist XSS, which localStorage does not; but they
// need CSRF protection and cannot be read by the WebSocket URL builder, which
// needs the raw token as a query parameter. For a locally-hosted academic
// project the simpler path is the right one, and this comment is here so the
// choice is visible rather than accidental.

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

/**
 * Perform an authenticated request and parse the response.
 *
 * @param {string} path e.g. '/api/auth/me'
 * @param {object} options fetch options; `body` is JSON-encoded automatically
 */
async function request(path, options = {}) {
  const { body, headers = {}, ...rest } = options;
  const token = getToken();

  const finalHeaders = { ...headers };
  if (body !== undefined) finalHeaders['Content-Type'] = 'application/json';
  if (token) finalHeaders.Authorization = `Bearer ${token}`;

  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...rest,
      headers: finalHeaders,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (cause) {
    // fetch only rejects for network-level failures. Saying "cannot reach the
    // server" is far more useful than the browser's bare "Failed to fetch".
    throw new ApiError(
      `Cannot reach the BridgeTalk API at ${API_BASE_URL}. Is the backend running?`,
      0,
      null,
    );
  }

  if (response.status === 204) return null;

  const isJson = (response.headers.get('content-type') ?? '').includes('application/json');
  const payload = isJson ? await response.json() : await response.text();

  if (!response.ok) {
    // FastAPI returns {detail: "..."} for HTTPException and {detail: [...]}
    // for validation errors. Flatten both into one readable string.
    let message = `Request failed (${response.status})`;
    if (payload && typeof payload === 'object' && payload.detail) {
      message = Array.isArray(payload.detail)
        ? payload.detail.map((item) => item.msg ?? String(item)).join('; ')
        : String(payload.detail);
    }
    throw new ApiError(message, response.status, payload);
  }

  return payload;
}

// --- auth ------------------------------------------------------------------

export const auth = {
  register: (payload) => request('/api/auth/register', { method: 'POST', body: payload }),
  login: (email, password) =>
    request('/api/auth/login/json', { method: 'POST', body: { email, password } }),
  me: () => request('/api/auth/me'),
};

// --- meetings --------------------------------------------------------------

export const meetings = {
  create: (title, isInterviewMode = false) =>
    request('/api/meetings', {
      method: 'POST',
      body: { title, is_interview_mode: isInterviewMode },
    }),
  get: (code) => request(`/api/meetings/${encodeURIComponent(code)}`),
  join: (code) => request(`/api/meetings/${encodeURIComponent(code)}/join`, { method: 'POST' }),
  leave: (code) => request(`/api/meetings/${encodeURIComponent(code)}/leave`, { method: 'POST' }),
  end: (code) => request(`/api/meetings/${encodeURIComponent(code)}/end`, { method: 'POST' }),
  history: () => request('/api/meetings/history'),
};

// --- transcripts -----------------------------------------------------------

export const transcripts = {
  append: ({ meetingId, source, content, confidence = null }) =>
    request('/api/transcripts', {
      method: 'POST',
      body: { meeting_id: meetingId, source, content, confidence },
    }),
  list: (meetingId) => request(`/api/transcripts/${meetingId}`),
  exportUrl: (meetingId) => `${API_BASE_URL}/api/transcripts/${meetingId}/export`,
};

// --- system ----------------------------------------------------------------

export const system = {
  health: () => request('/health'),
};

/**
 * Build the URL for the sign-inference WebSocket.
 *
 * The token goes in the query string because the browser WebSocket constructor
 * accepts only a URL — there is no way to set an Authorization header on it.
 */
export function buildPredictSocketUrl(meetingCode) {
  const token = getToken();
  return `${WS_BASE_URL}/ws/predict/${encodeURIComponent(meetingCode)}?token=${encodeURIComponent(
    token ?? '',
  )}`;
}

export { API_BASE_URL, WS_BASE_URL };
