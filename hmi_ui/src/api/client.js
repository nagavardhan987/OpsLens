/**
 * OpsLens API Client
 * Connects React frontend directly to Component 11 Live Orchestrator Gateway.
 * Strict adherence to the Shared System Contract schemas.
 */

// In EOTE/Web Browser deployments the OpsLens UI may be hosted on a different
// edge PC than the HMI runtime. Set VITE_API_BASE_URL to that edge host; the
// localhost default keeps the all-in-one development setup unchanged.
export const API_BASE = import.meta.env?.VITE_API_BASE_URL || 'http://localhost:8001/api';
export const API_ORIGIN = API_BASE.replace(/\/api\/?$/, '');

export async function getIntegrationStatus() {
  const response = await fetchWithTimeout(`${API_BASE}/integration/status`, {}, 5000);
  if (!response.ok) throw new Error(`Integration status returned HTTP ${response.status}`);
  return response.json();
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 8000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: options.signal || controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

export async function getSop(sopId, revision = '', sha256 = '') {
  const query = new URLSearchParams();
  if (revision) query.set('revision', revision);
  if (sha256) query.set('sha256', sha256);
  const suffix = query.size ? `?${query}` : '';
  const res = await fetch(`${API_BASE}/sops/${encodeURIComponent(sopId)}${suffix}`);
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    const detail = typeof payload.detail === 'string' ? payload.detail : '';
    throw new Error(detail || `Procedure service returned HTTP ${res.status}.`);
  }
  return res.json();
}

export async function listSopLibrary() {
  const res = await fetch(`${API_BASE}/sops/library`);
  if (!res.ok) throw new Error(`Failed to load SOP library: ${res.statusText}`);
  return res.json();
}

export async function ingestSopPdf(file, metadata) {
  const params = new URLSearchParams({ ...metadata, filename: file.name });
  const res = await fetch(`${API_BASE}/sops/ingest-pdf?${params}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/pdf', Prefer: 'respond-async' },
    body: file,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    const error = new Error(typeof detail === 'string' ? detail : detail?.message || `PDF ingestion failed: HTTP ${res.status}`);
    error.stage = typeof detail === 'object' ? detail.stage : undefined;
    error.manualReviewRequired = typeof detail === 'object' ? detail.manual_review_required : false;
    error.status = res.status;
    throw error;
  }
  return data;
}

export async function getSopIngestionJob(jobId) {
  const res = await fetch(`${API_BASE}/sops/ingestion-jobs/${encodeURIComponent(jobId)}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    throw new Error(typeof detail === 'string' ? detail : detail?.message || `Ingestion status unavailable: HTTP ${res.status}`);
  }
  return data;
}

export function getSopSourceUrl(sopId, revision = '', sha256 = '') {
  const query = new URLSearchParams();
  if (revision) query.set('revision', revision);
  if (sha256) query.set('sha256', sha256);
  const suffix = query.size ? `?${query}` : '';
  return `${API_BASE}/sops/${encodeURIComponent(sopId)}/source${suffix}`;
}

/**
 * Fetch list of registered scenarios.
 */
export async function listScenarios() {
  const res = await fetch(`${API_BASE}/scenarios`);
  if (!res.ok) throw new Error(`Failed to fetch scenarios: ${res.statusText}`);
  const data = await res.json();
  return data.scenarios || [];
}

/**
 * Trigger background execution of a synthetic telemetry scenario.
 */
export async function runScenario(scenarioId, speedMultiplier = 10.0) {
  const res = await fetch(`${API_BASE}/scenarios/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      scenario_id: scenarioId,
      speed_multiplier: speedMultiplier,
    }),
  });
  if (!res.ok) throw new Error(`Failed to start scenario: ${res.statusText}`);
  return res.json();
}

export async function getScenarioStatus() {
  const res = await fetch(`${API_BASE}/scenarios/status`);
  if (!res.ok) throw new Error(`Failed to fetch scenario status: ${res.statusText}`);
  return res.json();
}

export async function applySimulatedCorrectiveAction() {
  const res = await fetch(`${API_BASE}/scenarios/corrective-action`, { method: 'POST' });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Simulated corrective action failed: ${res.statusText}`);
  return data;
}

export async function triggerAlarmRepeat() {
  const res = await fetch(`${API_BASE}/scenarios/trigger-alarm-repeat`, { method: 'POST' });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : res.statusText || 'Unknown server error';
    throw new Error(`Repeat alarm failed (HTTP ${res.status}): ${detail}`);
  }
  return data;
}

