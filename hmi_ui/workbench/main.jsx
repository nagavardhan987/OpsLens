import React from 'react';
import { createRoot } from 'react-dom/client';
import WorkbenchApp from '../src/WorkbenchApp.jsx';
import '../src/index.css';

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <WorkbenchApp />
  </React.StrictMode>,
);
