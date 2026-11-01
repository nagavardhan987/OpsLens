import test from 'node:test';
import assert from 'node:assert/strict';
import { getEquipmentProcessTags, resolveEventEquipment } from './equipmentPresentation.js';

test('wastewater incident resolves equipment and shows its associated process tags', () => {
  const event = {
    candidate: { primary_tag: 'ALM-WW-101-HH', clustered_tags: ['LIT-101-WWL'] },
    correlated: { equipment_id: 'LiftStation-01' },
    story: { steps: [{ tag: 'LIT-101-WWL', unit: '%' }] },
  };
  assert.equal(resolveEventEquipment(event), 'LiftStation-01');
  assert.deepEqual(getEquipmentProcessTags(event, 'LiftStation-01').map(({ tag }) => tag), [
    'LIT-101-WWL', 'FIT-101-DIS', 'PIT-101-DIS', 'MOT-101-CUR',
  ]);
});

test('inlet works and aeration alarms map to the correct wastewater equipment', () => {
  assert.equal(resolveEventEquipment({ candidate: { primary_tag: 'ALM-SCR-110-DP' } }), 'InletWorks-01');
  assert.equal(resolveEventEquipment({ candidate: { primary_tag: 'ALM-AER-201-DO' } }), 'AerationBasin-01');
});
