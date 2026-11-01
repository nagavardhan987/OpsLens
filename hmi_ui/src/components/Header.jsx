import React from 'react';
import { AlertTriangle } from 'lucide-react';

export default function Header({ selectedEventId = null }) {
  return (
    <header className="hmi-header">
      <div className="hmi-header-main alarm-command-header">
        <div className="alarm-command-title">
          <span className="alarm-command-mark"><AlertTriangle size={17} /></span>
          <span><strong>OpsLens</strong></span>
        </div>
        <div className="alarm-header-context" aria-live="polite">{selectedEventId || 'Plant operations'}</div>
      </div>
    </header>
  );
}
