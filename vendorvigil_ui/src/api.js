/**
 * VendorVigil — API Client (v1)
 * Connects to FastAPI v1 backend.
 * Read-only client for the presentation dashboard.
 * All mutation endpoints are intentionally excluded.
 */

const BASE = process.env.REACT_APP_API_URL || '';

/** GET /api/v1/health/ready */
export async function checkHealth() {
  const res = await fetch(`${BASE}/api/v1/health/ready`);
  if (!res.ok) { throw new Error(`API ${res.url}: ${res.status}`); }
  return res.json();
}

/** GET /api/v1/assessments/active */
export async function getActiveAssessment() {
  const res = await fetch(`${BASE}/api/v1/assessments/active`);
  if (!res.ok) { throw new Error(`API ${res.url}: ${res.status}`); }
  return res.json();
}

/** GET /api/v1/assessments/latest */
export async function getLatestAssessment() {
  const res = await fetch(`${BASE}/api/v1/assessments/latest`);
  if (!res.ok) { throw new Error(`API ${res.url}: ${res.status}`); }
  return res.json();
}

/** GET /api/v1/assessments/{id} */
export async function getAssessment(assessmentId) {
  const res = await fetch(`${BASE}/api/v1/assessments/${assessmentId}`);
  if (!res.ok) return null;
  if (!res.ok) { throw new Error(`API ${res.url}: ${res.status}`); }
  return res.json();
}

/** GET /api/v1/dashboard/summary */
export async function getDashboardSummary() {
  const res = await fetch(`${BASE}/api/v1/dashboard/summary`);
  if (!res.ok) { throw new Error(`API ${res.url}: ${res.status}`); }
  return res.json();
}

/**
 * SSE stream for real-time assessment events.
 * Uses v1 endpoint with named event listeners.
 * Supports Last-Event-ID for resume.
 *
 * @param {string} assessmentId
 * @param {object} handlers - { onCreated, onProgress, onCompleted, onFailed, onHeartbeat, onError }
 * @returns {() => void} cleanup function
 */
export function streamAssessmentEvents(assessmentId, handlers = {}) {
  const {
    onCreated = () => {},
    onProgress = () => {},
    onCompleted = () => {},
    onFailed = () => {},
    onHeartbeat = () => {},
    onError = () => {},
  } = handlers;

  const evtSource = new EventSource(`${BASE}/api/v1/assessments/${assessmentId}/events`);

  evtSource.addEventListener('assessment.created', (event) => {
    try { onCreated(JSON.parse(event.data)); } catch (e) { console.warn('SSE parse error:', e); }
  });

  evtSource.addEventListener('assessment.progress', (event) => {
    try { onProgress(JSON.parse(event.data)); } catch (e) { console.warn('SSE parse error:', e); }
  });

  evtSource.addEventListener('assessment.completed', (event) => {
    try {
      onCompleted(JSON.parse(event.data));
      evtSource.close();
    } catch (e) { console.warn('SSE parse error:', e); }
  });

  evtSource.addEventListener('assessment.failed', (event) => {
    try {
      onFailed(JSON.parse(event.data));
      evtSource.close();
    } catch (e) { console.warn('SSE parse error:', e); }
  });

  evtSource.addEventListener('heartbeat', (event) => {
    try { onHeartbeat(JSON.parse(event.data)); } catch (e) { /* ignore heartbeat parse errors */ }
  });

  evtSource.onerror = (err) => {
    onError(err);
  };

  return () => evtSource.close();
}
