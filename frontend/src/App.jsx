import React, { useState, useEffect } from 'react';

const API_BASE    = 'http://localhost:8000';
const RAG_API     = 'http://localhost:8005';
const ANALYTICS_API = 'http://localhost:8006';
const PQ_API      = 'http://localhost:8007';

const DEMO_USERS = [
  { username: 'admin',           role: 'ADMIN',             name: 'System Admin',            sub: null,   pw: 'admin123'    },
  { username: 'ministry_officer',role: 'MINISTRY_OFFICER',  name: 'Ministry of Coal Officer', sub: null,   pw: 'ministry123' },
  { username: 'cmpdi_officer',   role: 'CMPDI_OFFICER',     name: 'CMPDI Nodal Officer',      sub: 'CMPDI',pw: 'cmpdi123'   },
  { username: 'mcl_officer',     role: 'SUBSIDIARY_OFFICER',name: 'MCL Officer (MCL only)',   sub: 'MCL',  pw: 'mcl123'     },
  { username: 'ecl_officer',     role: 'SUBSIDIARY_OFFICER',name: 'ECL Officer (ECL only)',   sub: 'ECL',  pw: 'ecl123'     },
  { username: 'auditor_user',    role: 'AUDITOR',           name: 'Compliance Auditor',       sub: null,   pw: 'audit123'   },
];

const CAN_READ_USERS  = ['ADMIN', 'AUDITOR', 'MINISTRY_OFFICER'];
const CAN_WRITE_USERS = ['ADMIN'];
const CAN_WRITE_PQ    = ['ADMIN', 'MINISTRY_OFFICER', 'CMPDI_OFFICER'];
const CAN_APPROVE_PQ  = ['ADMIN', 'MINISTRY_OFFICER'];

const NAV = [
  { id: 'overview',      label: 'Overview',       icon: 'dashboard' },
  { id: 'documents',     label: 'Documents',      icon: 'folder_open' },
  { id: 'parliament',    label: 'PQ Copilot',     icon: 'account_balance' },
  { id: 'ask',           label: 'Ask AI',         icon: 'auto_awesome' },
  { id: 'analytics',     label: 'Analytics',      icon: 'bar_chart' },
  { id: 'discrepancies', label: 'Discrepancies',  icon: 'warning' },
  { id: 'users',         label: 'Users',          icon: 'manage_accounts', needsRole: CAN_READ_USERS },
  { id: 'audit',         label: 'Audit',          icon: 'security' },
];

const ALL_ROLES = ['ADMIN','MINISTRY_OFFICER','CMPDI_OFFICER','SUBSIDIARY_OFFICER','ANALYST','AUDITOR','VIEWER'];

const pct = (v) => (v === null || v === undefined ? null : `${v}%`);

// ─── Material Symbol icon helper ─────────────────────────────────────────────
function Icon({ name, className = '' }) {
  return <span className={`material-symbols-outlined ${className}`}>{name}</span>;
}

