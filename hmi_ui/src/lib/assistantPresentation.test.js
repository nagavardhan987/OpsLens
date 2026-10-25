import test from 'node:test';
import assert from 'node:assert/strict';
import {
  assistantDisplayStatus,
  formatAbsoluteChange,
  formatMeasurement,
  formatRelativeChange,
  formatTimestamp,
} from './assistantPresentation.js';

test('response status never calls deterministic output AI generated', () => {
  assert.equal(assistantDisplayStatus({ llm_used: true, fallback_used: false }).tone, 'ai');
  assert.equal(assistantDisplayStatus({ llm_used: false, fallback_used: true }).tone, 'fallback');
  assert.equal(assistantDisplayStatus({ llm_used: false, fallback_used: false }).tone, 'evidence');
  assert.equal(assistantDisplayStatus({ llm_used: true, fallback_used: true }).tone, 'fallback');
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
