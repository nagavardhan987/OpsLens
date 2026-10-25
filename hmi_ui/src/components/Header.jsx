import React from 'react';
import { Activity } from 'lucide-react';

export default function Header() {
  return (
    <header className="hmi-header">
      <div className="hmi-header-main flex items-center justify-center">
        <a href="#overview" className="hmi-brand flex items-center gap-2.5 text-center" aria-label="OpsLens operator overview">
          <span className="hmi-brand-mark"><Activity size={18} /></span>
          <span className="text-left">
            <strong>OpsLens</strong>
            <small>Industrial HMI Copilot · EcoStruxure</small>
          </span>
        </a>
      </div>
    </header>
  );
}