// ─── Minimal markdown renderer ────────────────────────────────────────────────
function Markdown({ text }) {
  if (!text) return <span className="text-outline">No content.</span>;
  const lines = text.split('\n');
  const out = [];
  let bullets = [];
  const flush = (k) => {
    if (bullets.length) {
      out.push(<ul key={`u${k}`} className="prose">{bullets}</ul>);
      bullets = [];
    }
  };
  const inline = (s) => {
    const parts = s.split(/(\*\*.+?\*\*)/g);
    return parts.map((p, i) =>
      p.startsWith('**') && p.endsWith('**')
        ? <strong key={i}>{p.slice(2, -2)}</strong>
        : <span key={i}>{p}</span>
    );
  };
  const isTableRow = (s) => /^\s*\|.*\|\s*$/.test(s);
  const isSep = (s) => /^\s*\|[\s:|-]+\|\s*$/.test(s);
  const cells = (s) => s.trim().replace(/^\||\/$/g, '').replace(/\|$/, '').split('|').map(c => c.trim());

  let i = 0;
  while (i < lines.length) {
    const raw = lines[i];
    const line = raw.trimEnd();
    if (!line.trim()) { flush(i); i++; continue; }
    if (isTableRow(line) && i + 1 < lines.length && isSep(lines[i + 1])) {
      flush(i);
      const header = cells(line);
      const rows = [];
      i += 2;
      while (i < lines.length && isTableRow(lines[i]) && !isSep(lines[i])) { rows.push(cells(lines[i])); i++; }
      out.push(
        <div key={`t${i}`} className="overflow-x-auto my-3">
          <table className="w-full text-body-sm font-body-sm border-collapse">
            <thead>
              <tr className="border-b border-outline-variant">
                {header.map((c, k) => <th key={k} className="text-left py-2 px-3 text-label-mono-sm font-label-mono-sm uppercase text-on-surface-variant">{inline(c)}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, ri) => (
                <tr key={ri} className="border-b border-outline-variant/40 hover:bg-surface-container-low">
                  {r.map((c, ci) => <td key={ci} className="py-2 px-3 text-on-surface">{inline(c)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    const b = line.match(/^\s*[-*]\s+(.*)$/);
    if (h) {
      flush(i);
      const lvl = h[1].length;
      const cls = lvl <= 1 ? 'text-headline-sm font-headline-sm' : lvl === 2 ? 'text-body-lg font-semibold' : 'text-body-md font-semibold';
      out.push(<div key={i} className={`${cls} text-on-surface mt-4 mb-2`}>{inline(h[2])}</div>);
    } else if (b) {
      bullets.push(<li key={i} className="text-body-sm text-on-surface mb-1">{inline(b[1])}</li>);
    } else {
      flush(i);
      out.push(<p key={i} className="prose text-body-sm text-on-surface">{inline(line)}</p>);
    }
    i++;
  }
  flush('end');
  return <div className="space-y-1">{out}</div>;
}

// ─── Status badge ─────────────────────────────────────────────────────────────
function StatusBadge({ status }) {
  const map = {
    classified: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    validated:  'bg-emerald-50 text-emerald-700 border-emerald-200',
    flagged:    'bg-amber-50 text-amber-700 border-amber-200',
    failed:     'bg-red-50 text-red-700 border-red-200',
    uploaded:   'bg-primary-fixed text-on-primary-fixed border-primary-fixed-dim',
  };
  return (
    <span className={`inline-flex items-center px-space-xs py-space-2xs rounded-full border text-label-mono-sm font-label-mono-sm uppercase tracking-wide ${map[status] || 'bg-surface-container text-on-surface-variant border-outline-variant'}`}>
      {status}
    </span>
  );
}

// ─── Table component ──────────────────────────────────────────────────────────
function DataTable({ columns, rows, emptyMsg = 'No data yet.' }) {
  return (
    <div className="w-full overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-outline-variant">
            {columns.map((col, i) => (
              <th key={i} className={`py-3 px-4 text-left text-label-mono-sm font-label-mono-sm uppercase tracking-wider text-on-surface-variant ${col.right ? 'text-right' : ''}`}>
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="py-10 text-center text-body-sm text-outline">
                {emptyMsg}
              </td>
            </tr>
          ) : rows}
        </tbody>
      </table>
    </div>
  );
}

// ─── KPI card ─────────────────────────────────────────────────────────────────
function KpiCard({ label, value, sub, trend, accent }) {
  return (
    <div className="bg-surface-container-lowest p-space-lg rounded-xl shadow-sm flex flex-col gap-space-xs hover:shadow-md transition-shadow">
      <div className="flex items-center justify-between">
        <span className="text-label-mono-sm font-label-mono-sm uppercase tracking-wider text-on-surface-variant">{label}</span>
        {trend && <span className="px-space-xs py-space-2xs bg-surface-container rounded text-primary text-label-mono-sm font-label-mono-sm">{trend}</span>}
      </div>
      <div className={`text-display-hero font-display-hero text-on-surface tracking-tight font-semibold ${accent || ''}`} style={{ fontSize: typeof value === 'string' && value.length > 8 ? '32px' : undefined }}>
        {value ?? '—'}
      </div>
      {sub && <span className="text-body-sm font-body-sm text-on-surface-variant">{sub}</span>}
    </div>
  );
}

// ─── Main App ─────────────────────────────────────────────────────────────────
export default function App() {
  const [tab, setTab]       = useState('overview');
  const [user, setUser]     = useState(null);
  const [token, setToken]   = useState('');
  const [authed, setAuthed] = useState(false);
  const [loginForm, setLoginForm] = useState({ username: '', password: '' });
  const [loginError, setLoginError] = useState('');
  const [loginBusy, setLoginBusy]   = useState(false);

  const [documents,     setDocuments]     = useState([]);
  const [metrics,       setMetrics]       = useState(null);
  const [auditLogs,     setAuditLogs]     = useState([]);
  const [wordcloud,     setWordcloud]     = useState([]);
  const [topics,        setTopics]        = useState([]);
  const [trends,        setTrends]        = useState([]);
  const [discrepancies, setDiscrepancies] = useState(null);
  const [users,         setUsers]         = useState([]);
  const [newUser, setNewUser] = useState({ username:'', password:'', full_name:'', role:'VIEWER', assigned_subsidiary:'' });
  const [userMsg, setUserMsg] = useState(null);
  const [pqs,         setPqs]         = useState([]);
  const [selectedPQ,  setSelectedPQ]  = useState(null);
  const [newPQ, setNewPQ] = useState({ question_text:'', pq_number:'', due_date:'' });
  const [pqBusy, setPqBusy] = useState(false);

  const [selectedDoc,    setSelectedDoc]    = useState(null);
  const [selectedReport, setSelectedReport] = useState(null);
  const [uploadFile,     setUploadFile]     = useState(null);
  const [procStep,       setProcStep]       = useState(0);
  const [procMsg,        setProcMsg]        = useState(null);

  const [subFilter,    setSubFilter]    = useState('ALL');
  const [searchQuery,  setSearchQuery]  = useState('');
  const [ragQuery,     setRagQuery]     = useState('');
  const [ragResult,    setRagResult]    = useState(null);
  const [ragLoading,   setRagLoading]   = useState(false);
  const [ragScope,     setRagScope]     = useState('CROSS_DOCUMENT');

  const authHeaders = (t) => ({ Authorization: `Bearer ${t || token}` });

  async function doLogin(username, password) {
    setLoginError(''); setLoginBusy(true);
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { setLoginError(data.detail || 'Invalid username or password'); return; }
      const u = { username: data.user.username, role: data.user.role, sub: data.user.assigned_subsidiary, name: data.user.full_name };
      setToken(data.access_token); setUser(u); setAuthed(true); setTab('overview');
      loadAll(data.access_token);
    } catch (e) {
      setLoginError('Cannot reach the server. Is the API running on :8000?');
    } finally { setLoginBusy(false); }
  }

  function logout() {
    setAuthed(false); setToken(''); setUser(null);
    setDocuments([]); setUsers([]); setSelectedDoc(null); setSelectedReport(null);
    setMetrics(null); setAuditLogs([]); setDiscrepancies(null);
    setLoginForm({ username: '', password: '' }); setLoginError('');
  }

  function loadAll(t) {
    const h = { headers: authHeaders(t) };
    fetch(`${API_BASE}/documents`, h).then(r => r.json()).then(d => Array.isArray(d) && setDocuments(d)).catch(() => {});
    fetch(`${API_BASE}/metrics`, h).then(r => r.json()).then(setMetrics).catch(() => {});
    fetch(`${API_BASE}/audit-logs`, h).then(r => r.json()).then(a => Array.isArray(a) && setAuditLogs(a)).catch(() => {});
    fetch(`${ANALYTICS_API}/analytics/wordcloud`, h).then(r => r.json()).then(w => w.words && setWordcloud(w.words)).catch(() => {});
    fetch(`${ANALYTICS_API}/analytics/topics`, h).then(r => r.json()).then(t2 => t2.topics && setTopics(t2.topics)).catch(() => {});
    fetch(`${ANALYTICS_API}/analytics/trends`, h).then(r => r.json()).then(tr => tr.trends && setTrends(tr.trends)).catch(() => {});
    fetch(`${ANALYTICS_API}/analytics/discrepancies`, h).then(r => r.json()).then(setDiscrepancies).catch(() => {});
    fetch(`${API_BASE}/auth/users`, h).then(r => r.ok ? r.json() : []).then(u => Array.isArray(u) && setUsers(u)).catch(() => setUsers([]));
    fetch(`${PQ_API}/api/parliament/questions`, h).then(r => r.ok ? r.json() : []).then(p => Array.isArray(p) && setPqs(p)).catch(() => setPqs([]));
  }

  async function createPQ() {
    setPqBusy(true);
    try {
      const body = { question_text: newPQ.question_text };
      if (newPQ.pq_number) body.pq_number = newPQ.pq_number;
      if (newPQ.due_date)  body.due_date  = newPQ.due_date;
      const res = await fetch(`${PQ_API}/api/parliament/questions`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) { alert(data.detail || 'Failed to register PQ'); return; }
      setNewPQ({ question_text:'', pq_number:'', due_date:'' });
      loadAll(); openPQ(data.id);
    } catch (e) { alert(e.message); } finally { setPqBusy(false); }
  }

  async function openPQ(id) {
    try {
      const r = await fetch(`${PQ_API}/api/parliament/questions/${id}`, { headers: authHeaders() });
      if (r.ok) setSelectedPQ(await r.json());
    } catch (e) {}
  }

  async function generatePQDraft(id) {
    setPqBusy(true);
    try {
      const r = await fetch(`${PQ_API}/api/parliament/questions/${id}/generate-draft`, { method: 'POST', headers: authHeaders() });
      if (!r.ok) { const d = await r.json(); alert(d.detail || 'Draft failed'); return; }
      await openPQ(id); loadAll();
    } catch (e) { alert(e.message); } finally { setPqBusy(false); }
  }

  async function reviewPQ(id, decision) {
    try {
      const r = await fetch(`${PQ_API}/api/parliament/questions/${id}/review`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ decision }),
      });
      if (!r.ok) { const d = await r.json(); alert(d.detail || 'Review failed'); return; }
      await openPQ(id); loadAll();
    } catch (e) { alert(e.message); }
  }

  async function createUser() {
    setUserMsg(null);
    const body = { ...newUser };
    if (!body.assigned_subsidiary) delete body.assigned_subsidiary;
    try {
      const res = await fetch(`${API_BASE}/auth/users`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) { setUserMsg(data.detail || 'Failed to create user'); return; }
      setNewUser({ username:'', password:'', full_name:'', role:'VIEWER', assigned_subsidiary:'' });
      setUserMsg(`Created ${data.username}`); loadAll();
    } catch (e) { setUserMsg(e.message); }
  }

  async function toggleUser(u) {
    await fetch(`${API_BASE}/auth/users/${u.id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ is_active: !u.is_active }),
    }).then(r => { if (!r.ok) r.json().then(d => alert(d.detail)); });
    loadAll();
  }

  async function removeUser(u) {
    if (!confirm(`Delete user ${u.username}?`)) return;
    const res = await fetch(`${API_BASE}/auth/users/${u.id}`, { method: 'DELETE', headers: authHeaders() });
    if (!res.ok) { const d = await res.json(); alert(d.detail); }
    loadAll();
  }

  async function handleUpload() {
    if (!uploadFile) return;
    setProcStep(1); setProcMsg('Uploading to object store…');
    try {
      const fd = new FormData(); fd.append('file', uploadFile);
      const up = await fetch(`${API_BASE}/upload`, { method: 'POST', headers: authHeaders(), body: fd });
      const upData = await up.json();
      setProcStep(2); setProcMsg('Running OCR, extraction, validation & classification…');
      const proc = await fetch(`${API_BASE}/process/${upData.id}`, { method: 'POST', headers: authHeaders() });
      const procData = await proc.json();
      setProcStep(5); setProcMsg('Done. Report generation runs asynchronously.');
      loadAll(); setUploadFile(null); openDoc(procData.id);
    } catch (e) { setProcMsg('Pipeline error: ' + e.message); setProcStep(0); }
  }

  async function openDoc(docId) {
    try {
      const dr = await fetch(`${API_BASE}/documents/${docId}`, { headers: authHeaders() });
      if (!dr.ok) { alert(`Access denied for role ${user.role}.`); return; }
      setSelectedDoc(await dr.json());
      const rr = await fetch(`${API_BASE}/reports/${docId}`, { headers: authHeaders() });
      setSelectedReport(rr.ok ? await rr.json() : null);
      setTab('document');
    } catch (e) { console.error(e); }
  }

  async function downloadReport(docId, fmt) {
    try {
      const res = await fetch(`${API_BASE}/reports/${docId}/export?format=${fmt}`, { headers: authHeaders() });
      if (!res.ok) { alert('Report not available for export yet.'); return; }
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href = url; a.download = `MineIQ_report.${fmt}`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch (e) { alert('Export failed: ' + e.message); }
  }

  async function runRag() {
    if (!ragQuery.trim()) return;
    setRagLoading(true); setRagResult(null);
    try {
      const payload = { query: ragQuery, top_k: 4 };
      if (selectedDoc && ragScope === 'SELECTED') { payload.document_id = selectedDoc.id; payload.mode = 'SELECTED'; }
      else payload.mode = 'CROSS_DOCUMENT';
      const res = await fetch(`${RAG_API}/query`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(payload),
      });
      setRagResult(await res.json());
    } catch (e) {
      setRagResult({ answer: 'Query error: ' + e.message, sources: [], grounded: false });
    } finally { setRagLoading(false); }
  }

  const filtered = documents.filter(d => {
    if (subFilter !== 'ALL' && d.subsidiary?.toUpperCase() !== subFilter) return false;
    if (searchQuery && !d.original_filename?.toLowerCase().includes(searchQuery.toLowerCase())) return false;
    return true;
  });

  const accuracyDisplay = metrics
    ? (metrics.extraction_accuracy_evaluated ? pct(metrics.extraction_accuracy_percentage) : 'Not evaluated')
    : '—';

  // ── Input styles ─────────────────────────────────────────────────────────
  const inputCls = "w-full h-10 px-space-base bg-surface-container-low border border-outline-variant rounded-lg text-body-md font-body-md text-on-surface placeholder:text-outline focus:outline-none focus:border-primary-container focus:shadow-[0_0_0_2px_rgba(79,70,229,0.2)] transition-all";
  const selectCls = "h-10 px-space-base bg-surface-container-low border border-outline-variant rounded-lg text-body-md font-body-md text-on-surface focus:outline-none focus:border-primary-container transition-all";
  const btnPrimaryCls = "inline-flex items-center gap-space-xs h-9 px-space-md bg-primary-container hover:bg-secondary text-on-primary text-label-ui font-label-ui rounded-lg transition-all shadow-sm active:scale-[0.99] disabled:opacity-50 disabled:pointer-events-none";
  const btnGhostCls   = "inline-flex items-center gap-space-xs h-9 px-space-sm bg-surface-container-low hover:bg-surface-container border border-outline-variant text-on-surface-variant text-label-ui font-label-ui rounded-lg transition-all disabled:opacity-50 disabled:pointer-events-none";
  const btnSmGhostCls = "inline-flex items-center gap-space-xs h-7 px-space-sm bg-transparent hover:bg-surface-container-low text-on-surface-variant text-label-ui font-label-ui rounded transition-all";

  // ── LOGIN SCREEN ──────────────────────────────────────────────────────────
  if (!authed) {
    return (
      <div className="min-h-screen w-full flex items-center justify-center p-space-lg relative overflow-hidden">
        {/* Dark atmospheric backdrop */}
        <div className="absolute inset-0 -z-10 bg-gradient-to-br from-[#0B0F19] via-[#0F172A] to-[#1E1B4B]" />
        <div className="absolute w-[680px] h-[680px] rounded-full bg-gradient-to-tr from-primary/30 to-secondary-container/20 blur-[130px] -top-32 -left-32 pointer-events-none" />
        <div className="absolute w-[560px] h-[560px] rounded-full bg-gradient-to-bl from-primary-container/25 via-secondary/15 to-transparent blur-[120px] -bottom-24 -right-24 pointer-events-none" />
        {/* Grid texture */}
        <svg className="absolute inset-0 w-full h-full opacity-[0.035] pointer-events-none" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <pattern id="grid-pattern" width="48" height="48" patternUnits="userSpaceOnUse">
              <path d="M 48 0 L 0 0 0 48" fill="none" stroke="white" strokeWidth="1" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#grid-pattern)" />
        </svg>

        {/* Login card */}
        <div className="w-full max-w-[428px] mx-auto relative">
          <div className="absolute -inset-1.5 rounded-full bg-gradient-to-b from-primary-container/40 to-transparent blur-xl opacity-60 pointer-events-none" />
          <div className="relative bg-surface-container-lowest text-on-surface rounded-xl shadow-2xl p-space-xl backdrop-blur-md">

            {/* Brand */}
            <div className="flex flex-col items-center text-center mb-space-xl">
              <div className="relative flex items-center justify-center mb-space-base">
                <div className="absolute w-16 h-16 rounded-full bg-primary-container/20 blur-md" />
                <div className="relative w-12 h-12 rounded-xl bg-primary-container flex items-center justify-center shadow-sm">
                  <Icon name="layers" className="text-on-primary text-[24px]" />
                </div>
              </div>
              <div className="inline-flex items-center gap-space-xs bg-surface-container-low px-space-sm py-space-2xs rounded-full mb-space-sm">
                <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                <span className="text-label-mono-sm font-label-mono-sm text-on-surface-variant uppercase tracking-wider">Geological Core v3.4</span>
              </div>
              <h1 className="text-headline-lg font-headline-lg text-on-surface tracking-tight">Welcome to MineIQ</h1>
              <p className="text-body-md font-body-md text-on-surface-variant mt-space-xs max-w-[320px]">
                AI-powered document intelligence for geological &amp; mining operations.
              </p>
            </div>

            {/* Auth form */}
            <form onSubmit={e => { e.preventDefault(); doLogin(loginForm.username.trim(), loginForm.password); }}
              className="flex flex-col gap-space-base">
              <div className="flex flex-col gap-space-2xs">
                <label className="text-label-ui font-label-ui text-on-surface-variant font-medium">Username</label>
                <input
                  className={inputCls} autoFocus placeholder="Username"
                  value={loginForm.username}
                  onChange={e => setLoginForm({ ...loginForm, username: e.target.value })}
                />
              </div>
              <div className="flex flex-col gap-space-2xs">
                <label className="text-label-ui font-label-ui text-on-surface-variant font-medium">Password</label>
                <input
                  className={inputCls} type="password" placeholder="••••••••"
                  value={loginForm.password}
                  onChange={e => setLoginForm({ ...loginForm, password: e.target.value })}
                />
              </div>
              {loginError && (
                <div className="flex items-center gap-space-xs px-space-sm py-space-xs bg-error-container text-on-error-container rounded-lg text-body-sm font-body-sm">
                  <Icon name="error" className="text-[16px]" /> {loginError}
                </div>
              )}
              <button
                className={`group relative w-full h-11 mt-space-xs bg-primary-container hover:bg-secondary hover:shadow-[0_4px_24px_rgba(79,70,229,0.4)] text-on-primary text-headline-sm font-headline-sm rounded-lg flex items-center justify-center gap-space-sm transition-all duration-200 active:scale-[0.99] disabled:opacity-60 disabled:pointer-events-none`}
                type="submit" disabled={loginBusy || !loginForm.username || !loginForm.password}
              >
                {loginBusy
                  ? <><Icon name="refresh" className="text-[18px] spin" /> Signing in…</>
                  : <><span>Sign in to Workspace</span><Icon name="arrow_forward" className="text-[18px] transition-transform group-hover:translate-x-0.5" /></>
                }
              </button>
            </form>

            {/* Demo roles */}
            <div className="relative my-space-lg flex items-center justify-center">
              <div className="w-full h-[1px] bg-surface-container-high" />
              <span className="absolute px-space-sm bg-surface-container-lowest text-label-mono-sm font-label-mono-sm text-outline uppercase tracking-tight">Quick demo access</span>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-space-xs">
              {DEMO_USERS.map(u => (
                <button key={u.username}
                  className="px-space-md py-space-xs bg-surface-container-low hover:bg-primary-fixed hover:text-on-primary-fixed text-label-mono-sm font-label-mono-sm rounded-full text-on-surface-variant transition-colors disabled:opacity-50"
                  disabled={loginBusy}
                  onClick={() => doLogin(u.username, u.pw)}
                >
                  {u.name.split(' ')[0]}
                </button>
              ))}
            </div>

            {/* System telemetry */}
            <div className="mt-space-lg pt-space-md flex items-center justify-between text-label-mono-sm font-label-mono-sm text-outline border-t border-outline-variant/40">
              <div className="flex items-center gap-space-2xs">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                <span>Inference Clusters Online</span>
              </div>
              <span>Latency 12ms</span>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── MAIN APP ──────────────────────────────────────────────────────────────
  const visibleNav = NAV.filter(n => !n.needsRole || n.needsRole.includes(user.role));

  return (
    <div className="min-h-screen bg-surface font-body-md text-body-md text-on-surface antialiased">
      {/* ── Top Navigation Header ─────────────────────────────────────────── */}
      <header className="fixed top-0 w-full z-50 bg-surface-container-lowest/90 backdrop-blur-xl shadow-[0_1px_8px_rgba(0,0,0,0.04)]">
        <div className="h-16 w-full px-margin-desktop flex items-center justify-between gap-space-md">
          {/* Left: Brand + Nav */}
          <div className="flex items-center gap-space-lg">
            <div className="flex items-center gap-space-sm cursor-pointer flex-shrink-0">
              <div className="w-8 h-8 rounded-lg bg-primary-container flex items-center justify-center">
                <Icon name="layers" className="text-on-primary text-[18px]" />
              </div>
              <span className="text-headline-sm font-headline-sm text-on-surface tracking-tight font-semibold">MineIQ</span>
              <span className="px-space-xs py-space-2xs bg-surface-container-high rounded text-on-surface-variant text-label-mono-sm font-label-mono-sm uppercase">Enterprise</span>
            </div>
            <nav className="hidden xl:flex items-center gap-space-xs">
              {visibleNav.map(n => {
                const isActive = tab === n.id || (n.id === 'documents' && tab === 'document');
                return (
                  <button key={n.id}
                    className={`px-space-sm py-space-xs rounded transition-all text-body-sm font-body-sm ${
                      isActive
                        ? 'bg-surface-container-low text-on-surface font-medium shadow-[inset_0_-2px_0_0_#4f46e5]'
                        : 'text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface'
                    }`}
                    onClick={() => setTab(n.id)}
                  >
                    {n.label}
                  </button>
                );
              })}
            </nav>
          </div>

          {/* Right: Search + User */}
          <div className="flex items-center gap-space-md">
            <div className="hidden md:flex items-center justify-between h-9 w-56 px-space-sm bg-surface-container-low rounded cursor-pointer shadow-[0_0_0_1px_rgba(0,0,0,0.06)] hover:bg-surface-container transition-all">
              <div className="flex items-center gap-space-xs">
                <Icon name="search" className="text-outline text-[18px]" />
                <span className="text-label-mono-sm font-label-mono-sm text-outline">Search intelligence...</span>
              </div>
              <kbd className="px-space-xs py-space-2xs bg-surface-container-lowest rounded text-label-mono-sm font-label-mono-sm text-on-surface-variant shadow-[0_1px_2px_rgba(0,0,0,0.04)]">⌘K</kbd>
            </div>
            <div className="flex items-center gap-space-sm">
              <div className="flex flex-col items-end">
                <span className="text-label-ui font-label-ui text-on-surface leading-none">{user?.name}</span>
                <span className="text-label-mono-sm font-label-mono-sm text-on-surface-variant leading-none mt-0.5">{user?.role}{user?.sub ? ` · ${user.sub}` : ''}</span>
              </div>
              <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center">
                <Icon name="person" className="text-on-primary text-[18px]" />
              </div>
              <button className={btnSmGhostCls} onClick={logout}>
                <Icon name="logout" className="text-[16px]" />
              </button>
            </div>
          </div>
        </div>

        {/* Mobile nav */}
        <div className="xl:hidden flex items-center gap-1 px-4 pb-2 overflow-x-auto">
          {visibleNav.map(n => {
            const isActive = tab === n.id || (n.id === 'documents' && tab === 'document');
            return (
              <button key={n.id}
                className={`flex-shrink-0 px-3 py-1.5 rounded text-label-ui font-label-ui transition-all ${
                  isActive ? 'bg-surface-container text-on-surface font-medium' : 'text-on-surface-variant hover:bg-surface-container-low'
                }`}
                onClick={() => setTab(n.id)}
              >
                {n.label}
              </button>
            );
          })}
        </div>
      </header>

      {/* ── Main content area ─────────────────────────────────────────────── */}
      <main className="pt-16 xl:pt-16 bg-surface">
        <div className="w-full px-margin-desktop py-space-xl flex flex-col gap-space-2xl max-w-[1600px] mx-auto">

          {/* ── OVERVIEW ────────────────────────────────────────────────── */}
          {tab === 'overview' && (
            <div className="flex flex-col gap-space-2xl">
              {/* Page header */}
              <div className="flex flex-col md:flex-row md:items-end justify-between gap-space-md">
                <div>
                  <div className="flex items-center gap-space-xs mb-space-2xs">
                    <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
                    <span className="text-label-mono-sm font-label-mono-sm uppercase text-on-surface-variant tracking-wider">Telemetry Engine Active</span>
                  </div>
                  <h1 className="text-headline-lg font-headline-lg text-on-surface tracking-tight font-semibold">Operational Intelligence</h1>
                </div>
                <div className="flex items-center gap-space-sm self-start md:self-auto">
                  <button className={btnPrimaryCls} onClick={() => setTab('documents')}>
                    <Icon name="file_upload" className="text-[18px]" />
                    Ingest Documents
                  </button>
                </div>
              </div>

              {/* KPI grid */}
              <section className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-space-base">
                <KpiCard label="Total Documents"     value={metrics?.total_documents ?? documents.length} sub="Ingested in repository" trend="+MoM" />
                <KpiCard label="Automation Rate"     value={pct(metrics?.automation_percentage) ?? '—'}   sub="Processed without manual review" />
                <KpiCard label="Extraction Accuracy" value={accuracyDisplay}
                  sub={metrics?.extraction_accuracy_detail ? `${metrics.extraction_accuracy_detail.fields_correct}/${metrics.extraction_accuracy_detail.fields_total} fields on benchmark` : 'Measured on labeled benchmark'}
                />
                <KpiCard label="Time Reduction"      value={pct(metrics?.time_reduction_percentage) ?? '—'} sub="vs 180-min manual baseline" />
              </section>

              {/* Recent documents */}
              <section className="bg-surface-container-lowest rounded-xl shadow-sm overflow-hidden">
                <div className="p-space-lg flex items-center justify-between">
                  <div>
                    <h3 className="text-headline-sm font-headline-sm text-on-surface font-semibold tracking-tight">Recent Parsed Extractions</h3>
                    <p className="text-body-sm font-body-sm text-on-surface-variant mt-space-2xs">Live feed of documents across active coal subsidiaries.</p>
                  </div>
                  <button className={btnSmGhostCls} onClick={() => setTab('documents')}>
                    View all <Icon name="chevron_right" className="text-[16px]" />
                  </button>
                </div>
                <DataTable
                  columns={[
                    { label: 'Filename' }, { label: 'Subsidiary' }, { label: 'Type' }, { label: 'Status' }, { label: '', right: true }
                  ]}
                  emptyMsg="No documents yet — upload one to begin."
                  rows={documents.slice(0, 6).map(d => (
                    <tr key={d.id} className="border-b border-outline-variant/40 hover:bg-surface-container-low group transition-colors">
                      <td className="py-3 px-4 font-medium text-on-surface text-body-sm">{d.original_filename}</td>
                      <td className="py-3 px-4 text-on-surface-variant text-body-sm">{d.subsidiary || '—'}</td>
                      <td className="py-3 px-4 text-on-surface-variant text-label-mono-sm font-label-mono-sm">{d.doc_type || 'unclassified'}</td>
                      <td className="py-3 px-4"><StatusBadge status={d.status} /></td>
                      <td className="py-3 px-4 text-right">
                        <button className={btnSmGhostCls} onClick={() => openDoc(d.id)}>Open <Icon name="open_in_new" className="text-[14px]" /></button>
                      </td>
                    </tr>
                  ))}
                />
              </section>
            </div>
          )}

          {/* ── DOCUMENTS ───────────────────────────────────────────────── */}
          {tab === 'documents' && (
            <div className="flex flex-col gap-space-xl">
              <div>
                <h1 className="text-headline-lg font-headline-lg text-on-surface tracking-tight font-semibold">Documents</h1>
                <p className="text-body-sm font-body-sm text-on-surface-variant mt-space-2xs">Upload and manage geological survey reports and production logs.</p>
              </div>

              {/* Upload card */}
              <div className="bg-surface-container-lowest rounded-xl shadow-sm p-space-xl">
                <h3 className="text-headline-sm font-headline-sm text-on-surface font-semibold mb-space-base">Upload &amp; Process Document</h3>
                <input type="file" id="file-in" className="hidden" onChange={e => setUploadFile(e.target.files[0])} />
                <label htmlFor="file-in"
                  className="flex flex-col items-center justify-center w-full h-32 border-2 border-dashed border-outline-variant rounded-xl cursor-pointer hover:border-primary-container hover:bg-surface-container-low transition-all text-on-surface-variant group">
                  {uploadFile ? (
                    <div className="flex items-center gap-space-sm text-on-surface">
                      <Icon name="description" className="text-[24px] text-primary-container" />
                      <div>
                        <div className="font-medium text-body-md">{uploadFile.name}</div>
                        <div className="text-label-mono-sm font-label-mono-sm text-on-surface-variant">{(uploadFile.size / 1024).toFixed(1)} KB</div>
                      </div>
                    </div>
                  ) : (
                    <div className="flex flex-col items-center gap-space-xs">
                      <Icon name="cloud_upload" className="text-[32px] group-hover:text-primary-container transition-colors" />
                      <span className="text-body-sm font-body-sm">Click to select a PDF, spreadsheet, image or text file</span>
                    </div>
                  )}
                </label>
                <div className="flex items-center justify-end mt-space-base gap-space-sm">
                  {uploadFile && <button className={btnGhostCls} onClick={() => setUploadFile(null)}>Clear</button>}
                  <button className={btnPrimaryCls} disabled={!uploadFile} onClick={handleUpload}>
                    <Icon name="rocket_launch" className="text-[16px]" /> Start Pipeline
                  </button>
                </div>

                {/* Pipeline progress */}
                {procMsg && (
                  <div className="mt-space-lg pt-space-lg border-t border-outline-variant/40">
                    {['Upload & idempotency check', 'OCR + structured extraction', 'Validation & discrepancy check', 'LLM classification', 'Vector indexing & report'].map((s, i) => {
                      const n = i + 1;
                      const done   = procStep > n;
                      const active = procStep === n;
                      return (
                        <div key={s} className="flex items-center gap-space-sm py-space-xs">
                          <div className={`w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 text-[11px] ${done ? 'bg-emerald-500 text-white' : active ? 'bg-primary-container text-on-primary' : 'bg-surface-container-high text-on-surface-variant'}`}>
                            {done ? <Icon name="check" className="text-[14px]" /> : active ? <Icon name="refresh" className="text-[14px] spin" /> : <span>{n}</span>}
                          </div>
                          <span className={`text-body-sm font-body-sm ${done || active ? 'text-on-surface' : 'text-outline'}`}>{s}</span>
                        </div>
                      );
                    })}
                    <div className="mt-space-sm text-label-mono-sm font-label-mono-sm text-outline">{procMsg}</div>
                  </div>
                )}
              </div>

              {/* Documents table */}
              <div className="bg-surface-container-lowest rounded-xl shadow-sm overflow-hidden">
                <div className="p-space-lg flex flex-col sm:flex-row sm:items-center gap-space-md">
                  <div className="flex items-center gap-space-xs h-9 flex-1 max-w-72 px-space-sm bg-surface-container-low rounded-lg border border-outline-variant focus-within:border-primary-container transition-all">
                    <Icon name="search" className="text-outline text-[18px]" />
                    <input className="flex-1 bg-transparent text-body-sm text-on-surface placeholder:text-outline focus:outline-none"
                      placeholder="Search filename…" value={searchQuery} onChange={e => setSearchQuery(e.target.value)} />
                  </div>
                  <select className={selectCls} value={subFilter} onChange={e => setSubFilter(e.target.value)}>
                    {['ALL','MCL','ECL','BCCL','CCL','WCL','SECL','NCL','CMPDI'].map(s => (
                      <option key={s} value={s}>{s === 'ALL' ? 'All subsidiaries' : s}</option>
                    ))}
                  </select>
                  <span className="text-label-mono-sm font-label-mono-sm text-on-surface-variant ml-auto">{filtered.length} records</span>
                </div>
                <DataTable
                  columns={[
                    { label: 'Filename' }, { label: 'Subsidiary' }, { label: 'Type' }, { label: 'Status' }, { label: 'Uploaded' }, { label: '', right: true }
                  ]}
                  emptyMsg="No documents yet."
                  rows={filtered.map(d => (
                    <tr key={d.id} className="border-b border-outline-variant/40 hover:bg-surface-container-low transition-colors">
                      <td className="py-3 px-4 font-medium text-on-surface text-body-sm">{d.original_filename}</td>
                      <td className="py-3 px-4 text-on-surface-variant text-body-sm">{d.subsidiary || '—'}</td>
                      <td className="py-3 px-4 text-label-mono-sm font-label-mono-sm text-on-surface-variant">{d.doc_type || 'unclassified'}</td>
                      <td className="py-3 px-4"><StatusBadge status={d.status} /></td>
                      <td className="py-3 px-4 text-label-mono-sm font-label-mono-sm text-outline">{d.uploaded_at ? new Date(d.uploaded_at).toLocaleDateString() : '—'}</td>
                      <td className="py-3 px-4 text-right">
                        <button className={btnSmGhostCls} onClick={() => openDoc(d.id)}>Open</button>
                      </td>
                    </tr>
                  ))}
                />
              </div>
            </div>
          )}

          {/* ── DOCUMENT DETAIL ──────────────────────────────────────────── */}
          {tab === 'document' && selectedDoc && (
            <div className="flex flex-col gap-space-xl">
              <button className={btnSmGhostCls} onClick={() => setTab('documents')}>
                <Icon name="arrow_back" className="text-[16px]" /> Back to Documents
              </button>

              {/* Header card */}
              <div className="bg-surface-container-lowest rounded-xl shadow-sm p-space-xl">
                <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-space-md">
                  <div>
                    <div className="flex items-center gap-space-sm flex-wrap">
                      <h2 className="text-headline-md font-headline-md text-on-surface font-semibold">{selectedDoc.original_filename}</h2>
                      {selectedDoc.subsidiary && (
                        <span className="px-space-xs py-space-2xs bg-primary-fixed text-on-primary-fixed rounded text-label-mono-sm font-label-mono-sm">{selectedDoc.subsidiary}</span>
                      )}
                      <StatusBadge status={selectedDoc.status} />
                    </div>
                    <div className="text-body-sm font-body-sm text-on-surface-variant mt-space-xs">
                      {selectedDoc.doc_type || 'unclassified'} · {selectedDoc.topic_area || 'general'} · {selectedDoc.source_type}
                    </div>
                  </div>
                  {selectedReport && (
                    <div className="flex items-center gap-space-sm">
                      <button className={btnGhostCls} onClick={() => downloadReport(selectedDoc.id, 'pdf')}>
                        <Icon name="download" className="text-[16px]" /> PDF
                      </button>
                      <button className={btnPrimaryCls} onClick={() => downloadReport(selectedDoc.id, 'docx')}>
                        <Icon name="download" className="text-[16px]" /> DOCX
                      </button>
                    </div>
                  )}
                </div>

                {/* Validation alerts */}
                {selectedDoc.validations?.length > 0 && (
                  <div className="mt-space-lg bg-amber-50 border border-amber-200 rounded-xl p-space-md">
                    <div className="flex items-center gap-space-xs text-amber-700 font-semibold mb-space-xs">
                      <Icon name="warning" className="text-[16px]" /> Validation Alerts
                    </div>
                    {selectedDoc.validations.map((v, i) => (
                      <div key={i} className="text-body-sm text-amber-800">• {v.message}</div>
                    ))}
                  </div>
                )}
              </div>

              {/* Structured records */}
              {selectedDoc.structured_records?.length > 0 && (
                <div className="bg-surface-container-lowest rounded-xl shadow-sm overflow-hidden">
                  <div className="p-space-lg border-b border-outline-variant/40">
                    <h3 className="text-headline-sm font-headline-sm text-on-surface font-semibold">Structured Records ({selectedDoc.structured_records.length})</h3>
                  </div>
                  <DataTable
                    columns={[
                      { label: 'Mine' }, { label: 'Year' }, { label: 'Target (MT)' }, { label: 'Actual (MT)' }, { label: 'Dispatch (MT)' }, { label: 'OB (MCuM)' }
                    ]}
                    rows={selectedDoc.structured_records.map((r, i) => (
                      <tr key={i} className="border-b border-outline-variant/40 hover:bg-surface-container-low">
                        <td className="py-3 px-4 font-medium text-on-surface text-body-sm">{r.mine_name || '—'}</td>
                        <td className="py-3 px-4 text-label-mono-sm font-label-mono-sm text-on-surface">{r.report_year ?? '—'}</td>
                        <td className="py-3 px-4 text-label-mono-sm font-label-mono-sm text-on-surface text-right">{r.production_target_mt ?? '—'}</td>
                        <td className="py-3 px-4 text-label-mono-sm font-label-mono-sm text-on-surface text-right">{r.actual_production_mt ?? '—'}</td>
                        <td className="py-3 px-4 text-label-mono-sm font-label-mono-sm text-on-surface text-right">{r.dispatch_mt ?? '—'}</td>
                        <td className="py-3 px-4 text-label-mono-sm font-label-mono-sm text-on-surface text-right">{r.overburden_mcum ?? '—'}</td>
                      </tr>
                    ))}
                  />
                </div>
              )}

              {/* Report */}
              <div className="bg-surface-container-lowest rounded-xl shadow-sm p-space-xl">
                <div className="flex items-center justify-between mb-space-lg">
                  <div className="flex items-center gap-space-xs">
                    <Icon name="description" className="text-[20px] text-primary-container" />
                    <h3 className="text-headline-sm font-headline-sm text-on-surface font-semibold">Generated Report</h3>
                  </div>
                  {selectedReport && (
                    <span className="px-space-xs py-space-2xs bg-amber-50 text-amber-700 border border-amber-200 rounded text-label-mono-sm font-label-mono-sm uppercase">
                      AI draft · human review required
                    </span>
                  )}
                </div>
                {selectedReport
                  ? <Markdown text={selectedReport.report_text} />
                  : <div className="py-space-xl text-center text-body-sm text-outline">Report is generating asynchronously. Reopen shortly.</div>
                }
              </div>

              {/* Raw text */}
              <div className="bg-surface-container-lowest rounded-xl shadow-sm p-space-xl">
                <h3 className="text-headline-sm font-headline-sm text-on-surface font-semibold mb-space-base">Extracted Text</h3>
                <pre className="bg-surface-container-low border border-outline-variant rounded-xl p-space-md text-label-mono-sm font-label-mono-sm text-on-surface-variant overflow-x-auto max-h-60 whitespace-pre-wrap">
                  {selectedDoc.extracted_text || 'No text extracted.'}
                </pre>
              </div>
            </div>
          )}

          {/* ── ASK AI ──────────────────────────────────────────────────── */}
          {tab === 'ask' && (
            <div className="flex flex-col gap-space-xl max-w-3xl mx-auto w-full">
              <div>
                <div className="flex items-center gap-space-xs mb-space-xs">
                  <Icon name="auto_awesome" className="text-[20px] text-primary-container" />
                  <h1 className="text-headline-lg font-headline-lg text-on-surface tracking-tight font-semibold">Ask MineIQ</h1>
                </div>
                <p className="text-body-sm font-body-sm text-on-surface-variant">Grounded answers with citations. Results are scoped to your authorized role.</p>
              </div>

              <div className="bg-surface-container-lowest rounded-xl shadow-sm p-space-xl flex flex-col gap-space-md">
                {/* Scope selector */}
                <div className="flex items-center gap-space-xs">
                  {[['CROSS_DOCUMENT','All authorized documents'],['SELECTED', selectedDoc ? `Selected: ${selectedDoc.original_filename}` : 'Selected document']].map(([v, l]) => (
                    <button key={v}
                      className={`h-8 px-space-sm rounded-lg text-label-ui font-label-ui transition-all ${ragScope === v ? 'bg-primary-container text-on-primary shadow-sm' : 'bg-surface-container-low text-on-surface-variant hover:bg-surface-container border border-outline-variant'}`}
                      disabled={v === 'SELECTED' && !selectedDoc}
                      onClick={() => setRagScope(v)}>{l}
                    </button>
                  ))}
                </div>

                {/* Query input */}
                <div className="flex gap-space-sm">
                  <input
                    className={`${inputCls} flex-1`}
                    placeholder="e.g. What was MCL production in 2025?"
                    value={ragQuery}
                    onChange={e => setRagQuery(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && runRag()}
                  />
                  <button className={btnPrimaryCls} onClick={runRag} disabled={ragLoading}>
                    {ragLoading ? <Icon name="refresh" className="text-[16px] spin" /> : <Icon name="send" className="text-[16px]" />}
                    Ask
                  </button>
                </div>
              </div>

              {/* Result */}
              {ragResult && (
                <div className="bg-surface-container-lowest rounded-xl shadow-sm p-space-xl flex flex-col gap-space-md">
                  <div className="flex items-center justify-between">
                    <span className={`inline-flex items-center gap-space-xs px-space-xs py-space-2xs rounded-full border text-label-mono-sm font-label-mono-sm uppercase ${ragResult.grounded ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-amber-50 text-amber-700 border-amber-200'}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${ragResult.grounded ? 'bg-emerald-500' : 'bg-amber-500'}`} />
                      {ragResult.grounded ? 'Grounded' : 'Insufficient evidence'}
                    </span>
                    <span className="text-label-mono-sm font-label-mono-sm text-outline">
                      {ragResult.mode === 'SQL_NUMERIC' ? `SQL · ${ragResult.intent}` : 'Vector retrieval'} · scope {ragResult.authorized_scope}
                    </span>
                  </div>
                  <Markdown text={ragResult.answer} />

                  {ragResult.table?.length > 0 && (
                    <div className="mt-space-sm overflow-x-auto border border-outline-variant rounded-xl">
                      <table className="w-full border-collapse text-body-sm">
                        <thead className="bg-surface-container-low">
                          <tr className="border-b border-outline-variant">
                            {['Subsidiary','Year','Mines','Target (MT)','Actual (MT)'].map(c => (
                              <th key={c} className="py-2 px-4 text-left text-label-mono-sm font-label-mono-sm uppercase text-on-surface-variant">{c}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {ragResult.table.map((r, i) => (
                            <tr key={i} className="border-b border-outline-variant/40 hover:bg-surface-container-low">
                              <td className="py-2 px-4">{r.subsidiary}</td>
                              <td className="py-2 px-4 font-label-mono-sm text-label-mono-sm">{r.report_year}</td>
                              <td className="py-2 px-4">{r.mines}</td>
                              <td className="py-2 px-4 text-right font-label-mono-sm text-label-mono-sm">{r.production_target_mt ?? '—'}</td>
                              <td className="py-2 px-4 text-right font-label-mono-sm text-label-mono-sm">{r.actual_production_mt ?? '—'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {ragResult.sources?.length > 0 && (
                    <div>
                      <div className="text-label-mono-sm font-label-mono-sm uppercase tracking-wider text-outline mb-space-sm">Sources ({ragResult.sources.length})</div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-space-sm">
                        {ragResult.sources.map((s, i) => (
                          <div key={i} className="bg-surface-container-low border border-outline-variant rounded-xl p-space-md">
                            <div className="flex items-center justify-between mb-space-xs">
                              <span className="font-medium text-body-sm text-on-surface">{s.filename}</span>
                              {s.subsidiary && <span className="px-space-xs py-space-2xs bg-primary-fixed text-on-primary-fixed rounded text-label-mono-sm font-label-mono-sm">{s.subsidiary}</span>}
                            </div>
                            {s.relevance_snippet && <div className="text-body-sm text-on-surface-variant italic">"{s.relevance_snippet}"</div>}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ── ANALYTICS ────────────────────────────────────────────────── */}
          {tab === 'analytics' && (
            <div className="flex flex-col gap-space-xl">
              <div>
                <h1 className="text-headline-lg font-headline-lg text-on-surface tracking-tight font-semibold">Analytics</h1>
                <p className="text-body-sm font-body-sm text-on-surface-variant mt-space-2xs">Corpus intelligence and trend analysis across authorized documents.</p>
              </div>

              {/* Word cloud */}
              <div className="bg-surface-container-lowest rounded-xl shadow-sm p-space-xl">
                <h3 className="text-headline-sm font-headline-sm text-on-surface font-semibold mb-space-lg">Corpus Word Cloud</h3>
                {wordcloud.length ? (
                  <div className="flex flex-wrap gap-space-sm">
                    {wordcloud.map((w, i) => {
                      const max  = wordcloud[0]?.value || 1;
                      const size = 11 + Math.round((w.value / max) * 14);
                      const colors = ['text-primary-container','text-emerald-600','text-on-surface'];
                      return (
                        <span key={w.text}
                          className={`px-space-xs py-space-2xs bg-surface-container-low rounded-full cursor-default hover:bg-surface-container ${colors[i % 3]}`}
                          style={{ fontSize: size }}>
                          {w.text} <span className="text-outline text-[10px]">{w.value}</span>
                        </span>
                      );
                    })}
                  </div>
                ) : <div className="py-space-xl text-center text-body-sm text-outline">No corpus terms yet.</div>}
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-space-xl">
                {/* Topics */}
                <div className="bg-surface-container-lowest rounded-xl shadow-sm p-space-xl">
                  <h3 className="text-headline-sm font-headline-sm text-on-surface font-semibold mb-space-lg">Topic Distribution</h3>
                  {topics.filter(t => t.count > 0).length ? topics.filter(t => t.count > 0).map(t => (
                    <div key={t.topic} className="flex items-center justify-between py-space-sm border-b border-outline-variant/40 last:border-0">
                      <span className="text-body-sm font-body-sm text-on-surface">{t.topic}</span>
                      <span className="px-space-xs py-space-2xs bg-primary-fixed text-on-primary-fixed rounded text-label-mono-sm font-label-mono-sm">{t.count}</span>
                    </div>
                  )) : <div className="py-space-xl text-center text-body-sm text-outline">No topics yet.</div>}
                </div>

                {/* Trends */}
                <div className="bg-surface-container-lowest rounded-xl shadow-sm p-space-xl">
                  <h3 className="text-headline-sm font-headline-sm text-on-surface font-semibold mb-space-lg">Trends by Year</h3>
                  {trends.length ? trends.map(tr => (
                    <div key={tr.year} className="flex items-start justify-between py-space-sm border-b border-outline-variant/40 last:border-0 gap-space-sm">
                      <span className="text-label-mono-md font-label-mono-md text-on-surface font-medium">{tr.year}</span>
                      <span className="text-label-mono-sm font-label-mono-sm text-on-surface-variant text-right">
                        Prod {tr['Coal Production']} · Geo {tr['Geological Exploration']} · OB {tr['Overburden Removal']} · Safety {tr['Safety & Compliance']}
                      </span>
                    </div>
                  )) : <div className="py-space-xl text-center text-body-sm text-outline">Building trend timeline…</div>}
                </div>
              </div>
            </div>
          )}

          {/* ── DISCREPANCIES ────────────────────────────────────────────── */}
          {tab === 'discrepancies' && (
            <div className="flex flex-col gap-space-xl">
              <div>
                <h1 className="text-headline-lg font-headline-lg text-on-surface tracking-tight font-semibold">Discrepancies</h1>
                <p className="text-body-sm font-body-sm text-on-surface-variant mt-space-2xs">Cross-document data conflicts detected in your authorized scope.</p>
              </div>

              <section className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-space-base">
                <KpiCard label="Conflicts Found"  value={discrepancies?.count ?? '—'}                                  sub="Across authorized documents" />
                <KpiCard label="Critical"         value={discrepancies?.by_severity?.critical ?? '—'}                 sub="≥ 10% divergence" accent="text-red-600" />
                <KpiCard label="High"             value={discrepancies?.by_severity?.high ?? '—'}                     sub="≥ 3% divergence" accent="text-amber-600" />
                <KpiCard label="Records Scanned"  value={discrepancies?.scanned_records ?? '—'}                       sub="Structured rows compared" />
              </section>

              <div className="bg-surface-container-lowest rounded-xl shadow-sm p-space-xl">
                <h3 className="text-headline-sm font-headline-sm text-on-surface font-semibold mb-space-lg">Cross-Document Discrepancies</h3>
                {discrepancies?.discrepancies?.length ? (
                  <div className="flex flex-col gap-space-md">
                    {discrepancies.discrepancies.map((d, i) => (
                      <div key={i} className="border border-outline-variant rounded-xl p-space-lg">
                        <div className="flex items-center justify-between mb-space-md flex-wrap gap-space-sm">
                          <div>
                            <span className="font-semibold text-body-md text-on-surface">{d.subsidiary} · {d.mine_name} · {d.report_year}</span>
                            <span className="text-body-sm text-on-surface-variant ml-2">— {d.metric_label}</span>
                          </div>
                          <span className={`px-space-xs py-space-2xs rounded-full border text-label-mono-sm font-label-mono-sm uppercase ${d.severity === 'critical' ? 'bg-red-50 text-red-700 border-red-200' : d.severity === 'high' ? 'bg-amber-50 text-amber-700 border-amber-200' : 'bg-surface-container text-on-surface-variant border-outline-variant'}`}>
                            {d.severity} · {d.pct_difference}%
                          </span>
                        </div>
                        <div className="grid grid-cols-2 gap-space-md">
                          <div className="bg-surface-container-low rounded-xl p-space-md">
                            <div className="text-label-mono-sm font-label-mono-sm text-outline mb-space-xs">Value A · {d.source_a.filename}</div>
                            <div className="text-headline-md font-headline-md text-on-surface">{d.value_a}</div>
                          </div>
                          <div className="bg-surface-container-low rounded-xl p-space-md">
                            <div className="text-label-mono-sm font-label-mono-sm text-outline mb-space-xs">Value B · {d.source_b.filename}</div>
                            <div className="text-headline-md font-headline-md text-on-surface">{d.value_b}</div>
                          </div>
                        </div>
                        <div className="text-label-mono-sm font-label-mono-sm text-outline mt-space-sm">Difference {d.difference} · status {d.status.replace('_', ' ')}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="py-space-xl text-center text-body-sm text-outline">No discrepancies detected in your authorized scope.</div>
                )}
              </div>
            </div>
          )}

          {/* ── PQ COPILOT ──────────────────────────────────────────────── */}
          {tab === 'parliament' && (
            <div className="flex flex-col gap-space-xl">
              <div>
                <div className="flex items-center gap-space-xs mb-space-xs">
                  <Icon name="account_balance" className="text-[20px] text-primary-container" />
                  <h1 className="text-headline-lg font-headline-lg text-on-surface tracking-tight font-semibold">PQ Copilot</h1>
                </div>
                <p className="text-body-sm font-body-sm text-on-surface-variant">Parliamentary Question AI drafting with cited extraction from authorized mining records.</p>
              </div>

              {CAN_WRITE_PQ.includes(user.role) && (
                <div className="bg-surface-container-lowest rounded-xl shadow-sm p-space-xl">
                  <h3 className="text-headline-sm font-headline-sm text-on-surface font-semibold mb-space-xs">Register New Question</h3>
                  <p className="text-body-sm font-body-sm text-on-surface-variant mb-space-lg">MineIQ extracts subsidiaries, metrics and period, then drafts a cited response from authorized records.</p>
                  <div className="flex flex-col gap-space-md">
                    <textarea className={`${inputCls} h-auto`} rows={3}
                      placeholder="e.g. Provide production and dispatch figures for MCL, NCL and SECL for the last five years and explain major variations."
                      value={newPQ.question_text}
                      onChange={e => setNewPQ({ ...newPQ, question_text: e.target.value })}
                      style={{ resize: 'vertical', fontFamily: 'inherit' }}
                    />
                    <div className="flex flex-col sm:flex-row gap-space-md">
                      <input className={`${inputCls} flex-1`} placeholder="PQ number (optional)" value={newPQ.pq_number} onChange={e => setNewPQ({ ...newPQ, pq_number: e.target.value })} />
                      <input className={`${inputCls} flex-1`} type="date" value={newPQ.due_date} onChange={e => setNewPQ({ ...newPQ, due_date: e.target.value })} />
                      <button className={btnPrimaryCls} onClick={createPQ} disabled={pqBusy || !newPQ.question_text.trim()}>
                        {pqBusy ? <Icon name="refresh" className="text-[16px] spin" /> : <Icon name="account_balance" className="text-[16px]" />}
                        Register &amp; Analyze
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* PQ list */}
              <div className="bg-surface-container-lowest rounded-xl shadow-sm overflow-hidden">
                <div className="p-space-lg border-b border-outline-variant/40">
                  <h3 className="text-headline-sm font-headline-sm text-on-surface font-semibold">Questions ({pqs.length})</h3>
                </div>
                <DataTable
                  columns={[{ label: 'PQ #' }, { label: 'Question' }, { label: 'Subsidiaries' }, { label: 'Due' }, { label: 'Status' }, { label: '', right: true }]}
                  emptyMsg="No parliamentary questions yet."
                  rows={pqs.map(p => (
                    <tr key={p.id} className="border-b border-outline-variant/40 hover:bg-surface-container-low transition-colors">
                      <td className="py-3 px-4 font-label-mono-sm text-label-mono-sm text-on-surface-variant">{p.pq_number || '—'}</td>
                      <td className="py-3 px-4 text-body-sm text-on-surface max-w-xs">{(p.question_text || '').slice(0, 90)}{p.question_text?.length > 90 ? '…' : ''}</td>
                      <td className="py-3 px-4">
                        <div className="flex flex-wrap gap-1">
                          {(p.subsidiaries || []).map(s => <span key={s} className="px-space-xs py-space-2xs bg-primary-fixed text-on-primary-fixed rounded text-label-mono-sm font-label-mono-sm">{s}</span>)}
                        </div>
                      </td>
                      <td className="py-3 px-4 text-label-mono-sm font-label-mono-sm text-outline">{p.due_date || '—'}</td>
                      <td className="py-3 px-4">
                        <StatusBadge status={p.status?.toLowerCase().replace('_', '-')} />
                      </td>
                      <td className="py-3 px-4 text-right">
                        <button className={btnSmGhostCls} onClick={() => openPQ(p.id)}>View <Icon name="chevron_right" className="text-[14px]" /></button>
                      </td>
                    </tr>
                  ))}
                />
              </div>

              {/* Selected PQ detail */}
              {selectedPQ && (
                <div className="bg-surface-container-lowest rounded-xl shadow-sm p-space-xl flex flex-col gap-space-lg">
                  <div className="flex items-start justify-between gap-space-md">
                    <div>
                      <div className="text-label-mono-sm font-label-mono-sm text-outline mb-space-xs">{selectedPQ.pq_number || 'PQ'} · {selectedPQ.house || ''}</div>
                      <div className="font-semibold text-body-lg text-on-surface max-w-2xl">{selectedPQ.question_text}</div>
                    </div>
                    <StatusBadge status={selectedPQ.status?.toLowerCase().replace('_', '-')} />
                  </div>

                  <div className="flex flex-wrap gap-space-xs">
                    {(selectedPQ.subsidiaries || []).map(s => <span key={s} className="px-space-xs py-space-2xs bg-primary-fixed text-on-primary-fixed rounded text-label-mono-sm font-label-mono-sm">{s}</span>)}
                    {selectedPQ.period_from && <span className="px-space-xs py-space-2xs bg-surface-container-high text-on-surface-variant rounded text-label-mono-sm font-label-mono-sm">{selectedPQ.period_from}–{selectedPQ.period_to}</span>}
                    {(selectedPQ.metrics || []).map(m => <span key={m} className="px-space-xs py-space-2xs bg-surface-container-high text-on-surface-variant rounded text-label-mono-sm font-label-mono-sm">{m}</span>)}
                  </div>

                  {CAN_WRITE_PQ.includes(user.role) && (
                    <button className={btnPrimaryCls} onClick={() => generatePQDraft(selectedPQ.id)} disabled={pqBusy}>
                      {pqBusy ? <Icon name="refresh" className="text-[16px] spin" /> : <Icon name="gavel" className="text-[16px]" />}
                      {selectedPQ.response ? 'Regenerate Draft' : 'Generate Cited Draft'}
                    </button>
                  )}

                  {selectedPQ.response ? (
                    <div>
                      <div className="flex items-center justify-between mb-space-md">
                        <span className="text-headline-sm font-headline-sm text-on-surface font-semibold">Draft Response</span>
                        <span className="px-space-xs py-space-2xs bg-amber-50 text-amber-700 border border-amber-200 rounded text-label-mono-sm font-label-mono-sm uppercase">{selectedPQ.response.status}</span>
                      </div>
                      <div className="border border-outline-variant rounded-xl p-space-lg bg-surface-container-low">
                        <Markdown text={selectedPQ.response.draft_text} />
                      </div>
                      {selectedPQ.status === 'PENDING_APPROVAL' && CAN_APPROVE_PQ.includes(user.role) && (
                        <div className="flex gap-space-sm mt-space-md">
                          <button className={btnPrimaryCls} onClick={() => reviewPQ(selectedPQ.id, 'APPROVED')}>
                            <Icon name="check_circle" className="text-[16px]" /> Approve
                          </button>
                          <button className={`${btnGhostCls} text-red-600 border-red-200`} onClick={() => reviewPQ(selectedPQ.id, 'REJECTED')}>
                            Reject
                          </button>
                        </div>
                      )}
                      {selectedPQ.status === 'APPROVED' && (
                        <div className="flex items-center gap-space-xs mt-space-md text-emerald-600 text-body-sm">
                          <Icon name="check_circle" className="text-[16px]" />
                          Approved{selectedPQ.response.approved_by ? ` by ${selectedPQ.response.approved_by}` : ''}
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="py-space-xl text-center text-body-sm text-outline">No draft generated yet.</div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ── USERS ────────────────────────────────────────────────────── */}
          {tab === 'users' && (
            <div className="flex flex-col gap-space-xl">
              <div>
                <h1 className="text-headline-lg font-headline-lg text-on-surface tracking-tight font-semibold">Users &amp; Roles</h1>
                <p className="text-body-sm font-body-sm text-on-surface-variant mt-space-2xs">Manage system access with role-based and subsidiary-scoped permissions.</p>
              </div>

              {CAN_WRITE_USERS.includes(user.role) && (
                <div className="bg-surface-container-lowest rounded-xl shadow-sm p-space-xl">
                  <h3 className="text-headline-sm font-headline-sm text-on-surface font-semibold mb-space-lg">Add User</h3>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-space-md">
                    <input className={inputCls} placeholder="Username" value={newUser.username} onChange={e => setNewUser({ ...newUser, username: e.target.value })} />
                    <input className={inputCls} placeholder="Full name"  value={newUser.full_name} onChange={e => setNewUser({ ...newUser, full_name: e.target.value })} />
                    <input className={inputCls} type="password" placeholder="Password (min 6)" value={newUser.password} onChange={e => setNewUser({ ...newUser, password: e.target.value })} />
                    <select className={`${selectCls} w-full`} value={newUser.role} onChange={e => setNewUser({ ...newUser, role: e.target.value })}>
                      {ALL_ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                    </select>
                    <select className={`${selectCls} w-full`} value={newUser.assigned_subsidiary} onChange={e => setNewUser({ ...newUser, assigned_subsidiary: e.target.value })}>
                      <option value="">No subsidiary scope</option>
                      {['MCL','ECL','BCCL','CCL','WCL','SECL','NCL','CMPDI'].map(s => <option key={s} value={s}>{s}</option>)}
                    </select>
                    <button className={`${btnPrimaryCls} w-full`} onClick={createUser} disabled={!newUser.username || !newUser.password || !newUser.full_name}>
                      <Icon name="person_add" className="text-[16px]" /> Create User
                    </button>
                  </div>
                  {userMsg && (
                    <div className={`mt-space-md text-body-sm ${userMsg.startsWith('Created') ? 'text-emerald-600' : 'text-red-600'}`}>{userMsg}</div>
                  )}
                </div>
              )}

              <div className="bg-surface-container-lowest rounded-xl shadow-sm overflow-hidden">
                <div className="p-space-lg border-b border-outline-variant/40">
                  <h3 className="text-headline-sm font-headline-sm text-on-surface font-semibold">Users ({users.length})</h3>
                </div>
                <DataTable
                  columns={[
                    { label: 'Username' }, { label: 'Name' }, { label: 'Role' }, { label: 'Scope' }, { label: 'Status' }, { label: 'Last Login' },
                    ...(CAN_WRITE_USERS.includes(user.role) ? [{ label: '', right: true }] : [])
                  ]}
                  emptyMsg="No users visible."
                  rows={users.map(u => (
                    <tr key={u.id} className="border-b border-outline-variant/40 hover:bg-surface-container-low transition-colors">
                      <td className="py-3 px-4 font-medium text-on-surface text-body-sm">{u.username}</td>
                      <td className="py-3 px-4 text-on-surface-variant text-body-sm">{u.full_name}</td>
                      <td className="py-3 px-4">
                        <span className="px-space-xs py-space-2xs bg-primary-fixed text-on-primary-fixed rounded text-label-mono-sm font-label-mono-sm">{u.role}</span>
                      </td>
                      <td className="py-3 px-4 text-label-mono-sm font-label-mono-sm text-on-surface-variant">{u.assigned_subsidiary || '—'}</td>
                      <td className="py-3 px-4">
                        <span className={`px-space-xs py-space-2xs rounded-full border text-label-mono-sm font-label-mono-sm uppercase ${u.is_active ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-red-50 text-red-700 border-red-200'}`}>
                          {u.is_active ? 'active' : 'disabled'}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-label-mono-sm font-label-mono-sm text-outline">{u.last_login ? new Date(u.last_login).toLocaleString() : 'never'}</td>
                      {CAN_WRITE_USERS.includes(user.role) && (
                        <td className="py-3 px-4 text-right whitespace-nowrap">
                          <button className={btnSmGhostCls} onClick={() => toggleUser(u)}>{u.is_active ? 'Disable' : 'Enable'}</button>
                          {u.username !== user.username && (
                            <button className={`${btnSmGhostCls} text-red-500 ml-1`} onClick={() => removeUser(u)}>
                              <Icon name="delete" className="text-[14px]" />
                            </button>
                          )}
                        </td>
                      )}
                    </tr>
                  ))}
                />
              </div>
            </div>
          )}

          {/* ── AUDIT ────────────────────────────────────────────────────── */}
          {tab === 'audit' && (
            <div className="flex flex-col gap-space-xl">
              <div>
                <h1 className="text-headline-lg font-headline-lg text-on-surface tracking-tight font-semibold">Audit Trail</h1>
                <p className="text-body-sm font-body-sm text-on-surface-variant mt-space-2xs">Complete immutable audit log of all system events, access controls, and data operations.</p>
              </div>

              <section className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-space-base">
                <KpiCard label="Docs Processed"  value={metrics?.processed_documents ?? '—'}   sub="Reached classified state" />
                <KpiCard label="Reports Generated" value={metrics?.reports_generated ?? '—'}   sub="Stored & indexed" />
                <KpiCard label="Avg Processing"   value={metrics?.average_processing_time_sec ? `${metrics.average_processing_time_sec}s` : '—'} sub="Per document" />
                <KpiCard label="Access Blocks"    value={auditLogs.filter(l => l.result === 'DENIED' || (l.action || '').includes('ISOLATION')).length}
                  sub="RBAC / isolation stops" accent="text-red-600" />
              </section>

              <div className="bg-surface-container-lowest rounded-xl shadow-sm overflow-hidden">
                <div className="p-space-lg border-b border-outline-variant/40">
                  <h3 className="text-headline-sm font-headline-sm text-on-surface font-semibold">Audit Log</h3>
                </div>
                <DataTable
                  columns={[{ label: 'Time' }, { label: 'User' }, { label: 'Role' }, { label: 'Action' }, { label: 'Service' }, { label: 'Result' }]}
                  emptyMsg="No audit events yet."
                  rows={auditLogs.slice(0, 40).map(l => (
                    <tr key={l.id} className="border-b border-outline-variant/40 hover:bg-surface-container-low transition-colors">
                      <td className="py-3 px-4 text-label-mono-sm font-label-mono-sm text-outline">{l.timestamp ? new Date(l.timestamp).toLocaleString() : '—'}</td>
                      <td className="py-3 px-4 font-medium text-on-surface text-body-sm">{l.user_id}</td>
                      <td className="py-3 px-4 text-label-mono-sm font-label-mono-sm text-on-surface-variant">{l.user_role}</td>
                      <td className="py-3 px-4 text-body-sm text-on-surface">{l.action}</td>
                      <td className="py-3 px-4 text-label-mono-sm font-label-mono-sm text-on-surface-variant">{l.service}</td>
                      <td className="py-3 px-4">
                        <span className={`px-space-xs py-space-2xs rounded-full border text-label-mono-sm font-label-mono-sm uppercase ${
                          ['SUCCESS','APPROVED'].includes(l.result) ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                          : ['DENIED','PURGED'].includes(l.result)  ? 'bg-red-50 text-red-700 border-red-200'
                          : 'bg-amber-50 text-amber-700 border-amber-200'
                        }`}>{l.result}</span>
                      </td>
                    </tr>
                  ))}
                />
              </div>
            </div>
          )}

        </div>
      </main>
    </div>
  );
}