/**
 * Reset pipeline state in backend.
 */
export async function resetDemo() {
  const res = await fetch(`${API_BASE}/demo/reset`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed to reset demo: ${res.statusText}`);
  return res.json();
}

/**
 * Query current system status and envelope baselines.
 */
export async function getSystemStatus() {
  const res = await fetch(`${API_BASE}/status`);
  if (!res.ok) throw new Error(`Failed to fetch status: ${res.statusText}`);
  return res.json();
}

/**
 * Query open (unresolved) event IDs.
 */
export async function getOpenEvents() {
  const res = await fetchWithTimeout(`${API_BASE}/events/open`);
  if (!res.ok) throw new Error(`Failed to fetch open events: ${res.statusText}`);
  const data = await res.json();
  const list = Array.isArray(data) ? data : (data.open_events || []);
  return list.map((item) => (typeof item === 'string' ? { event_id: item } : item));
}

export async function getRecentEvents(limit = 10) {
  const res = await fetchWithTimeout(`${API_BASE}/events/recent?limit=${encodeURIComponent(limit)}`);
  if (!res.ok) throw new Error(`Failed to fetch recent alarms: ${res.statusText}`);
  const data = await res.json();
  return data.events || [];
}

/**
 * Fetch active incidents ordered by deterministic urgency ranking.
 * Returns ranked_incidents array with ranking_position and ranking_rationale.
 */
export async function getRankedIncidents(limit = 20) {
  try {
    const res = await fetchWithTimeout(`${API_BASE}/incidents/ranked?limit=${encodeURIComponent(limit)}`);
    if (!res.ok) return null;
    const data = await res.json();
    return data;
  } catch {
    return null;
  }
}

/**
 * Single point of truth cross-table join query for an event.
 * Returns joined CandidateEvent, CorrelatedEvent, EventStory, Evidence, SopMatch, Guidance, and OperatorActions.
 */
export async function getFullEvent(eventId) {
  const res = await fetchWithTimeout(`${API_BASE}/events/${eventId}`);
  if (!res.ok) {
    if (res.status === 404) return null;
    throw new Error(`Failed to fetch full event: ${res.statusText}`);
  }
  return res.json();
}

export async function askOpsLens(eventId, question, conversationId) {
  const res = await fetch(`${API_BASE}/assistant/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ event_id: eventId, question, conversation_id: conversationId || undefined }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : `Assistant request failed (${res.status})`;
    const requestId = res.headers.get('X-Request-ID');
    throw new Error(requestId ? `${detail} (Request ID: ${requestId})` : detail);
  }
  return data;
}

export async function getImpactMetrics(params = {}) {
  const query = new URLSearchParams();
  if (params.scope) query.set('scope', params.scope);
  if (params.eventId) query.set('event_id', params.eventId);
  if (params.baselineMttr) query.set('baseline_mttr', params.baselineMttr);
  const qs = query.toString();
  const url = `${API_BASE}/metrics/impact${qs ? `?${qs}` : ''}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to fetch impact metrics: ${res.statusText}`);
  return res.json();
}

export async function getCopilotHealth() {
  const res = await fetch(`${API_BASE}/copilot/health`);
  if (!res.ok) throw new Error(`Failed to fetch copilot health: ${res.statusText}`);
  return res.json();
}

