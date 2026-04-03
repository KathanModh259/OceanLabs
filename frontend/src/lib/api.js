export const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8012';

function toApiErrorMessage(response, detail, fallbackMessage) {
  const normalizedDetail = typeof detail === 'string' ? detail.trim() : ''

  if (response.status === 404 && normalizedDetail.toLowerCase() === 'not found') {
    return `Backend endpoint not found at ${API_BASE}. Start this project backend and set VITE_API_BASE_URL if needed.`
  }

  return normalizedDetail || fallbackMessage
}

/**
 * Start a meeting recording
 * @param {Object} data - { title, platform, url, language, duration_minutes }
 * @returns {Promise<Object>} - { recording_id, status }
 */
export async function startRecording(data) {
  const response = await fetch(`${API_BASE}/api/start-recording`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
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
  const response = await fetch(`${API_BASE}/api/recordings`);

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
  const response = await fetch(`${API_BASE}/api/recordings/${recordingId}`)

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '' }))
    throw new Error(toApiErrorMessage(response, error.detail, 'Failed to fetch recording details'))
  }

  return response.json()
}