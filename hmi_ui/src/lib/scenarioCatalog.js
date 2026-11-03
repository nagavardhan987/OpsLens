export const PRIMARY_SCENARIO_CATALOG = [
  { scenario_id: 'wet_well_high_level', name: 'Lift Station — Wet-Well High-High Level', demo_group: 'WITH MATCHING SOP', sop_id: 'SOP-LFT-001', sop_title: 'Lift Station High-High Level and Pump Clog Response', sop_approval_status: 'Draft for review — not approved' },
  { scenario_id: 'screen_differential_pressure', name: 'Inlet Works — Screen Differential Pressure High', demo_group: 'WITH MATCHING SOP', sop_id: 'SOP-INL-001', sop_title: 'Bar Screen Operation and Blockage Response', sop_approval_status: 'Draft for review — not approved' },
  { scenario_id: 'biological_foam', name: 'Aeration Tank — Biological Foam', demo_group: 'WITH MATCHING SOP', sop_id: 'SOP-BIO-001', sop_title: 'Activated Sludge Foam Control', sop_approval_status: 'Draft for review — not approved' },
  { scenario_id: 'ras_pump_failure', name: 'RAS Pump Failure — Sludge Blanket High', demo_group: 'WITH MATCHING SOP', sop_id: 'SOP-BIO-002', sop_title: 'RAS Pump Failure and Sludge Blanket Control', sop_approval_status: 'Draft for review — not approved' },
  { scenario_id: 'biogas_holder_pressure', name: 'Biogas System — High Holder Pressure / CHP Trip', demo_group: 'WITH MATCHING SOP', sop_id: 'SOP-GAS-001', sop_title: 'Biogas Holder High Pressure, CHP Trip and Flare Operation', sop_approval_status: 'Draft for review — not approved' },
  { scenario_id: 'centrifuge_capture', name: 'Dewatering Centrifuge — Low Solids Capture / High Centrate Ammonia', demo_group: 'WITH MATCHING SOP', sop_id: 'SOP-SLD-001', sop_title: 'Dewatering Centrifuge Operation and Centrate Recycle Control', sop_approval_status: 'Draft for review — not approved' },
  { scenario_id: 'monitoring_due', name: 'Process Monitoring — Sampling / Calibration Due', demo_group: 'WITH MATCHING SOP', sop_id: 'SOP-LAB-001', sop_title: 'Process Sampling and Monitoring Schedule', sop_approval_status: 'Draft for review — not approved' },
  { scenario_id: 'valve_restriction', name: 'Pump-02 — Valve Restriction', demo_group: 'WITHOUT SPECIFIC EQUIPMENT-FAILURE SOP' },
  { scenario_id: 'bearing_wear', name: 'Compressor-01 — Bearing Wear', demo_group: 'WITHOUT SPECIFIC EQUIPMENT-FAILURE SOP' },
  { scenario_id: 'filter_sensor_fault', name: 'Filter-01 — Sensor Fault', demo_group: 'WITHOUT SPECIFIC EQUIPMENT-FAILURE SOP' },
];

const SOP_GROUP = 'WITH MATCHING SOP';
const NO_EQUIPMENT_SOP_GROUP = 'WITHOUT SPECIFIC EQUIPMENT-FAILURE SOP';

// The backend is authoritative for incident telemetry and scenario execution.
// This allowlist keeps a stale/legacy API response from restoring obsolete
// scenarios or mislabeling newer scenarios while the service is being updated.
export function resolvePrimaryScenarioCatalog(apiScenarios = []) {
  const byId = new Map((Array.isArray(apiScenarios) ? apiScenarios : [])
    .filter((scenario) => scenario?.scenario_id)
    .map((scenario) => [scenario.scenario_id, scenario]));
  const scenarios = PRIMARY_SCENARIO_CATALOG.map((catalogEntry) => ({
    ...(byId.get(catalogEntry.scenario_id) || {}),
    ...catalogEntry,
  }));
  return {
    scenarios,
    withSop: scenarios.filter((scenario) => scenario.demo_group === SOP_GROUP),
    withoutEquipmentSop: scenarios.filter((scenario) => scenario.demo_group === NO_EQUIPMENT_SOP_GROUP),
  };
}