function parseSseBlock(block, handlers) {
  const lines = block.split('\n');
  let eventName = 'message';
  const dataLines = [];
  for (const line of lines) {
    if (line.startsWith('event:')) eventName = line.slice(6).trim();
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return;
  const payload = JSON.parse(dataLines.join('\n'));
  if (eventName === 'token') handlers.onToken?.(payload.text || '');
  else if (eventName === 'status') handlers.onStatus?.(payload);
  else if (eventName === 'error') handlers.onError?.(payload);
  else if (eventName === 'done') handlers.onDone?.(payload);
}

export async function askOpsLensStream({ eventId, question, conversationId, signal, onToken, onStatus, onError, onDone }) {
  const res = await fetch(`${API_BASE}/assistant/ask/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ event_id: eventId, question, conversation_id: conversationId || undefined }),
    signal,
  });
  if (!res.ok || !res.body) {
    const data = await res.json().catch(() => ({}));
    const detail = typeof data.detail === 'string' ? data.detail : `Assistant stream failed (${res.status})`;
    const requestId = res.headers.get('X-Request-ID');
    throw new Error(requestId ? `${detail} (Request ID: ${requestId})` : detail);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let streamFailure = false;
  const handlers = {
    onToken, onStatus, onDone,
    onError: (payload) => { streamFailure = true; onError?.(payload); },
  };
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop() || '';
    for (const part of parts) parseSseBlock(part, handlers);
  }
  if (buffer.trim()) parseSseBlock(buffer, handlers);
  // A streamed error event does not reject fetch by itself. Reject here so the
  // drawer can retry the deterministic JSON endpoint, which may still provide
  // a grounded answer when only the stream/provider path failed.
  if (streamFailure) throw new Error('Assistant stream failed; retrying with the incident evidence endpoint.');
}

/**
 * Log an operator intervention action to component 9 audit table.
 */
export async function logOperatorAction(params) {
  const event_id = params.event_id || params.eventId;
  const operator = params.operator || params.operator_id || 'J. Rivera (Shift 2)';
  const action_type = params.action_type || params.actionType;
  const notes = params.notes || null;
  const timestamp = params.timestamp || new Date().toISOString();

  const res = await fetch(`${API_BASE}/actions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      event_id,
      operator,
      action_type,
      notes,
      timestamp,
    }),
  });
  if (!res.ok) {
    const error = new Error('Operator action request failed.');
    error.status = res.status;
    throw error;
  }
  return res.json();
}

/** Mark an incident unresolved through the dedicated status-transition endpoint. */
export async function markIncidentUnresolved({ eventId, operator, reason = null, timestamp = new Date().toISOString() }) {
  const res = await fetch(`${API_BASE}/incidents/${encodeURIComponent(eventId)}/unresolved`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ operator, reason, timestamp }),
  });
  if (!res.ok) {
    const error = new Error('Incident status request failed.');
    error.status = res.status;
    throw error;
  }
  return res.json();
}

/**
 * Query / compile shift handover summary.
 */
export async function compileHandover(shiftStart, shiftEnd) {
  const now = new Date();
  const start = shiftStart || new Date(now.getTime() - 12 * 3600 * 1000).toISOString();
  const end = shiftEnd || new Date(now.getTime() + 4 * 3600 * 1000).toISOString();

  const res = await fetch(`${API_BASE}/handover`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      shift_start: start,
      shift_end: end,
    }),
  });
  if (!res.ok) throw new Error(`Failed to compile handover: ${res.statusText}`);
  const data = await res.json();

  // If events is an array of IDs, enrich them with event details
  if (Array.isArray(data.events) && data.events.length > 0 && typeof data.events[0] === 'string') {
    const enriched = await Promise.all(
      data.events.map(async (eid) => {
        try {
          const full = await getFullEvent(eid);
          return {
            event_id: eid,
            primary_tag: full?.primary_tag || eid,
            causal_label: full?.story?.causal_label || full?.candidate?.primary_tag || eid,
            likely_contributor: full?.evidence?.likely_contributor_tag || 'Under Investigation',
            trigger_timestamp: full?.trigger_timestamp || full?.story?.steps?.[0]?.timestamp || new Date().toISOString(),
            status: full?.status || 'OPEN',
            is_open: full?.is_open ?? true,
          };
        } catch {
          return { event_id: eid, primary_tag: eid, status: 'OPEN' };
        }
      })
    );
    data.events = enriched;
    if (enriched.length > 0) {
      data.likely_contributor = enriched[enriched.length - 1].likely_contributor;
      data.incident = enriched[enriched.length - 1].causal_label;
    }
  }

  return data;
}

/**
 * Subscribe to the live EventStream (SSE).
 * Calls onEvent(fullEvent) whenever a new event completes the pipeline.
 * Returns an unsubscribe function.
 */
export function subscribeToEventStream(onEvent, onError) {
  const eventSource = new EventSource(`${API_BASE}/events/stream`);

  eventSource.onmessage = (event) => {
    try {
      if (!event.data || event.data === 'connected' || event.data === ': keepalive') {
        return;
      }
      const data = JSON.parse(event.data);
      if (data && data.event_id) {
        onEvent(data);
      }
    } catch (e) {
      console.warn('[EventSource] Parse error:', e);
    }
  };

  eventSource.onerror = (err) => {
    console.warn('[EventSource] Connection error/retry:', err);
    if (onError) onError(err);
  };

  return () => {
    eventSource.close();
  };
}
