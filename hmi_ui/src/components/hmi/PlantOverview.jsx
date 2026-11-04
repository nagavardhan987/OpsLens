import React, { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { getPlantOverview } from '../../api/client';

const NAMES = {
  'InletWorks-01': 'Inlet works', 'LiftStation-01': 'Lift station', 'AerationBasin-01': 'Aeration tanks',
  'SecondaryClarifier-01': 'Secondary clarifiers', 'RASSystem-01': 'RAS pumps', 'BiogasSystem-01': 'Biogas & CHP',
  'DewateringCentrifuge-01': 'Dewatering centrifuge', 'Effluent-01': 'Final effluent',
};

function fmt(v) {
  if (typeof v === 'boolean') return v ? 'ON' : 'OFF';
  if (typeof v !== 'number') return '—';
  return Math.abs(v) >= 100 ? Math.round(v).toLocaleString() : String(Math.round(v * 100) / 100);
}

/** Monitoring view of the whole plant. Not an incident scenario. */
export default function PlantOverview() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    const load = () => getPlantOverview().then((d) => { if (live) { setData(d); setError(''); } }).catch((e) => live && setError(e.message));
    load();
    const t = window.setInterval(load, 3000);
    return () => { live = false; window.clearInterval(t); };
  }, []);
  return (
    <section className="ov-page">
      <div className="ov-page-title"><h1>Plant overview</h1><span>Monitoring view · latest recorded values · not an incident</span></div>
      {error && <p role="alert" className="ov-error">Plant values unavailable: {error}</p>}
      {!data && !error && <p className="ov-empty"><Loader2 size={13} className="spin" /> Loading…</p>}
      <div className="ov-plant-grid">
        {data?.equipment.map((eq) => {
          const alarms = eq.signals.filter((s) => s.beyond_limit).length;
          return (
            <div key={eq.equipment_id} className={`ov-panel ov-plant-card ${alarms ? 'alarm' : ''}`}>
              <header className="ov-panel-head"><h2>{NAMES[eq.equipment_id] || eq.equipment_id}</h2>{alarms ? <span className="ov-chip red">{alarms} LIMIT</span> : <span className="ov-chip green">NORMAL</span>}</header>
              <table className="ov-table"><tbody>
                {eq.signals.map((s) => (
                  <tr key={s.tag} className={s.beyond_limit ? 'hit' : ''}>
                    <td>{s.label}<div className="mono muted" style={{ fontSize: 9.5 }}>{s.tag}</div></td>
                    <td className="r mono"><b>{fmt(s.value)}</b> {s.unit}{s.stale && s.value != null && <div className="muted" style={{ fontSize: 9 }}>stale</div>}</td>
                    <td className="muted">{s.normal_text}</td>
                  </tr>
                ))}
              </tbody></table>
            </div>
          );
        })}
      </div>
    </section>
  );
}
