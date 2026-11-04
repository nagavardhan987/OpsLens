import test from 'node:test';
import assert from 'node:assert/strict';
import { calculateEvidenceSupport } from './evidenceSupport.js';

test('SOP approval does not change the incident evidence availability score', () => {
  const withoutSop = calculateEvidenceSupport({
    question: 'Why did this alarm trigger?',
    supporting_readings: [{ tag: 'PIT-02-PRS' }],
    supporting_events: [{ tag: 'ALM-P02-HP' }],
    uncertainty_status: 'hypothesis_requires_operator_verification',
  });
  const withSop = calculateEvidenceSupport({
    question: 'What does the SOP say?',
    supporting_readings: [{ tag: 'PIT-02-PRS' }],
    supporting_events: [{ tag: 'ALM-P02-HP' }],
    sources: [{ approved: true }],
    uncertainty_status: 'source_retrieved',
  });
  assert.equal(withSop.score, withoutSop.score);
  assert.equal(withSop.maxScore, 75);
  assert.equal(withSop.calibrated, false);
});

test('unverified SOP status does not cap or reduce incident evidence availability', () => {
  const result = calculateEvidenceSupport({
    question: 'Show the relevant SOP procedure',
    supporting_readings: [{ tag: 'PIT-02-PRS' }],
    supporting_events: [{ tag: 'ALM-P02-HP' }],
    sources: [{ approved: false }],
    uncertainty_status: 'insufficient_approved_procedure',
  });
  assert.equal(result.score, 65);
  assert.equal(result.components.length, 4);
  assert.equal(result.components.some((item) => /SOP/i.test(item.label)), false);
});

test('insufficient evidence does not receive sufficiency points', () => {
  const result = calculateEvidenceSupport({ uncertainty_status: 'insufficient_incident_evidence' });
  assert.equal(result.components.find((item) => item.label === 'Incident evidence sufficient for explanation').points, 0);
});

test('duplicate evidence within an availability category does not increase the score', () => {
  const one = calculateEvidenceSupport({
    supporting_readings: [{ tag: 'PIT-02-PRS' }],
    supporting_events: [{ tag: 'ALM-P02-HP' }],
    similar_incidents: [{ event_id: 'event-1' }],
    uncertainty_status: 'hypothesis_requires_operator_verification',
  });
  const many = calculateEvidenceSupport({
    supporting_readings: Array.from({ length: 20 }, (_, index) => ({ tag: `PIT-${index}` })),
    supporting_events: Array.from({ length: 20 }, (_, index) => ({ tag: `ALM-${index}` })),
    similar_incidents: Array.from({ length: 20 }, (_, index) => ({ event_id: `event-${index}` })),
    uncertainty_status: 'hypothesis_requires_operator_verification',
  });
  assert.equal(one.score, many.score);
  assert.equal(one.maxScore, 75);
  assert.equal(one.score, 75);
});
