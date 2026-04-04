/**
 * API client for OceanLabs backend.
 * Uses Supabase JWT for authentication.
 */

import { supabase } from './supabase';

export const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
let authFailureState = {
  failed: false,
}

function toWebSocketBase(httpBaseUrl) {
  return httpBaseUrl
    .replace(/^https:\/\//i, 'wss://')
    .replace(/^http:\/\//i, 'ws://')
    .replace(/\/+$/, '')
}

const API_WS_BASE = toWebSocketBase(API_BASE)

/**
 * Get the current access token from Supabase session.
 * @returns {Promise<string|null>}
 */
async function getAuthToken(options = {}) {
  const { allowRefresh = true } = options;

  try {
    const {
      data: { session },
    } = await supabase.auth.getSession();

    let token = session?.access_token || null;
    if (!token && allowRefresh) {
      const { data: refreshedData, error: refreshError } = await supabase.auth.refreshSession();
      if (!refreshError) {
        token = refreshedData?.session?.access_token || null;
      }
    }

    if (token) {
      authFailureState = { failed: false };
    }
    return token;
  } catch {
    return null;
  }
}

function createAuthError() {
  return new Error('Authentication required. Please log in again.');
}

/**
 * Build headers with JWT authorization.
 * @param {Object} extraHeaders
 * @param {{ requireAuth?: boolean }} options
 * @returns {Promise<Headers>}
 */
async function buildAuthHeaders(extraHeaders = {}, options = {}) {
  const { requireAuth = true } = options;
  const token = await getAuthToken({ allowRefresh: requireAuth });

  if (requireAuth && !token) {
    throw createAuthError();
  }

  const headers = new Headers({
    'Content-Type': 'application/json',
    ...extraHeaders,
  });
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  return headers;
}

async function fetchWithAuthRetry(url, options = {}) {
  const { retryOnUnauthorized = true, ...fetchOptions } = options;
  const initialHeaders = await buildAuthHeaders(fetchOptions.headers || {});

  let response = await fetch(url, {
    ...fetchOptions,
    headers: initialHeaders,
  });

  if (response.status !== 401 || !retryOnUnauthorized) {
    return response;
  }

  const refreshedToken = await getAuthToken({ allowRefresh: true });
  if (!refreshedToken) {
    return response;
  }

  const retryHeaders = await buildAuthHeaders(fetchOptions.headers || {});
  response = await fetch(url, {
    ...fetchOptions,
    headers: retryHeaders,
  });

  return response;
}

function toApiErrorMessage(response, detail, fallbackMessage) {
  const normalizedDetail = typeof detail === 'string' ? detail.trim() : '';

  if (response.status === 404 && normalizedDetail.toLowerCase() === 'not found') {
    return `Backend endpoint not found at ${API_BASE}. Start this project backend and set VITE_API_BASE_URL if needed.`;
  }

  if (response.status === 401) {
    // Mark auth failure but avoid immediate forced logout on transient verification issues.
    authFailureState.failed = true;
    return 'Session expired. Please log in again.';
  }

  return normalizedDetail || fallbackMessage;
}

/**
 * Start a meeting recording
 * @param {Object} data - { title, platform, url, language, duration_minutes }
 * @returns {Promise<Object>} - { recording_id, status }
 */
export async function startRecording(data) {
  const response = await fetchWithAuthRetry(`${API_BASE}/api/start-recording`, {
    method: 'POST',
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(toApiErrorMessage(response, error.detail, 'Failed to start recording'));
  }

  return response.json();
}

/**
 * List active recordings
 * @returns {Promise<Array>}
 */
export async function listRecordings() {
  const response = await fetchWithAuthRetry(`${API_BASE}/api/recordings`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '' }));
    throw new Error(toApiErrorMessage(response, error.detail, 'Failed to fetch recordings'));
  }

  return response.json();
}

/**
 * Get one recording detail by ID
 * @param {string} recordingId
 * @returns {Promise<Object>}
 */
export async function getRecordingDetails(recordingId) {
  const response = await fetchWithAuthRetry(`${API_BASE}/api/recordings/${encodeURIComponent(recordingId)}`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '' }))
    throw new Error(toApiErrorMessage(response, error.detail, 'Failed to fetch recording details'))
  }

  return response.json()
}

