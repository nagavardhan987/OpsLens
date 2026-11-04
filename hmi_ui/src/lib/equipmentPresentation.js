import { PLANT_EQUIPMENT_TAGS, TAG_EQUIPMENT } from './plantTags.generated.js';

// Legacy demo equipment is kept only so old incident records still render.
const LEGACY_TAGS = {
  'Pump-02': [
    { tag: 'FIT-02-FLW', label: 'Flow rate', unit: 'L/min' },
    { tag: 'PIT-02-PRS', label: 'Discharge pressure', unit: 'bar' },
    { tag: 'MOT-02-CUR', label: 'Motor current', unit: 'A' },
    { tag: 'VLV-04-POS', label: 'Valve position', unit: '%' },
  ],
  'Compressor-01': [
    { tag: 'CMP-01-SPD', label: 'Compressor speed', unit: 'RPM' },
    { tag: 'CMP-01-VIB', label: 'Bearing vibration', unit: 'mm/s' },
    { tag: 'CMP-01-CUR', label: 'Stator current', unit: 'A' },
    { tag: 'CMP-01-TMP', label: 'Bearing temperature', unit: '°C' },
  ],
  'Tank-01': [{ tag: 'TNK-01-LVL', label: 'Tank level', unit: '%' }],
};
const LEGACY_PREFIX = { 'Pump-02': ['VLV-04-', 'FIT-02-', 'MOT-02-', 'PIT-02-', 'ALM-P02-'], 'Compressor-01': ['CMP-01-', 'ALM-C01-'], 'Tank-01': ['TNK-01-', 'ALM-T01-'] };

export const EQUIPMENT_TAGS = { ...PLANT_EQUIPMENT_TAGS, ...LEGACY_TAGS };

// Exact tag -> equipment lookup. No prefix guessing for plant tags, so a
// LiftStation-01 tag can never be attributed to Pump-02 or vice versa.
export function equipmentForTag(tag) {
  if (!tag) return null;
  if (TAG_EQUIPMENT[tag]) return TAG_EQUIPMENT[tag];
  return Object.entries(LEGACY_PREFIX).find(([, prefixes]) => prefixes.some((p) => tag.startsWith(p)))?.[0] || null;
}

export function resolveEventEquipment(event) {
  const explicit = event?.correlated?.equipment_id || event?.equipment_id || event?.candidate?.equipment_id;
  if (explicit) return explicit;
  const tags = [
    event?.candidate?.primary_tag, event?.primary_tag,
    ...(event?.candidate?.clustered_tags || []),
    ...(event?.story?.steps || []).map((step) => step?.tag),
  ].filter(Boolean);
  for (const tag of tags) {
    const equipment = equipmentForTag(tag);
    if (equipment) return equipment;
  }
  return 'Unknown equipment';
}

export function getEquipmentProcessTags(event, equipmentId) {
  const knownTags = EQUIPMENT_TAGS[equipmentId] || [];
  const scoreTags = Object.keys(event?.evidence_audit?.scoring_breakdown?.tag_scores || {});
  const recordedTags = [...(event?.story?.steps || []).map((step) => step?.tag), ...scoreTags]
    .filter((tag) => tag && !tag.startsWith('ALM-') && equipmentForTag(tag) === equipmentId);
  const byTag = new Map(knownTags.map((item) => [item.tag, item]));
  for (const tag of recordedTags) {
    if (byTag.has(tag)) continue;
    const step = [...(event?.story?.steps || [])].reverse().find((item) => item.tag === tag);
    byTag.set(tag, { tag, label: tag, unit: step?.unit || '' });
  }
  return [...byTag.values()];
}
