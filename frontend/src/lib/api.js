/**
 * API client for OceanLabs backend.
 * Uses Supabase JWT for authentication.
 */

import { supabase } from './supabase';

export const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

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
async function getAuthToken() {
  try {
    const { data: { session } } = await supabase.auth.getSession();
    return session?.access_token || null;
  } catch {
    return null;
  }
}

/**
 * Build headers with JWT authorization.
 * @param {Object} extraHeaders
 * @returns {Promise<Headers>}
 */
async function buildAuthHeaders(extraHeaders = {}) {
  const token = await getAuthToken();
  const headers = new Headers({
    'Content-Type': 'application/json',
    ...extraHeaders,
  });
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  return headers;
}

function toApiErrorMessage(response, detail, fallbackMessage) {
  const normalizedDetail = typeof detail === 'string' ? detail.trim() : '';

  if (response.status === 404 && normalizedDetail.toLowerCase() === 'not found') {
    return `Backend endpoint not found at ${API_BASE}. Start this project backend and set VITE_API_BASE_URL if needed.`;
  }

  if (response.status === 401) {
    // Force re-login
    supabase.auth.signOut();
    setTimeout(() => window.location.href = '/auth', 100);
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
  const headers = await buildAuthHeaders();
  const response = await fetch(`${API_BASE}/api/start-recording`, {
    method: 'POST',
    headers,
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
  const headers = await buildAuthHeaders();
  const response = await fetch(`${API_BASE}/api/recordings`, { headers });

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
  const headers = await buildAuthHeaders();
  const response = await fetch(`${API_BASE}/api/recordings/${encodeURIComponent(recordingId)}`, { headers });

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

  // Get token synchronously via getSession() (may be cached)
  let token = '';
  try {
    const { data: { session } } = supabase.auth.getSession();
    token = session?.access_token || '';
  } catch {
    // Silent fail - WebSocket will connect without token
  }

  const streamPath = `/api/recordings/${encodeURIComponent(safeRecordingId)}/stream`;
  const socketUrl = token
    ? `${API_WS_BASE}${streamPath}?token=${encodeURIComponent(token)}`
    : `${API_WS_BASE}${streamPath}`;

  const socket = new WebSocket(socketUrl);

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

  return () => {
    if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
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
  const headers = await buildAuthHeaders();
  const response = await fetch(`${API_BASE}/api/stop-recording/${encodeURIComponent(recordingId)}`, {
    method: 'POST',
    headers,
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
  const headers = await buildAuthHeaders();
  const response = await fetch(`${API_BASE}/api/integrations/status`, { headers });

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
  const headers = await buildAuthHeaders();
  const response = await fetch(`${API_BASE}/api/integrations/test`, {
    method: 'POST',
    headers,
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
  const headers = await buildAuthHeaders();
  const token = await getAuthToken();
  if (!token) throw new Error('Authentication required');

  const params = new URLSearchParams({ next_url: nextUrl || '' });
  const response = await fetch(`${API_BASE}/api/integrations/oauth/${encodeURIComponent(provider)}/start?${params.toString()}`, {
    method: 'GET',
    headers,  // Authorization header
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
  const headers = await buildAuthHeaders();
  const response = await fetch(`${API_BASE}/api/integrations/config`, {
    method: 'POST',
    headers,
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
  const headers = await buildAuthHeaders();
  const response = await fetch(`${API_BASE}/api/integrations/disconnect`, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '' }));
    throw new Error(toApiErrorMessage(response, error.detail, 'Failed to disconnect integration'));
  }

  return response.json();
}
