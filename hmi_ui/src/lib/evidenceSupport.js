const INSUFFICIENT_INCIDENT_EVIDENCE = new Set([
  'insufficient_incident_evidence',
  'insufficient_historical_readings',
]);

/**
 * A transparent incident-evidence availability score. SOP approval is a
 * separate document-control state and contributes no points here. The fixed
 * 75-point denominator is 30 + 20 + 10 + 15, independent of incident type.
 * Each category is presence-scored once, so duplicate records do not add
 * points. Missing categories receive zero. This is not a calibrated measure
 * of completeness against expected incident-specific evidence, an LLM
 * confidence estimate, or a probability of the proposed cause.
 */
export function calculateEvidenceSupport(answer) {
  if (!answer) return null;
  const readings = Array.isArray(answer.supporting_readings) ? answer.supporting_readings : [];
  const events = Array.isArray(answer.supporting_events) ? answer.supporting_events : [];
  const similar = Array.isArray(answer.similar_incidents) ? answer.similar_incidents : [];
  const uncertainty = String(answer.uncertainty_status || '').toLowerCase();
  const components = [
    { label: 'Timestamped readings available', points: readings.length ? 30 : 0, max: 30 },
    { label: 'Recorded event sequence available', points: events.length ? 20 : 0, max: 20 },
    { label: 'Comparable incident history recorded', points: similar.length ? 10 : 0, max: 10 },
    { label: 'Incident evidence sufficient for explanation', points: INSUFFICIENT_INCIDENT_EVIDENCE.has(uncertainty) ? 0 : 15, max: 15 },
  ];
  const score = components.reduce((sum, item) => sum + item.points, 0);
  const maxScore = components.reduce((sum, item) => sum + item.max, 0);
  return { score, maxScore, components, calibrated: false };
}
