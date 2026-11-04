import test from 'node:test';
import assert from 'node:assert/strict';
import { equipmentForTag, getEquipmentProcessTags, resolveEventEquipment } from './equipmentPresentation.js';

test('lift station incident shows only LiftStation-01 tags from the incident map', () => {
  const event = { candidate: { primary_tag: 'ALM-WW-101-HH', clustered_tags: ['LIT-101-WWL'] }, story: { steps: [{ tag: 'LIT-101-WWL', unit: 'm' }] } };
  assert.equal(resolveEventEquipment(event), 'LiftStation-01');
  const tags = getEquipmentProcessTags(event, 'LiftStation-01').map(({ tag }) => tag);
  assert.ok(tags.includes('LIT-101-WWL') && tags.includes('FIT-102-FLW') && tags.includes('TIT-101-WDG'));
  assert.ok(!tags.some((t) => /-02-|VLV-04/.test(t)), 'no Pump-02 tags');
});

test('exact tag ownership, including shared downstream tags', () => {
  assert.equal(equipmentForTag('ALM-SCR-110-DL'), 'InletWorks-01');
  assert.equal(equipmentForTag('LDT-110-SCR'), 'InletWorks-01');
  assert.equal(equipmentForTag('INL-110-NH4'), 'InletWorks-01');
  assert.equal(equipmentForTag('AER-201-AIRFLOW'), 'AerationBasin-01');
  assert.equal(equipmentForTag('EFF-301-TSS'), 'Effluent-01');
  assert.equal(equipmentForTag('PIT-102-DIS'), 'LiftStation-01');
  assert.equal(equipmentForTag('PIT-02-PRS'), 'Pump-02');
  assert.equal(equipmentForTag('DPT-110-SCR'), null, 'removed tag is unknown');
});