/**
 * Subscribe to realtime recording events over WebSocket.
 * @param {string} recordingId
 * @param {Object} handlers
 * @param {(payload: any) => void} handlers.onEvent
 * @param {(error: Event | Error) => void} handlers.onError
 * @param {(event: CloseEvent) => void} handlers.onClose
 * @returns {() => void}
 */
export function startRecordingStream(recordingId, handlers = {}) {
  const safeRecordingId = (recordingId || '').trim();
  if (!safeRecordingId) return () => {};
  const streamPath = `/api/recordings/${encodeURIComponent(safeRecordingId)}/stream`;
  let socket = null;
  let disposed = false;

  getAuthToken()
    .then((token) => {
      if (disposed) return;

      if (!token) {
        handlers.onError?.(createAuthError());
        handlers.onClose?.({
          code: 4401,
          reason: 'Missing authentication token',
          wasClean: true,
        });
        return;
      }

      const socketUrl = `${API_WS_BASE}${streamPath}?token=${encodeURIComponent(token)}`;
      socket = new WebSocket(socketUrl);

      socket.onmessage = (event) => {
        if (!handlers?.onEvent) return;
        try {
          const parsed = JSON.parse(event.data);
          handlers.onEvent(parsed);
        } catch (parseError) {
          handlers.onError?.(parseError);
        }
      };

      socket.onerror = (errorEvent) => {
        handlers.onError?.(errorEvent);
      };

      socket.onclose = (closeEvent) => {
        handlers.onClose?.(closeEvent);
      };
    })
    .catch((error) => {
      if (!disposed) {
        handlers.onError?.(error);
      }
    });

  return () => {
    disposed = true;
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
      socket.close();
    }
  };
}

/**
 * Stop an active recording
 * @param {string} recordingId
 * @returns {Promise<Object>}
 */
export async function stopRecording(recordingId) {
  const response = await fetchWithAuthRetry(`${API_BASE}/api/stop-recording/${encodeURIComponent(recordingId)}`, {
    method: 'POST',
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '' }));
    throw new Error(toApiErrorMessage(response, error.detail, 'Failed to stop recording'));
  }

  return response.json();
}

/**
 * Get integration configuration status for Slack/Jira/Notion.
 * @returns {Promise<Object>}
 */
export async function getIntegrationsStatus() {
  const response = await fetchWithAuthRetry(`${API_BASE}/api/integrations/status`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '' }));
    throw new Error(toApiErrorMessage(response, error.detail, 'Failed to fetch integrations status'));
  }

  return response.json();
}

/**
 * Run a smoke test that dispatches to configured integrations.
 * @param {Object} payload
 * @returns {Promise<Object>}
 */
export async function runIntegrationsSmokeTest(payload = {}) {
  const response = await fetchWithAuthRetry(`${API_BASE}/api/integrations/test`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '' }));
    throw new Error(toApiErrorMessage(response, error.detail, 'Failed to run integrations smoke test'));
  }

  return response.json();
}

/**
 * Start OAuth flow for one integration provider.
 * @param {string} provider - slack | jira | notion
 * @param {string} nextUrl
 * @returns {Promise<Object>}
 */
export async function startIntegrationOAuth(provider, nextUrl) {
  const params = new URLSearchParams({ next_url: nextUrl || '' });
  const response = await fetchWithAuthRetry(`${API_BASE}/api/integrations/oauth/${encodeURIComponent(provider)}/start?${params.toString()}`, {
    method: 'GET',
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '' }));
    throw new Error(toApiErrorMessage(response, error.detail, 'Failed to start OAuth flow'));
  }

  return response.json();
}

/**
 * Save provider-specific integration configuration.
 * @param {Object} payload - { provider, config }
 * @returns {Promise<Object>}
 */
export async function saveIntegrationConfig(payload) {
  const response = await fetchWithAuthRetry(`${API_BASE}/api/integrations/config`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '' }));
    throw new Error(toApiErrorMessage(response, error.detail, 'Failed to save integration configuration'));
  }

  return response.json();
}

/**
 * Disconnect one integration provider for a user.
 * @param {Object} payload - { provider }
 * @returns {Promise<Object>}
 */
export async function disconnectIntegration(payload) {
  const response = await fetchWithAuthRetry(`${API_BASE}/api/integrations/disconnect`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '' }));
    throw new Error(toApiErrorMessage(response, error.detail, 'Failed to disconnect integration'));
  }

  return response.json();
}
