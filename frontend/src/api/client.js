/* LegalLens backend API client.
   All requests go through the CRA dev-server proxy (see package.json "proxy"),
   so the React app talks to the FastAPI backend same-origin on /api and /sessions. */

const CASE_STORAGE_KEY = 'lexai.case_id';
const TOKEN_KEY = 'token';
const REFRESH_KEY = 'lexai.refresh_token';
const USER_KEY = 'lexai.user';

let casePromise = null;

function readStorage(key) {
  try {
    return window.localStorage.getItem(key);
  } catch (e) {
    return null;
  }
}

function writeStorage(key, value) {
  try {
    if (value === null || value === undefined) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch (e) {
    /* localStorage unavailable */
  }
}

/* ── Session / auth state ──────────────────────────────────────────────── */

export function getToken() {
  return readStorage(TOKEN_KEY);
}

export function getRefreshToken() {
  return readStorage(REFRESH_KEY);
}

export function getAuthUser() {
  try {
    const raw = readStorage(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;
  }
}

export function isAuthenticated() {
  return Boolean(readStorage(TOKEN_KEY));
}

export function saveSession(data) {
  writeStorage(TOKEN_KEY, data.token || data.access_token || null);
  writeStorage(REFRESH_KEY, data.refresh_token || null);
  writeStorage(USER_KEY, data.user ? JSON.stringify(data.user) : null);
  return data.user || null;
}

export function clearSession() {
  writeStorage(TOKEN_KEY, null);
  writeStorage(REFRESH_KEY, null);
  writeStorage(USER_KEY, null);
}

export function getStoredCaseId() {
  return readStorage(CASE_STORAGE_KEY);
}

export function storeCaseId(caseId) {
  writeStorage(CASE_STORAGE_KEY, caseId);
}

export function clearStoredCaseId() {
  writeStorage(CASE_STORAGE_KEY, null);
}

/* ── Auth endpoints ────────────────────────────────────────────────────── */

export function signup({ fullName, email, password, role }) {
  return request('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify({ full_name: fullName, email, password, role: role || 'Advocate' }),
    auth: false,
  }).then((data) => {
    saveSession(data);
    return data;
  });
}

export function login({ email, password }) {
  return request('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
    auth: false,
  }).then((data) => {
    saveSession(data);
    return data;
  });
}

export function logoutRequest() {
  const refresh_token = getRefreshToken();
  return request('/api/auth/logout', {
    method: 'POST',
    body: JSON.stringify(refresh_token ? { refresh_token } : {}),
  }).catch(() => null); /* signing out must never fail on a dead session */
}

export function fetchMe() {
  return request('/api/users/me');
}

/* ── Requests ──────────────────────────────────────────────────────────── */

function describeError(data, status) {
  const detail = data && (data.detail || data.message);
  if (typeof detail === 'string' && detail) return detail;
  if (Array.isArray(detail) && detail.length) {
    /* FastAPI validation errors: [{ loc: [...], msg: '...' }, ...] */
    const first = detail[0];
    const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : '';
    return field ? `${field}: ${first.msg}` : String(first.msg || 'Request failed.');
  }
  return `Request failed (${status}).`;
}

async function request(path, options = {}) {
  const { auth = true, headers, ...rest } = options;
  const isForm = rest.body instanceof FormData;
  const sendHeaders = {};
  if (!isForm) sendHeaders['Content-Type'] = 'application/json';
  const token = getToken();
  if (auth && token) sendHeaders.Authorization = `Bearer ${token}`;

  const response = await fetch(path, {
    ...rest,
    headers: { ...sendHeaders, ...(headers || {}) },
  });

  let data = null;
  try {
    data = await response.json();
  } catch (e) {
    data = null;
  }

  if (!response.ok) {
    /* An expired or revoked access token ends the visit: the app pages are private. */
    if (response.status === 401 && auth && token) {
      clearSession();
      if (window.location.pathname !== '/login') window.location.assign('/login');
    }
    const error = new Error(describeError(data, response.status));
    error.status = response.status;
    throw error;
  }
  return data;
}

/* ── Case sessions ─────────────────────────────────────────────────────── */

export function createCase() {
  return request('/api/sessions', { method: 'POST' });
}

export function getCase(caseId) {
  return request(`/api/sessions/${encodeURIComponent(caseId)}`);
}

