import test from 'node:test';
import assert from 'node:assert/strict';
import {
  assistantDisplayStatus,
  assistantFallbackExplanation,
  formatAbsoluteChange,
  formatMeasurement,
  formatRelativeChange,
  formatTimestamp,
  getVerifiedSopReferences,
  getUnverifiedSopReferences,
  sopDisplayStatus,
} from './assistantPresentation.js';

test('response status never calls deterministic output AI generated', () => {
  assert.equal(assistantDisplayStatus({ llm_used: true, fallback_used: false }).tone, 'ai');
  assert.equal(assistantDisplayStatus({ llm_used: false, fallback_used: true }).tone, 'evidence');
  assert.equal(assistantDisplayStatus({ llm_used: false, fallback_used: false }).tone, 'evidence');
  assert.equal(assistantDisplayStatus({ llm_used: true, fallback_used: true }).tone, 'evidence');
  assert.equal(assistantDisplayStatus({ llm_used: false, fallback_used: true, fallback_reason: 'ungrounded_numeric_value' }).text,
    'Evidence-based answer');
  assert.equal(assistantDisplayStatus({ llm_used: true, fallback_used: false }).text, 'AI-generated');
});

test('fallback notice distinguishes provider errors from grounding rejection', () => {
  assert.match(assistantFallbackExplanation({ fallback_reason: 'timeout' }), /provider timed out/i);
  assert.match(assistantFallbackExplanation({ fallback_reason: 'ungrounded_numeric_value' }), /did not pass grounding checks/i);
  assert.match(assistantFallbackExplanation({ fallback_reason: 'deterministic_record_grounded', selected_provider: 'none' }), /No language model is enabled/i);
});

test('display helpers keep physical units, percentage points, and relative percentages distinct', () => {
  assert.equal(formatMeasurement(7.8, 'A'), '7.8 A');
  assert.equal(formatAbsoluteChange(-32.52, '%'), 'decreased by 32.52 percentage points');
  assert.equal(formatAbsoluteChange(4.2, 'bar'), 'increased by 4.2 bar');
  assert.equal(formatRelativeChange(-40.65), '-40.6% relative change');
  assert.equal(formatMeasurement(Number.NaN, 'L/min'), '—');
});

test('timestamps display localized readable time and missing/invalid values are explicit', () => {
  assert.notEqual(formatTimestamp('2026-10-16T09:59:00Z', 'en-GB'), 'Time unavailable');
  assert.equal(formatTimestamp(null), 'Time unavailable');
  assert.equal(formatTimestamp('not-a-timestamp'), 'Time unavailable');
});

test('only resolved SOP steps with meaningful stored content are shown as references', () => {
  const unresolved = {
    operator_response: { bottom_line: 'Relevant SOP section not available in current records.' },
    sources: [{ sop_id: 'SOP-UNKNOWN', section: 'step', text: 'A generated unsupported instruction.', verified: false }],
  };
  assert.deepEqual(getVerifiedSopReferences(unresolved), []);
  const resolved = { sources: [{ sop_id: 'SOP-P02-VLV-01', section: 'Step 1', step_title: 'Step 1',
    text: 'Inspect the recorded valve-position feedback against the stored procedure.', verified: true, approved: true }] };
  assert.equal(getVerifiedSopReferences(resolved).length, 1);
  assert.deepEqual(getVerifiedSopReferences({
    ...resolved,
    operator_response: { bottom_line: 'Relevant SOP section not available in the current records.' },
  }), []);
  assert.deepEqual(getVerifiedSopReferences({ sources: [{ ...resolved.sources[0], text: '' }] }), []);
  // Unapproved sources are never returned as verified references
  assert.deepEqual(getVerifiedSopReferences({
    sources: [{ ...resolved.sources[0], approved: false }],
  }), []);
  const unapprovedExcerpt = {
    operator_response: { bottom_line: 'No applicable approved SOP procedure was retrieved.' },
    sources: [{ ...resolved.sources[0], approved: false, document_status: 'Approval status not verified' }],
  };
  assert.equal(getUnverifiedSopReferences(unapprovedExcerpt).length, 1,
    'retrieved excerpts remain visible with a warning even when no approved procedure was found');
  assert.deepEqual(getVerifiedSopReferences(unapprovedExcerpt), []);
  // UI does not claim SOP grounding when procedure is unverified
  const ungroundedStatus = assistantDisplayStatus({
    llm_used: true,
    fallback_used: false,
    selected_provider: 'Groq',
    uncertainty_status: 'insufficient_approved_procedure',
  });
  assert.equal(ungroundedStatus.text, 'AI-generated');
  assert.doesNotMatch(ungroundedStatus.text, /Groq|grounded via/i);
});

test('SOP unavailable and retrieval failure have explicit non-verified display states', () => {
  assert.equal(sopDisplayStatus({ status: 'not_retrieved' }), 'No approved procedure found');
  assert.equal(sopDisplayStatus({ status: 'retrieval_unavailable' }), 'Unavailable');
  assert.equal(sopDisplayStatus({ status: 'reference_unapproved' }), 'Approval unverified');
  assert.equal(sopDisplayStatus({ status: 'reference_approved' }), 'Approved');
  assert.deepEqual(getVerifiedSopReferences({
    sop_resolution: { status: 'not_retrieved' },
    operator_response: { bottom_line: 'DPT-110-SCR reading supports the alarm association.' },
    sources: [],
  }), [], 'SOP absence must not manufacture a verified reference');
});
