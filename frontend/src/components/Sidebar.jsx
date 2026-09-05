import React from 'react';
import { Layers } from 'lucide-react';

export default function Sidebar({ user, tab, setTab, navItems }) {
  const visibleNav = navItems.filter(n => !n.needsRole || n.needsRole.includes(user?.role));

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="brand-mark"><Layers size={20} /></div>
        <div className="brand-title">MineIQ</div>
      </div>
      <nav className="sidebar-nav">
        {visibleNav.map(n => {
          const Icon = n.icon;
          const isActive = tab === n.id || (n.id === 'documents' && tab === 'document');
          return (
            <button key={n.id} className={`nav-item ${isActive ? 'active' : ''}`} onClick={() => setTab(n.id)}>
              <Icon size={18} /> <span>{n.label}</span>
            </button>
          );
        })}
      </nav>
    </aside>
  );
}
