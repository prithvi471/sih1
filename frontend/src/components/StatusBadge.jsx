import React from 'react';

export default function StatusBadge({ status }) {
  const map = {
    classified: 'badge-green', validated: 'badge-green', flagged: 'badge-amber',
    failed: 'badge-red', uploaded: 'badge-accent',
  };
  return <span className={`badge ${map[status] || ''}`}>{status}</span>;
}
