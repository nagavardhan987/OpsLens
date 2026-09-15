/**
 * OpsLens API Client
 * Connects React frontend directly to Component 11 Live Orchestrator Gateway.
 * Strict adherence to the Shared System Contract schemas.
 */

const API_BASE = 'http://localhost:8000/api';

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
  const res = await fetch(`${API_BASE}/events/open`);
  if (!res.ok) throw new Error(`Failed to fetch open events: ${res.statusText}`);
  const data = await res.json();
  const list = Array.isArray(data) ? data : (data.open_events || []);
  return list.map((item) => (typeof item === 'string' ? { event_id: item } : item));
}

/**
 * Single point of truth cross-table join query for an event.
 * Returns joined CandidateEvent, CorrelatedEvent, EventStory, Evidence, SopMatch, Guidance, and OperatorActions.
 */
export async function getFullEvent(eventId) {
  const res = await fetch(`${API_BASE}/events/${eventId}`);
  if (!res.ok) {
    if (res.status === 404) return null;
    throw new Error(`Failed to fetch full event: ${res.statusText}`);
  }
  return res.json();
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
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Action rejected: ${res.statusText}`);
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
