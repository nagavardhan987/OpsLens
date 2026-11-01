const EQUIPMENT_TAGS = {
  'LiftStation-01': [
    { tag: 'LIT-101-WWL', label: 'Wet-well level', unit: '%' },
    { tag: 'FIT-101-DIS', label: 'Lift discharge flow', unit: 'm³/h' },
    { tag: 'PIT-101-DIS', label: 'Discharge pressure', unit: 'bar' },
    { tag: 'MOT-101-CUR', label: 'Pump motor current', unit: 'A' },
  ],
  'InletWorks-01': [
    { tag: 'FIT-110-IN', label: 'Influent flow', unit: 'm³/h' },
    { tag: 'DPT-110-SCR', label: 'Screen differential pressure', unit: 'kPa' },
  ],
  'AerationBasin-01': [
    { tag: 'AIT-201-DO', label: 'Dissolved oxygen', unit: 'mg/L' },
    { tag: 'AIT-201-NH4', label: 'Ammonia', unit: 'mg/L' },
  ],
  'TertiaryTreatment-01': [
    { tag: 'FLT-401-BW-HOURS', label: 'Hours since backwash', unit: 'h' },
    { tag: 'FLT-401-HL', label: 'Filter head loss', unit: 'm' },
    { tag: 'FLT-401-TURB', label: 'Filter outlet turbidity', unit: 'NTU' },
    { tag: 'UV-501-UVT', label: 'UV transmittance', unit: '%' },
    { tag: 'UV-501-LAMPS-ON', label: 'UV lamps in service', unit: 'of 24' },
    { tag: 'UV-501-INTENSITY', label: 'UV intensity', unit: 'mW/cm²' },
    { tag: 'UV-501-DOSE', label: 'UV dose', unit: 'mJ/cm²' },
  ],
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
  'Tank-01': [
    { tag: 'TNK-01-LVL', label: 'Tank level', unit: '%' },
  ],
};

const TAG_EQUIPMENT = {
  'LiftStation-01': ['LIT-101-', 'FIT-101-', 'PIT-101-', 'MOT-101-', 'ALM-WW-101-'],
  'InletWorks-01': ['FIT-110-', 'DPT-110-', 'ALM-SCR-110-'],
  'AerationBasin-01': ['AIT-201-', 'ALM-AER-201-'],
  'TertiaryTreatment-01': ['FLT-401-', 'UV-501-', 'ALM-UV-501-', 'BWP-1-', 'BWP-2-', 'RLV-501-', 'CHL-501-', 'LAB-501-'],
  'Pump-02': ['VLV-04-', 'FIT-02-', 'MOT-02-', 'PIT-02-', 'ALM-P02-'],
  'Compressor-01': ['CMP-01-', 'ALM-C01-'],
  'Tank-01': ['TNK-01-', 'ALM-T01-'],
};

function equipmentForTag(tag) {
  if (!tag) return null;
  return Object.entries(TAG_EQUIPMENT).find(([, prefixes]) => prefixes.some((prefix) => tag.startsWith(prefix)))?.[0] || null;
}

export function resolveEventEquipment(event) {
  const explicit = event?.correlated?.equipment_id || event?.equipment_id || event?.candidate?.equipment_id;
  if (explicit) return explicit;

  const tags = [
    event?.candidate?.primary_tag,
    event?.primary_tag,
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
  const recordedTags = [
    ...(event?.story?.steps || []).map((step) => step?.tag),
    ...scoreTags,
  ].filter((tag) => tag && !tag.startsWith('ALM-') && equipmentForTag(tag) === equipmentId);

  const byTag = new Map(knownTags.map((item) => [item.tag, item]));
  for (const tag of recordedTags) {
    if (byTag.has(tag)) continue;
    const observation = event?.evidence_audit?.scoring_breakdown?.tag_scores?.[tag]?.observed_reading;
    const step = [...(event?.story?.steps || [])].reverse().find((item) => item.tag === tag);
    byTag.set(tag, { tag, label: tag, unit: observation?.unit || step?.unit || '' });
  }
  return [...byTag.values()];
}
