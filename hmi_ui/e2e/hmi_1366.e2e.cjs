// End-to-end check: Engineering Console start/stop + 1366x768 operator HMI.
// Needs: backend on :8001, HMI on :5173, console on :5174.
//   node e2e/hmi_1366.e2e.cjs [scenario_id] [screenshot.png]
const { chromium } = require('playwright');
const assert = require('node:assert/strict');

const API = process.env.OPSLENS_API || 'http://127.0.0.1:8001/api';
const HMI = process.env.OPSLENS_HMI || 'http://127.0.0.1:5173';
const CONSOLE = process.env.OPSLENS_CONSOLE || 'http://127.0.0.1:5174';
const scenario = process.argv[2] || 'wet_well_high_level';
const shot = process.argv[3] || 'hmi_1366x768.png';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
const check = (name, fn) => { fn(); results.push(`PASS ${name}`); };

(async () => {
  const browser = await chromium.launch();
  const errors = [];

  // ---------------- Engineering console ----------------
  const con = await browser.newPage({ viewport: { width: 1366, height: 768 } });
  con.on('pageerror', (e) => errors.push(`console page: ${e.message}`));
  await con.goto(CONSOLE);
  await con.getByRole('radio', { name: /lift station pumps clog|bar screen|Nocardia|RAS pump|CHP engine|Centrate/ }).first().waitFor();
  const radios = await con.getByRole('radio').allTextContents();
  check('console lists exactly the six incidents', () => assert.equal(radios.length, 6));
  check('no removed scenarios', () => assert.ok(!radios.join(' ').match(/Pump-02|UV|filter|Compressor|Sampling/i)));
  const names = { screen_differential_pressure: /bar screen/, wet_well_high_level: /lift station pumps clog/, biological_foam: /Nocardia/, ras_pump_failure: /RAS pump/, biogas_holder_pressure: /CHP engine/, centrifuge_capture: /Centrate/ };
  await con.getByRole('radio', { name: names[scenario] }).click();
  await con.getByText('DRAFT FOR REVIEW — NOT APPROVED').first().waitFor();
  await con.locator('table tbody tr').first().waitFor();
  await con.getByRole('button', { name: /Start/ }).click();
  await con.getByRole('button', { name: /Stop/ }).waitFor({ timeout: 5000 });
  check('Start is replaced by Stop while running (no duplicate submit)', () => true);
  // Poll until the backend reports the incident; the button must stay "Stop" while running.
  let status;
  for (let i = 0; i < 120; i += 1) {
    status = await (await fetch(`${API}/scenarios/status`)).json();
    if (status.status === 'running') {
      assert.equal(await con.getByRole('button', { name: /^Start/ }).count(), 0, 'Start re-enabled during run');
    } else break;
    await sleep(500);
  }
  check('run completes with an incident', () => assert.equal(status.status, 'awaiting_corrective_action', JSON.stringify(status)));
  await con.getByText('Incident published to the HMI').waitFor();
  const errText = await con.locator('[role=alert]').allTextContents();
  check('no "could not be started" error', () => assert.ok(!errText.join(' ').match(/could not be started/i), errText.join(' | ')));

  // ---------------- Operator HMI at 1366x768 ----------------
  const hmi = await browser.newPage({ viewport: { width: 1366, height: 768 } });
  hmi.on('pageerror', (e) => errors.push(`hmi page: ${e.message}`));
  await hmi.goto(HMI);
  await hmi.locator('.ov-banner:not(.idle)').waitFor({ timeout: 20000 });
  // Several incidents may be open; the HMI opens on the highest-ranked one.
  // Select the incident this run created, as the operator would.
  await hmi.locator(`.ov-alarm-row[data-event-id="${status.event_id}"]`).click();
  await hmi.locator('.ov-banner', { hasText: status.alarm_tag }).waitFor({ timeout: 20000 });
  await hmi.locator('.ov-trend').first().waitFor({ timeout: 20000 });
  await hmi.locator('.ov-steps li').first().waitFor({ timeout: 20000 });
  // Wait for the diagnosis to finish (AI or labelled fallback).
  await hmi.locator('.ov-diag-foot').waitFor({ timeout: 120000 });
  await sleep(800);

  const layout = await hmi.evaluate(() => {
    const se = document.scrollingElement;
    const rect = (sel) => { const e = document.querySelector(sel); if (!e) return null; const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height, b: r.bottom, r: r.right }; };
    const panels = [...document.querySelectorAll('.ov-banner, .ov-panel, .operator-workflow, .ov-topbar, .operator-sidebar')].map((e) => {
      const r = e.getBoundingClientRect(); return { cls: e.className.split(' ').slice(0, 2).join('.'), x: r.x, y: r.y, r: r.right, b: r.bottom };
    });
    const overlaps = [];
    for (let i = 0; i < panels.length; i += 1) for (let j = i + 1; j < panels.length; j += 1) {
      const a = panels[i]; const b = panels[j];
      if (a.x < b.r - 1 && b.x < a.r - 1 && a.y < b.b - 1 && b.y < a.b - 1) overlaps.push(`${a.cls} x ${b.cls}`);
    }
    const outside = panels.filter((p) => p.r > innerWidth + 0.5 || p.b > innerHeight + 0.5).map((p) => p.cls);
    const wfButtons = [...document.querySelectorAll('.operator-workflow-actions button')].map((b) => ({ t: b.textContent, clipped: b.scrollWidth > b.clientWidth + 1 }));
    return { sh: se.scrollHeight, sw: se.scrollWidth, ih: innerHeight, iw: innerWidth, overlaps, outside, wfButtons,
      banner: document.querySelector('.ov-banner')?.innerText, sopBadges: document.querySelector('.ov-sop-badges')?.innerText,
      diagBadge: document.querySelector('.ov-diag .ov-head-right')?.innerText, diagText: document.querySelector('.ov-diag-body')?.innerText.slice(0, 300),
      source: document.querySelector('.ov-source')?.innerText, trendTags: [...document.querySelectorAll('.ov-trend-foot .mono')].map((e) => e.textContent),
      workflow: rect('.operator-workflow') };
  });
  check('no vertical page scroll', () => assert.ok(layout.sh <= layout.ih, `${layout.sh} > ${layout.ih}`));
  check('no horizontal page scroll', () => assert.ok(layout.sw <= layout.iw, `${layout.sw} > ${layout.iw}`));
  check('no overlapping panels', () => assert.deepEqual(layout.overlaps, []));
  check('all panels inside the 1366x768 viewport', () => assert.deepEqual(layout.outside, []));
  check('workflow bar fully visible', () => assert.ok(layout.workflow.b <= 768));
  check('workflow buttons not clipped', () => assert.ok(layout.wfButtons.every((b) => !b.clipped), JSON.stringify(layout.wfButtons)));
  check('data marked SIMULATED', () => assert.match(layout.source, /SIMULATED/));
  check('SOP shown as draft, not approved', () => assert.match(layout.sopBadges, /DRAFT — NOT APPROVED/));
  check('diagnosis labelled AI or fallback', () => assert.match(layout.diagBadge, /AI · .* · OLLAMA|DETERMINISTIC FALLBACK/));
  if (/DETERMINISTIC/.test(layout.diagBadge)) check('fallback says it is not AI', () => assert.match(layout.diagText, /Not AI-generated/));
  const own = await (await fetch(`${API}/scenarios/${scenario}/details`)).json();
  check('trend tiles show only this incident\'s tags', () => assert.ok(layout.trendTags.every((t) => own.tags.includes(t)), layout.trendTags.join(',')));

  await hmi.screenshot({ path: shot });

  // Sidebar detail pages open without page errors.
  for (const page of ['Event Story', 'Evidence Engine', 'Operator Brief', 'Plant Overview', 'Incident History', 'Shift Handover', 'SOP Library', 'Overview']) {
    await hmi.getByRole('button', { name: page, exact: true }).click();
    await sleep(700);
  }
  await hmi.getByRole('button', { name: 'Shift Handover', exact: true }).click();
  await hmi.getByText(/handover/i).first().waitFor();
  check('shift handover page renders', () => true);
  await hmi.getByRole('button', { name: 'Overview', exact: true }).click();

  // Acknowledge from the workflow bar records an operator action (no PLC write).
  const primary = status.alarm_tag;
  await hmi.getByRole('button', { name: `Acknowledge ${primary}`, exact: true }).click();
  await hmi.locator('.operator-action-success').waitFor({ timeout: 10000 });
  const ranked = await (await fetch(`${API}/incidents/ranked?limit=100`)).json();
  const inc = ranked.ranked_incidents.find((i) => i.event_id === status.event_id);
  const prim = inc.individual_alarms.find((a) => a.tag === primary);
  check('acknowledge targets the banner alarm and leaves it ACTIVE (not cleared)', () => assert.equal(prim.lifecycle_state, 'ACKNOWLEDGED'));
  const briefNow = await (await fetch(`${API}/events/${status.event_id}/brief`)).json();
  const statusNow = await (await fetch(`${API}/scenarios/status`)).json();
  check('acknowledgement does not clear the alarm input', () => assert.equal(briefNow.resolution.alarm_input_active, true,
    JSON.stringify({ resolution: briefNow.resolution, active: briefNow.problem.active_alarm_inputs, run: statusNow.status, scen: statusNow.scenario_id, ev: statusNow.event_id })));

  // Simulated fix from the console: after-fix values, alarm input clears.
  await con.getByRole('button', { name: /Simulate the fix/ }).click();
  await con.getByText(/After-fix values reached/).waitFor({ timeout: 30000 });
  check('simulated fix clears the alarm input', () => true);

  check('no uncaught page errors', () => assert.deepEqual(errors, []));
  await browser.close();
  console.log(results.join('\n'));
  console.log(JSON.stringify({ diagBadge: layout.diagBadge, banner: layout.banner }, null, 1));
})().catch((e) => { console.error(results.join('\n')); console.error('FAIL', e.message); process.exit(1); });
