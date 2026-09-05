import React from 'react';

export default function KpiCard({ label, value, sub, colorClass = '' }) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value ${colorClass}`}>{value ?? '—'}</div>
      <div className="kpi-sub">{sub}</div>
    </div>
  );
}
