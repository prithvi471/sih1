import React from 'react';
import { LogOut } from 'lucide-react';

export default function Topbar({ user, logout }) {
  return (
    <header className="topbar">
      <div className="row">
        <span className="body-sm faint">CIL / CMPDI Document Intelligence</span>
      </div>
      <div className="row" style={{ gap: 12 }}>
        <div style={{ textAlign: 'right' }}>
          <div className="label-ui" style={{ color: 'var(--text)' }}>{user?.name}</div>
          <div className="label-ui faint">{user?.role}{user?.sub ? ` · ${user.sub}` : ''}</div>
        </div>
        <span className="badge badge-accent">{user?.role}{user?.sub ? ` · ${user.sub}` : ''}</span>
        <button className="btn btn-ghost btn-sm" onClick={logout}><LogOut size={16} /> Sign out</button>
      </div>
    </header>
  );
}
