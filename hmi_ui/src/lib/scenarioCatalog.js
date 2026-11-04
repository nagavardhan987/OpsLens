// The six Scenario Lab incidents from the plant incident map. The backend
// (/api/scenarios) is authoritative for telemetry; this allowlist keeps an
// older API from bringing back removed scenarios (Pump-02, filters, UV ...).
export const PRIMARY_SCENARIO_CATALOG = [
  { scenario_id: 'screen_differential_pressure', number: 1, name: 'Rags jam the bar screen', equipment_id: 'InletWorks-01', primary_alarm: 'ALM-SCR-110-DL', sop_id: 'SOP-INL-001', sop_title: 'Bar Screen Blockage Response', sop_coverage: 'full' },
  { scenario_id: 'wet_well_high_level', number: 2, name: 'The lift station pumps clog', equipment_id: 'LiftStation-01', primary_alarm: 'ALM-WW-101-HH', sop_id: 'SOP-LFT-001', sop_title: 'Lift Station High-High Level and Pump Clog Response', sop_coverage: 'full' },
  { scenario_id: 'biological_foam', number: 3, name: 'Nocardia foam on the aeration tank', equipment_id: 'AerationBasin-01', primary_alarm: 'ALM-AER-201-FOAM', sop_id: 'SOP-BIO-001', sop_title: 'Activated Sludge Foam Control', sop_coverage: 'full' },
  { scenario_id: 'ras_pump_failure', number: 4, name: 'RAS pump fails, sludge blanket rises', equipment_id: 'RASSystem-01', primary_alarm: 'ALM-SLB-201-HIGH', sop_id: 'SOP-BIO-002', sop_title: 'RAS Pump Failure and Sludge Blanket Control', sop_coverage: 'full' },
  { scenario_id: 'biogas_holder_pressure', number: 5, name: 'CHP engine trips, gas holder fills', equipment_id: 'BiogasSystem-01', primary_alarm: 'ALM-GAS-601-HIGH', sop_id: 'SOP-GAS-001', sop_title: 'Biogas Holder High Pressure, CHP Trip and Flare', sop_coverage: 'full' },
  { scenario_id: 'centrifuge_capture', number: 6, name: 'Centrate poisons the plant inlet', equipment_id: 'DewateringCentrifuge-01', primary_alarm: 'ALM-SLD-701-CAPTURE', sop_id: 'SOP-SLD-001', sop_title: 'Dewatering Centrifuge and Centrate Recycle', sop_coverage: 'partial' },
].map((entry) => ({ ...entry, sop_approval_status: 'Draft for review — NOT APPROVED (SOP-MAN-000 Rev 0)', source_status: 'SIMULATED' }));

export function resolvePrimaryScenarioCatalog(apiScenarios = []) {
  const byId = new Map((Array.isArray(apiScenarios) ? apiScenarios : [])
    .filter((scenario) => scenario?.scenario_id)
    .map((scenario) => [scenario.scenario_id, scenario]));
  // Catalog identity (name, SOP, approval) always wins over the API copy.
  const scenarios = PRIMARY_SCENARIO_CATALOG.map((entry) => ({ ...(byId.get(entry.scenario_id) || {}), ...entry }));
  return { scenarios };
}
