import test from 'node:test';
import assert from 'node:assert/strict';
import { PRIMARY_SCENARIO_CATALOG, resolvePrimaryScenarioCatalog } from './scenarioCatalog.js';

test('six incidents from the incident map, each with its SOP', () => {
  const { scenarios } = resolvePrimaryScenarioCatalog(PRIMARY_SCENARIO_CATALOG);
  assert.deepEqual(scenarios.map((s) => s.name), [
    'Rags jam the bar screen', 'The lift station pumps clog', 'Nocardia foam on the aeration tank',
    'RAS pump fails, sludge blanket rises', 'CHP engine trips, gas holder fills', 'Centrate poisons the plant inlet',
  ]);
  assert.deepEqual(scenarios.map((s) => s.sop_id), [
    'SOP-INL-001', 'SOP-LFT-001', 'SOP-BIO-001', 'SOP-BIO-002', 'SOP-GAS-001', 'SOP-SLD-001',
  ]);
  assert.ok(scenarios.every((s) => s.sop_approval_status.includes('NOT APPROVED')));
  assert.ok(scenarios.every((s) => !/\bapproved\b/i.test(s.sop_approval_status.replace(/NOT APPROVED/, ''))));
  assert.equal(scenarios.find((s) => s.scenario_id === 'centrifuge_capture').sop_coverage, 'partial');
});

test('legacy or removed scenarios from an old API cannot reappear', () => {
  const old = [
    { scenario_id: 'valve_restriction', name: 'Pump-02 — Valve Restriction' },
    { scenario_id: 'filters_uv_disinfection_failure', name: 'Filters / UV' },
    { scenario_id: 'monitoring_due', name: 'Sampling due' },
    { scenario_id: 'wet_well_high_level', name: 'Old name', sop_id: 'SOP-XYZ', approval_status: 'Approved' },
  ];
  const { scenarios } = resolvePrimaryScenarioCatalog(old);
  assert.equal(scenarios.length, 6);
  assert.ok(!scenarios.some((s) => ['valve_restriction', 'filters_uv_disinfection_failure', 'monitoring_due'].includes(s.scenario_id)));
  const lift = scenarios.find((s) => s.scenario_id === 'wet_well_high_level');
  assert.equal(lift.name, 'The lift station pumps clog');
  assert.equal(lift.sop_id, 'SOP-LFT-001');
});