export function listCases() {
  return request('/api/sessions');
}

export function updateCase(caseId, { name, pinned } = {}) {
  const body = {};
  if (name !== undefined) body.name = name;
  if (pinned !== undefined) body.pinned = pinned;
  return request(`/api/sessions/${encodeURIComponent(caseId)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
}

/** Delete a conversation; `onlyIfEmpty` refuses to remove one that has content. */
export function deleteCase(caseId, onlyIfEmpty = false) {
  const suffix = onlyIfEmpty ? '?only_if_empty=true' : '';
  return request(`/api/sessions/${encodeURIComponent(caseId)}${suffix}`, { method: 'DELETE' });
}

/** A conversation with nothing in it yet — safe to hand back instead of minting another. */
async function findBlankCase() {
  try {
    const rows = (await listCases()).sessions || [];
    const blank = rows.find((row) => !Number(row.messages || 0) && !Number(row.documents || 0));
    return blank ? blank.case_id : null;
  } catch (e) {
    return null;
  }
}

/** Resolve the current case id, reusing the stored one when it still exists. */
export function ensureCase(forceNew = false) {
  if (!forceNew && casePromise) return casePromise;
  casePromise = (async () => {
    if (!forceNew) {
      const stored = getStoredCaseId();
      if (stored) {
        try {
          const snapshot = await getCase(stored);
          return snapshot.case_id || stored;
        } catch (e) {
          clearStoredCaseId();
        }
      }
      // Signed in on another device/browser: adopt the blank case that is
      // already there rather than leaving another empty one behind it.
      const blank = await findBlankCase();
      if (blank) {
        storeCaseId(blank);
        return blank;
      }
    }
    const snapshot = await createCase();
    storeCaseId(snapshot.case_id);
    return snapshot.case_id;
  })();
  return casePromise;
}

export function resetCasePromise() {
  casePromise = null;
}

/* ── Chat ──────────────────────────────────────────────────────────────── */

export function sendChat(caseId, message) {
  return request('/api/chat', {
    method: 'POST',
    body: JSON.stringify({ case_id: caseId, message }),
  });
}

/* ── Document analysis ─────────────────────────────────────────────────── */

export function analyzeDocument(caseId, file) {
  const form = new FormData();
  form.append('file', file);
  if (caseId) form.append('case_id', caseId);
  return request('/api/analyze', { method: 'POST', body: form });
}

export function saveReportEdits(caseId, documentId, edits) {
  return request(`/api/sessions/${encodeURIComponent(caseId)}/documents/${encodeURIComponent(documentId)}/report`, {
    method: 'PUT',
    body: JSON.stringify({ edits }),
  });
}

export function getDocumentText(caseId, documentId) {
  return request(`/api/sessions/${encodeURIComponent(caseId)}/documents/${encodeURIComponent(documentId)}/text`);
}

/* ── Document generation ───────────────────────────────────────────────── */

export function getGenerationState(caseId) {
  return request(`/api/sessions/${encodeURIComponent(caseId)}/generation`);
}

export function getGenerationFields(caseId, generationId) {
  return request(`/api/sessions/${encodeURIComponent(caseId)}/generation/${encodeURIComponent(generationId)}/fields`);
}

export function updateGenerationFields(caseId, generationId, values, generate) {
  return request(`/api/sessions/${encodeURIComponent(caseId)}/generation/${encodeURIComponent(generationId)}/fields`, {
    method: 'PUT',
    body: JSON.stringify({ values, generate }),
  });
}

export function cancelGeneration(caseId) {
  return request(`/api/sessions/${encodeURIComponent(caseId)}/generation/cancel`, { method: 'POST' });
}

export function retryGeneration(caseId) {
  return request(`/api/sessions/${encodeURIComponent(caseId)}/generation/retry`, { method: 'POST' });
}

/* ── Generated files ───────────────────────────────────────────────────── */

/** Fetch a generated DOCX with the bearer token, since a plain link cannot send one. */
export function downloadGeneratedDocument(caseId, filename) {
  const token = getToken();
  return fetch(
    `/sessions/${encodeURIComponent(caseId)}/download/${encodeURIComponent(filename)}`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} },
  ).then(async (response) => {
    if (!response.ok) {
      throw new Error(`Download failed (${response.status}). Please sign in again.`);
    }
    return response.blob();
  });
}
