import test from 'node:test';
import assert from 'node:assert/strict';
import { PRIMARY_SCENARIO_CATALOG, resolvePrimaryScenarioCatalog } from './scenarioCatalog.js';

test('primary scenario catalog has seven mapped SOP cases and three no equipment SOP cases', () => {
  const result = resolvePrimaryScenarioCatalog(PRIMARY_SCENARIO_CATALOG);
  assert.equal(result.scenarios.length, 10);
  assert.equal(result.withSop.length, 7);
  assert.equal(result.withoutEquipmentSop.length, 3);
  assert.deepEqual(result.withSop.map(({ sop_id }) => sop_id), [
    'SOP-LFT-001', 'SOP-INL-001', 'SOP-BIO-001', 'SOP-BIO-002',
    'SOP-GAS-001', 'SOP-SLD-001', 'SOP-LAB-001',
  ]);
  assert.deepEqual(result.withoutEquipmentSop.map(({ scenario_id }) => scenario_id), [
    'valve_restriction', 'bearing_wear', 'filter_sensor_fault',
  ]);
});

test('legacy API scenarios cannot replace or repopulate the primary list', () => {
  const oldApiResponse = [
    { scenario_id: 'wet_well_high_level', name: 'Lift Station — Wet-Well High-High Level' },
    { scenario_id: 'screen_differential_pressure', name: 'Inlet Works — Screen Differential Pressure High' },
    { scenario_id: 'low_do_ammonia_rise', name: 'Aeration — Low DO / Ammonia Rise' },
    { scenario_id: 'seal_leak', name: 'Pump-02 Mechanical Seal Leak' },
    { scenario_id: 'sensor_fault', name: 'PIT-02-PRS Sensor Fault / False Positive' },
    { scenario_id: 'tank_overflow', name: 'Tank-01 High Level / Overflow Risk' },
    { scenario_id: 'compressor_overspeed', name: 'Compressor-01 Overspeed & Vibration' },
    { scenario_id: 'pump_cavitation', name: 'Pump-02 Low Flow / Cavitation' },
    { scenario_id: 'valve_restriction_cascade', name: 'Pump-02 Valve Restriction Cascade' },
    { scenario_id: 'bearing_wear', name: 'Compressor-01 Bearing Wear Degradation' },
  ];
  const result = resolvePrimaryScenarioCatalog(oldApiResponse);
  assert.equal(result.scenarios.length, 10);
  assert.equal(result.withSop.length, 7);
  assert.equal(result.withoutEquipmentSop.length, 3);
  assert.equal(result.scenarios.find((scenario) => scenario.scenario_id === 'wet_well_high_level').sop_id, 'SOP-LFT-001');
  assert.equal(result.scenarios.find((scenario) => scenario.scenario_id === 'screen_differential_pressure').sop_id, 'SOP-INL-001');
  assert.equal(result.scenarios.some((scenario) => scenario.scenario_id === 'low_do_ammonia_rise'), false);
  assert.equal(result.scenarios.some((scenario) => scenario.scenario_id === 'seal_leak'), false);
});
