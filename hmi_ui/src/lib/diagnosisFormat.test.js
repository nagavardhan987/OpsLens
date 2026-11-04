import test from 'node:test';
import assert from 'node:assert/strict';
import { parseDiagnosis } from './diagnosisFormat.js';

test('parses headings, labels and the fallback note', () => {
  const r = parseDiagnosis('> DETERMINISTIC FALLBACK — not AI-generated\n\n## 1. Incident summary\n- CONFIRMED: level 3.85 m\n## 3. Possible root causes\n- HYPOTHESIS: impeller clogged\n- **UNKNOWN**: fault code');
  assert.equal(r.note, 'DETERMINISTIC FALLBACK — not AI-generated');
  assert.deepEqual(r.sections.map((s) => s.title), ['Incident summary', 'Possible root causes']);
  assert.deepEqual(r.sections[0].items[0], { label: 'CONFIRMED', text: 'level 3.85 m' });
  assert.equal(r.sections[1].items[1].label, 'UNKNOWN');
});

test('partial streamed text still renders', () => {
  const r = parseDiagnosis('## 1. Incident sum');
  assert.equal(r.sections[0].title, 'Incident sum');
});
