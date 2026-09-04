import React, { useState, useEffect } from 'react';
import {
  FileText, Upload, Database, Shield, Search, Sparkles, BarChart3,
  RefreshCw, AlertTriangle, CheckCircle2, Download, ArrowLeft, Layers,
  MessageSquare, Activity, ChevronRight, Users, Trash2, Plus, LogOut, Lock
} from 'lucide-react';

const API_BASE = 'http://localhost:8000';
const RAG_API = 'http://localhost:8005';
const ANALYTICS_API = 'http://localhost:8006';

const DEMO_USERS = [
  { username: 'admin', role: 'ADMIN', name: 'System Admin', sub: null, pw: 'admin123' },
  { username: 'ministry_officer', role: 'MINISTRY_OFFICER', name: 'Ministry of Coal Officer', sub: null, pw: 'ministry123' },
  { username: 'cmpdi_officer', role: 'CMPDI_OFFICER', name: 'CMPDI Nodal Officer', sub: 'CMPDI', pw: 'cmpdi123' },
  { username: 'mcl_officer', role: 'SUBSIDIARY_OFFICER', name: 'MCL Officer (MCL only)', sub: 'MCL', pw: 'mcl123' },
  { username: 'ecl_officer', role: 'SUBSIDIARY_OFFICER', name: 'ECL Officer (ECL only)', sub: 'ECL', pw: 'ecl123' },
  { username: 'auditor_user', role: 'AUDITOR', name: 'Compliance Auditor', sub: null, pw: 'audit123' },
];

const CAN_READ_USERS = ['ADMIN', 'AUDITOR', 'MINISTRY_OFFICER'];
const CAN_WRITE_USERS = ['ADMIN'];

const NAV = [
  { id: 'overview', label: 'Overview', icon: Activity },
  { id: 'documents', label: 'Documents', icon: Database },
  { id: 'ask', label: 'Ask AI', icon: Sparkles },
  { id: 'analytics', label: 'Analytics', icon: BarChart3 },
  { id: 'discrepancies', label: 'Discrepancies', icon: AlertTriangle },
  { id: 'users', label: 'Users', icon: Users, needsRole: CAN_READ_USERS },
  { id: 'audit', label: 'Audit', icon: Shield },
];

const ALL_ROLES = ['ADMIN', 'MINISTRY_OFFICER', 'CMPDI_OFFICER', 'SUBSIDIARY_OFFICER', 'ANALYST', 'AUDITOR', 'VIEWER'];

const pct = (v) => (v === null || v === undefined ? null : `${v}%`);

// Minimal markdown renderer for report text (#/##/### headings, **bold**, - bullets)
function Markdown({ text }) {
  if (!text) return <span className="muted">No content.</span>;
  const lines = text.split('\n');
  const out = [];
  let bullets = [];
  const flush = (k) => {
    if (bullets.length) {
      out.push(<ul key={`u${k}`} style={{ margin: '6px 0 10px', paddingLeft: 20 }}>{bullets}</ul>);
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
  const cells = (s) => s.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());

  let i = 0;
  while (i < lines.length) {
    const raw = lines[i];
    const line = raw.trimEnd();
    if (!line.trim()) { flush(i); i++; continue; }

    // Markdown table block
    if (isTableRow(line) && i + 1 < lines.length && isSep(lines[i + 1])) {
      flush(i);
      const header = cells(line);
      const rows = [];
      i += 2;
      while (i < lines.length && isTableRow(lines[i]) && !isSep(lines[i])) { rows.push(cells(lines[i])); i++; }
      out.push(
        <div key={`t${i}`} className="table-wrap" style={{ margin: '8px 0 14px' }}>
          <table className="table">
            <thead><tr>{header.map((c, k) => <th key={k}>{inline(c)}</th>)}</tr></thead>
            <tbody>{rows.map((r, ri) => <tr key={ri}>{r.map((c, ci) => <td key={ci}>{inline(c)}</td>)}</tr>)}</tbody>
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
      const size = lvl <= 1 ? 17 : lvl === 2 ? 15 : 14;
      out.push(<div key={i} style={{ fontWeight: 650, fontSize: size, margin: '14px 0 6px', letterSpacing: '-0.01em' }}>{inline(h[2])}</div>);
    } else if (b) {
      bullets.push(<li key={i} style={{ marginBottom: 4 }}>{inline(b[1])}</li>);
    } else {
      flush(i);
      out.push(<p key={i} style={{ margin: '0 0 8px' }}>{inline(line)}</p>);
    }
    i++;
  }
  flush('end');
  return <div className="prose" style={{ whiteSpace: 'normal' }}>{out}</div>;
}

function StatusBadge({ status }) {
  const map = {
    classified: 'badge-green', validated: 'badge-green', flagged: 'badge-amber',
    failed: 'badge-red', uploaded: 'badge-accent',
  };
  return <span className={`badge ${map[status] || ''}`}>{status}</span>;
}

export default function App() {
  const [tab, setTab] = useState('overview');
  const [user, setUser] = useState(null);
  const [token, setToken] = useState('');
  const [authed, setAuthed] = useState(false);
  const [loginForm, setLoginForm] = useState({ username: '', password: '' });
  const [loginError, setLoginError] = useState('');
  const [loginBusy, setLoginBusy] = useState(false);

  const [documents, setDocuments] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [auditLogs, setAuditLogs] = useState([]);
  const [wordcloud, setWordcloud] = useState([]);
  const [topics, setTopics] = useState([]);
  const [trends, setTrends] = useState([]);
  const [discrepancies, setDiscrepancies] = useState(null);
  const [users, setUsers] = useState([]);
  const [newUser, setNewUser] = useState({ username: '', password: '', full_name: '', role: 'VIEWER', assigned_subsidiary: '' });
  const [userMsg, setUserMsg] = useState(null);

  const [selectedDoc, setSelectedDoc] = useState(null);
  const [selectedReport, setSelectedReport] = useState(null);

  const [uploadFile, setUploadFile] = useState(null);
  const [procStep, setProcStep] = useState(0);
  const [procMsg, setProcMsg] = useState(null);

  const [subFilter, setSubFilter] = useState('ALL');
  const [searchQuery, setSearchQuery] = useState('');

  const [ragQuery, setRagQuery] = useState('');
  const [ragResult, setRagResult] = useState(null);
  const [ragLoading, setRagLoading] = useState(false);
  const [ragScope, setRagScope] = useState('CROSS_DOCUMENT');

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
      const u = {
        username: data.user.username, role: data.user.role,
        sub: data.user.assigned_subsidiary, name: data.user.full_name,
      };
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
      setNewUser({ username: '', password: '', full_name: '', role: 'VIEWER', assigned_subsidiary: '' });
      setUserMsg(`Created ${data.username}`);
      loadAll();
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
      loadAll();
      setUploadFile(null);
      openDoc(procData.id);
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
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
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

  // ---- Login screen ----
  if (!authed) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
        <div style={{ width: '100%', maxWidth: 400 }}>
          <div className="row" style={{ gap: 11, justifyContent: 'center', marginBottom: 20 }}>
            <div className="brand-mark"><Layers size={19} /></div>
            <div>
              <div className="brand-title">MineIQ</div>
              <div className="small muted">CIL / CMPDI Document Intelligence</div>
            </div>
          </div>
          <div className="card card-pad-lg">
            <div className="section-title" style={{ marginBottom: 14 }}>Sign in</div>
            <form onSubmit={e => { e.preventDefault(); doLogin(loginForm.username.trim(), loginForm.password); }}>
              <div className="stack" style={{ gap: 10 }}>
                <input className="input" placeholder="Username" autoFocus value={loginForm.username}
                  onChange={e => setLoginForm({ ...loginForm, username: e.target.value })} />
                <input className="input" type="password" placeholder="Password" value={loginForm.password}
                  onChange={e => setLoginForm({ ...loginForm, password: e.target.value })} />
                <button className="btn btn-primary" type="submit" disabled={loginBusy || !loginForm.username || !loginForm.password}>
                  {loginBusy ? <RefreshCw size={15} className="spin" /> : <Lock size={15} />} Sign in
                </button>
              </div>
            </form>
            {loginError && <div className="small" style={{ color: 'var(--red)', marginTop: 10 }}>{loginError}</div>}

            <div style={{ borderTop: '1px solid var(--border)', margin: '18px 0 14px' }} />
            <div className="small muted" style={{ marginBottom: 10 }}>Or sign in with a demo role</div>
            <div className="stack" style={{ gap: 7 }}>
              {DEMO_USERS.map(u => (
                <button key={u.username} className="btn btn-ghost" style={{ justifyContent: 'space-between' }}
                  disabled={loginBusy} onClick={() => doLogin(u.username, u.pw)}>
                  <span>{u.name}</span>
                  <span className="badge badge-accent">{u.role}{u.sub ? ` · ${u.sub}` : ''}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="small faint" style={{ textAlign: 'center', marginTop: 14 }}>
            Access is scoped by role. Subsidiary officers see only their own data.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="app">
      {/* Header */}
      <header className="header">
        <div className="container">
          <div className="between" style={{ padding: '14px 0' }}>
            <div className="row" style={{ gap: 11 }}>
              <div className="brand-mark"><Layers size={19} /></div>
              <div>
                <div className="brand-title">MineIQ</div>
                <div className="small muted">CIL / CMPDI Document Intelligence</div>
              </div>
            </div>
            <div className="row" style={{ gap: 10 }}>
              <div style={{ textAlign: 'right' }}>
                <div className="small" style={{ fontWeight: 560 }}>{user?.name}</div>
                <div className="small faint">{user?.role}{user?.sub ? ` · ${user.sub}` : ''}</div>
              </div>
              <span className="badge badge-accent">{user?.role}{user?.sub ? ` · ${user.sub}` : ''}</span>
              <button className="btn btn-ghost btn-sm" onClick={logout}><LogOut size={14} /> Sign out</button>
            </div>
          </div>
          <nav className="nav">
            {NAV.filter(n => !n.needsRole || n.needsRole.includes(user.role)).map(n => {
              const Icon = n.icon;
              return (
                <button key={n.id} className={`tab ${tab === n.id || (n.id === 'documents' && tab === 'document') ? 'active' : ''}`} onClick={() => setTab(n.id)}>
                  <Icon size={15} /> {n.label}
                </button>
              );
            })}
          </nav>
        </div>
      </header>

      <main className="main">
        <div className="container">

          {/* OVERVIEW */}
          {tab === 'overview' && (
            <div className="stack">
              <div className="kpi-grid">
                <div className="kpi">
                  <div className="kpi-label">Total documents</div>
                  <div className="kpi-value">{metrics?.total_documents ?? documents.length}</div>
                  <div className="kpi-sub">Ingested in repository</div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Automation</div>
                  <div className="kpi-value">{pct(metrics?.automation_percentage) ?? '—'}</div>
                  <div className="kpi-sub">Processed without manual review</div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Extraction accuracy</div>
                  <div className="kpi-value" style={{ fontSize: accuracyDisplay === 'Not evaluated' ? 18 : 26 }}>{accuracyDisplay}</div>
                  <div className="kpi-sub">{metrics?.extraction_accuracy_detail ? `${metrics.extraction_accuracy_detail.fields_correct}/${metrics.extraction_accuracy_detail.fields_total} fields on benchmark` : 'Measured on labeled benchmark'}</div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Time reduction</div>
                  <div className="kpi-value">{pct(metrics?.time_reduction_percentage) ?? '—'}</div>
                  <div className="kpi-sub">vs assumed 180-min manual baseline</div>
                </div>
              </div>

              <div className="card">
                <div className="between" style={{ marginBottom: 14 }}>
                  <div className="section-title">Recent documents</div>
                  <button className="btn btn-ghost btn-sm" onClick={() => setTab('documents')}>View all <ChevronRight size={14} /></button>
                </div>
                <RecentTable docs={documents.slice(0, 6)} onOpen={openDoc} />
              </div>
            </div>
          )}

          {/* DOCUMENTS */}
          {tab === 'documents' && (
            <div className="stack">
              <div className="card">
                <div className="section-title" style={{ marginBottom: 12 }}>Upload &amp; process a document</div>
                <input type="file" id="file-in" style={{ display: 'none' }} onChange={e => setUploadFile(e.target.files[0])} />
                <label htmlFor="file-in" className="dropzone">
                  {uploadFile
                    ? <div className="row" style={{ justifyContent: 'center', gap: 8 }}><FileText size={18} /> <strong>{uploadFile.name}</strong> <span className="faint small">({(uploadFile.size / 1024).toFixed(1)} KB)</span></div>
                    : <span className="muted">Click to select a PDF, spreadsheet, image or text file</span>}
                </label>
                <div className="row" style={{ marginTop: 14, justifyContent: 'flex-end' }}>
                  <button className="btn btn-primary" disabled={!uploadFile} onClick={handleUpload}>
                    <Upload size={15} /> Start pipeline
                  </button>
                </div>
                {procMsg && (
                  <div style={{ marginTop: 16, borderTop: '1px solid var(--border)', paddingTop: 14 }}>
                    {['Upload & idempotency check', 'OCR + structured extraction', 'Validation & discrepancy check', 'LLM classification', 'Vector indexing & report'].map((s, i) => {
                      const n = i + 1;
                      return (
                        <div className="step" key={s}>
                          <div className={`step-dot ${procStep > n ? 'done' : procStep === n ? 'active' : ''}`}>
                            {procStep > n ? <CheckCircle2 size={13} /> : procStep === n ? <RefreshCw size={11} className="spin" /> : null}
                          </div>
                          <span className={procStep >= n ? '' : 'faint'}>{s}</span>
                        </div>
                      );
                    })}
                    <div className="small muted" style={{ marginTop: 8 }}>{procMsg}</div>
                  </div>
                )}
              </div>

              <div className="card">
                <div className="between wrap" style={{ marginBottom: 14, gap: 10 }}>
                  <div className="row" style={{ border: '1px solid var(--border-strong)', borderRadius: 8, padding: '0 10px', width: 280 }}>
                    <Search size={15} className="muted" />
                    <input className="input" style={{ border: 'none', boxShadow: 'none', padding: '8px 8px' }} placeholder="Search filename…" value={searchQuery} onChange={e => setSearchQuery(e.target.value)} />
                  </div>
                  <select className="select" style={{ width: 'auto' }} value={subFilter} onChange={e => setSubFilter(e.target.value)}>
                    {['ALL', 'MCL', 'ECL', 'BCCL', 'CCL', 'WCL', 'SECL', 'NCL', 'CMPDI'].map(s => <option key={s} value={s}>{s === 'ALL' ? 'All subsidiaries' : s}</option>)}
                  </select>
                </div>
                <div className="table-wrap">
                  <table className="table">
                    <thead><tr><th>Filename</th><th>Subsidiary</th><th>Type</th><th>Status</th><th>Uploaded</th><th></th></tr></thead>
                    <tbody>
                      {filtered.map(d => (
                        <tr key={d.id}>
                          <td style={{ fontWeight: 560 }}>{d.original_filename}</td>
                          <td>{d.subsidiary || '—'}</td>
                          <td className="muted">{d.doc_type || 'unclassified'}</td>
                          <td><StatusBadge status={d.status} /></td>
                          <td className="muted small">{d.uploaded_at ? new Date(d.uploaded_at).toLocaleDateString() : '—'}</td>
                          <td style={{ textAlign: 'right' }}><button className="btn btn-ghost btn-sm" onClick={() => openDoc(d.id)}>Open</button></td>
                        </tr>
                      ))}
                      {filtered.length === 0 && <tr><td colSpan={6} className="empty">No documents yet.</td></tr>}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* DOCUMENT DETAIL */}
          {tab === 'document' && selectedDoc && (
            <div className="stack">
              <button className="btn btn-ghost btn-sm" style={{ alignSelf: 'flex-start' }} onClick={() => setTab('documents')}><ArrowLeft size={14} /> Back</button>

              <div className="card">
                <div className="between wrap" style={{ gap: 10 }}>
                  <div>
                    <div className="row" style={{ gap: 9 }}>
                      <h2 style={{ fontSize: 19 }}>{selectedDoc.original_filename}</h2>
                      <span className="badge badge-accent">{selectedDoc.subsidiary || 'N/A'}</span>
                      <StatusBadge status={selectedDoc.status} />
                    </div>
                    <div className="small muted" style={{ marginTop: 5 }}>{selectedDoc.doc_type || 'unclassified'} · {selectedDoc.topic_area || 'general'} · {selectedDoc.source_type}</div>
                  </div>
                  {selectedReport && (
                    <div className="row" style={{ gap: 8 }}>
                      <button className="btn btn-ghost btn-sm" onClick={() => downloadReport(selectedDoc.id, 'pdf')}><Download size={14} /> PDF</button>
                      <button className="btn btn-primary btn-sm" onClick={() => downloadReport(selectedDoc.id, 'docx')}><Download size={14} /> DOCX</button>
                    </div>
                  )}
                </div>

                {selectedDoc.validations?.length > 0 && (
                  <div style={{ marginTop: 16, background: 'var(--amber-soft)', border: '1px solid #fde9b8', borderRadius: 10, padding: 14 }}>
                    <div className="row" style={{ color: 'var(--amber)', fontWeight: 600, marginBottom: 6, gap: 7 }}><AlertTriangle size={15} /> Validation alerts</div>
                    {selectedDoc.validations.map((v, i) => <div key={i} className="small" style={{ color: '#7c4a06' }}>• {v.message}</div>)}
                  </div>
                )}
              </div>

              {/* Structured records */}
              {selectedDoc.structured_records?.length > 0 && (
                <div className="card">
                  <div className="section-title" style={{ marginBottom: 12 }}>Structured records ({selectedDoc.structured_records.length})</div>
                  <div className="table-wrap">
                    <table className="table">
                      <thead><tr><th>Mine</th><th>Year</th><th>Target (MT)</th><th>Actual (MT)</th><th>Dispatch (MT)</th><th>OB (MCuM)</th></tr></thead>
                      <tbody>
                        {selectedDoc.structured_records.map((r, i) => (
                          <tr key={i}>
                            <td style={{ fontWeight: 560 }}>{r.mine_name || '—'}</td>
                            <td>{r.report_year ?? '—'}</td>
                            <td>{r.production_target_mt ?? '—'}</td>
                            <td>{r.actual_production_mt ?? '—'}</td>
                            <td>{r.dispatch_mt ?? '—'}</td>
                            <td>{r.overburden_mcum ?? '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Report */}
              <div className="card">
                <div className="between" style={{ marginBottom: 10 }}>
                  <div className="section-title"><FileText size={15} style={{ verticalAlign: -2, marginRight: 6 }} />Generated report</div>
                  {selectedReport && <span className="badge">AI draft · human review required</span>}
                </div>
                {selectedReport ? <Markdown text={selectedReport.report_text} /> : <div className="empty">Report is generating asynchronously. Reopen shortly.</div>}
              </div>

              {/* Raw text */}
              <div className="card">
                <div className="section-title" style={{ marginBottom: 10 }}>Extracted text</div>
                <pre style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 8, padding: 14, fontSize: 12.5, color: '#374151', overflowX: 'auto', maxHeight: 240, margin: 0, whiteSpace: 'pre-wrap' }}>
                  {selectedDoc.extracted_text || 'No text extracted.'}
                </pre>
              </div>
            </div>
          )}

          {/* ASK AI */}
          {tab === 'ask' && (
            <div className="stack" style={{ maxWidth: 860, margin: '0 auto', width: '100%' }}>
              <div className="card">
                <div className="row" style={{ gap: 9, marginBottom: 12 }}><Sparkles size={18} className="muted" /><h2 style={{ fontSize: 17 }}>Ask MineIQ</h2></div>
                <div className="small muted" style={{ marginBottom: 12 }}>Grounded answers with citations. Numeric questions are answered from structured records (SQL); results are scoped to your role.</div>
                <div className="row" style={{ gap: 6, marginBottom: 12 }}>
                  {[['CROSS_DOCUMENT', 'All authorized documents'], ['SELECTED', selectedDoc ? `Selected: ${selectedDoc.original_filename}` : 'Selected document']].map(([v, l]) => (
                    <button key={v} className={`btn btn-sm ${ragScope === v ? 'btn-primary' : 'btn-ghost'}`} disabled={v === 'SELECTED' && !selectedDoc} onClick={() => setRagScope(v)}>{l}</button>
                  ))}
                </div>
                <div className="row" style={{ gap: 8 }}>
                  <input className="input" placeholder="e.g. What was MCL production in 2025?" value={ragQuery} onChange={e => setRagQuery(e.target.value)} onKeyDown={e => e.key === 'Enter' && runRag()} />
                  <button className="btn btn-primary" onClick={runRag} disabled={ragLoading}>{ragLoading ? <RefreshCw size={15} className="spin" /> : <MessageSquare size={15} />} Ask</button>
                </div>
              </div>

              {ragResult && (
                <div className="card">
                  <div className="between" style={{ marginBottom: 12 }}>
                    <span className={`badge ${ragResult.grounded ? 'badge-green' : 'badge-amber'}`}>{ragResult.grounded ? 'Grounded' : 'Insufficient evidence'}</span>
                    <span className="small faint">{ragResult.mode === 'SQL_NUMERIC' ? `SQL · ${ragResult.intent}` : 'Vector retrieval'} · scope {ragResult.authorized_scope}</span>
                  </div>
                  <Markdown text={ragResult.answer} />

                  {ragResult.table?.length > 0 && (
                    <div className="table-wrap" style={{ marginTop: 14 }}>
                      <table className="table">
                        <thead><tr><th>Subsidiary</th><th>Year</th><th>Mines</th><th>Target (MT)</th><th>Actual (MT)</th></tr></thead>
                        <tbody>
                          {ragResult.table.map((r, i) => (
                            <tr key={i}><td>{r.subsidiary}</td><td>{r.report_year}</td><td>{r.mines}</td><td>{r.production_target_mt ?? '—'}</td><td>{r.actual_production_mt ?? '—'}</td></tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {ragResult.sources?.length > 0 && (
                    <div style={{ marginTop: 16 }}>
                      <div className="small muted" style={{ marginBottom: 8, textTransform: 'uppercase', letterSpacing: '.03em' }}>Sources ({ragResult.sources.length})</div>
                      <div className="grid-2">
                        {ragResult.sources.map((s, i) => (
                          <div key={i} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, background: 'var(--surface-2)' }}>
                            <div className="row between"><strong className="small">{s.filename}</strong>{s.subsidiary && <span className="badge">{s.subsidiary}</span>}</div>
                            {s.relevance_snippet && <div className="small muted" style={{ marginTop: 6, fontStyle: 'italic' }}>“{s.relevance_snippet}”</div>}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ANALYTICS */}
          {tab === 'analytics' && (
            <div className="stack">
              <div className="card">
                <div className="section-title" style={{ marginBottom: 14 }}>Corpus word cloud</div>
                {wordcloud.length ? (
                  <div className="cloud">
                    {wordcloud.map((w, i) => {
                      const max = wordcloud[0]?.value || 1;
                      const size = 12 + Math.round((w.value / max) * 16);
                      return <span key={w.text} className="chip" style={{ fontSize: size, color: i % 3 === 0 ? 'var(--accent)' : i % 3 === 1 ? 'var(--green)' : 'var(--text)' }}>{w.text} <span className="faint">{w.value}</span></span>;
                    })}
                  </div>
                ) : <div className="empty">No corpus terms yet.</div>}
              </div>

              <div className="grid-2">
                <div className="card">
                  <div className="section-title" style={{ marginBottom: 12 }}>Topic distribution</div>
                  {topics.filter(t => t.count > 0).length ? topics.filter(t => t.count > 0).map(t => (
                    <div className="between" key={t.topic} style={{ padding: '7px 0', borderBottom: '1px solid var(--border)' }}>
                      <span>{t.topic}</span><span className="badge badge-accent">{t.count}</span>
                    </div>
                  )) : <div className="empty">No topics yet.</div>}
                </div>
                <div className="card">
                  <div className="section-title" style={{ marginBottom: 12 }}>Trends by year</div>
                  {trends.length ? trends.map(tr => (
                    <div className="between" key={tr.year} style={{ padding: '7px 0', borderBottom: '1px solid var(--border)' }}>
                      <strong>{tr.year}</strong>
                      <span className="small muted">Prod {tr['Coal Production']} · Geo {tr['Geological Exploration']} · OB {tr['Overburden Removal']} · Safety {tr['Safety & Compliance']}</span>
                    </div>
                  )) : <div className="empty">Building trend timeline…</div>}
                </div>
              </div>
            </div>
          )}

          {/* DISCREPANCIES */}
          {tab === 'discrepancies' && (
            <div className="stack">
              <div className="kpi-grid">
                <div className="kpi"><div className="kpi-label">Conflicts found</div><div className="kpi-value">{discrepancies?.count ?? '—'}</div><div className="kpi-sub">Across authorized documents</div></div>
                <div className="kpi"><div className="kpi-label">Critical</div><div className="kpi-value" style={{ color: 'var(--red)' }}>{discrepancies?.by_severity?.critical ?? '—'}</div><div className="kpi-sub">≥ 10% divergence</div></div>
                <div className="kpi"><div className="kpi-label">High</div><div className="kpi-value" style={{ color: 'var(--amber)' }}>{discrepancies?.by_severity?.high ?? '—'}</div><div className="kpi-sub">≥ 3% divergence</div></div>
                <div className="kpi"><div className="kpi-label">Records scanned</div><div className="kpi-value">{discrepancies?.scanned_records ?? '—'}</div><div className="kpi-sub">Structured rows compared</div></div>
              </div>
              <div className="card">
                <div className="section-title" style={{ marginBottom: 12 }}>Cross-document discrepancies</div>
                {discrepancies?.discrepancies?.length ? (
                  <div className="stack" style={{ gap: 12 }}>
                    {discrepancies.discrepancies.map((d, i) => (
                      <div key={i} style={{ border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
                        <div className="between" style={{ marginBottom: 8 }}>
                          <div><strong>{d.subsidiary} · {d.mine_name} · {d.report_year}</strong> <span className="muted small">— {d.metric_label}</span></div>
                          <span className={`badge ${d.severity === 'critical' ? 'badge-red' : d.severity === 'high' ? 'badge-amber' : ''}`}>{d.severity} · {d.pct_difference}%</span>
                        </div>
                        <div className="grid-2">
                          <div style={{ background: 'var(--surface-2)', borderRadius: 8, padding: 10 }}>
                            <div className="small faint">Value A · {d.source_a.filename}</div><div style={{ fontSize: 18, fontWeight: 650 }}>{d.value_a}</div>
                          </div>
                          <div style={{ background: 'var(--surface-2)', borderRadius: 8, padding: 10 }}>
                            <div className="small faint">Value B · {d.source_b.filename}</div><div style={{ fontSize: 18, fontWeight: 650 }}>{d.value_b}</div>
                          </div>
                        </div>
                        <div className="small muted" style={{ marginTop: 8 }}>Difference {d.difference} · status {d.status.replace('_', ' ')}</div>
                      </div>
                    ))}
                  </div>
                ) : <div className="empty">No discrepancies detected in your authorized scope.</div>}
              </div>
            </div>
          )}

          {/* USERS */}
          {tab === 'users' && (
            <div className="stack">
              {CAN_WRITE_USERS.includes(user.role) && (
                <div className="card">
                  <div className="section-title" style={{ marginBottom: 12 }}>Add user</div>
                  <div className="grid-3" style={{ gap: 10 }}>
                    <input className="input" placeholder="Username" value={newUser.username} onChange={e => setNewUser({ ...newUser, username: e.target.value })} />
                    <input className="input" placeholder="Full name" value={newUser.full_name} onChange={e => setNewUser({ ...newUser, full_name: e.target.value })} />
                    <input className="input" type="password" placeholder="Password (min 6)" value={newUser.password} onChange={e => setNewUser({ ...newUser, password: e.target.value })} />
                    <select className="select" value={newUser.role} onChange={e => setNewUser({ ...newUser, role: e.target.value })}>
                      {ALL_ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                    </select>
                    <select className="select" value={newUser.assigned_subsidiary} onChange={e => setNewUser({ ...newUser, assigned_subsidiary: e.target.value })}>
                      <option value="">No subsidiary scope</option>
                      {['MCL', 'ECL', 'BCCL', 'CCL', 'WCL', 'SECL', 'NCL', 'CMPDI'].map(s => <option key={s} value={s}>{s}</option>)}
                    </select>
                    <button className="btn btn-primary" onClick={createUser} disabled={!newUser.username || !newUser.password || !newUser.full_name}><Plus size={15} /> Create</button>
                  </div>
                  {userMsg && <div className="small" style={{ marginTop: 10, color: userMsg.startsWith('Created') ? 'var(--green)' : 'var(--red)' }}>{userMsg}</div>}
                </div>
              )}
              <div className="card">
                <div className="section-title" style={{ marginBottom: 12 }}>Users &amp; roles ({users.length})</div>
                <div className="table-wrap">
                  <table className="table">
                    <thead><tr><th>Username</th><th>Name</th><th>Role</th><th>Scope</th><th>Status</th><th>Last login</th>{CAN_WRITE_USERS.includes(user.role) && <th></th>}</tr></thead>
                    <tbody>
                      {users.map(u => (
                        <tr key={u.id}>
                          <td style={{ fontWeight: 560 }}>{u.username}</td>
                          <td className="muted">{u.full_name}</td>
                          <td><span className="badge badge-accent">{u.role}</span></td>
                          <td>{u.assigned_subsidiary || '—'}</td>
                          <td><span className={`badge ${u.is_active ? 'badge-green' : 'badge-red'}`}>{u.is_active ? 'active' : 'disabled'}</span></td>
                          <td className="muted small">{u.last_login ? new Date(u.last_login).toLocaleString() : 'never'}</td>
                          {CAN_WRITE_USERS.includes(user.role) && (
                            <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                              <button className="btn btn-ghost btn-sm" onClick={() => toggleUser(u)}>{u.is_active ? 'Disable' : 'Enable'}</button>
                              {u.username !== user.username && <button className="btn btn-ghost btn-sm" style={{ marginLeft: 6, color: 'var(--red)' }} onClick={() => removeUser(u)}><Trash2 size={13} /></button>}
                            </td>
                          )}
                        </tr>
                      ))}
                      {users.length === 0 && <tr><td colSpan={7} className="empty">No users visible.</td></tr>}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* AUDIT */}
          {tab === 'audit' && (
            <div className="stack">
              <div className="kpi-grid">
                <div className="kpi"><div className="kpi-label">Documents processed</div><div className="kpi-value">{metrics?.processed_documents ?? '—'}</div><div className="kpi-sub">Reached classified state</div></div>
                <div className="kpi"><div className="kpi-label">Reports generated</div><div className="kpi-value">{metrics?.reports_generated ?? '—'}</div><div className="kpi-sub">Stored & indexed</div></div>
                <div className="kpi"><div className="kpi-label">Avg processing</div><div className="kpi-value">{metrics?.average_processing_time_sec ? `${metrics.average_processing_time_sec}s` : '—'}</div><div className="kpi-sub">Per document</div></div>
                <div className="kpi"><div className="kpi-label">Access blocks</div><div className="kpi-value" style={{ color: 'var(--red)' }}>{auditLogs.filter(l => l.result === 'DENIED' || (l.action || '').includes('ISOLATION')).length}</div><div className="kpi-sub">RBAC / isolation stops</div></div>
              </div>
              <div className="card">
                <div className="section-title" style={{ marginBottom: 12 }}>Audit trail</div>
                <div className="table-wrap">
                  <table className="table">
                    <thead><tr><th>Time</th><th>User</th><th>Role</th><th>Action</th><th>Service</th><th>Result</th></tr></thead>
                    <tbody>
                      {auditLogs.slice(0, 40).map(l => (
                        <tr key={l.id}>
                          <td className="muted small">{l.timestamp ? new Date(l.timestamp).toLocaleString() : '—'}</td>
                          <td style={{ fontWeight: 560 }}>{l.user_id}</td>
                          <td className="muted">{l.user_role}</td>
                          <td>{l.action}</td>
                          <td className="muted">{l.service}</td>
                          <td><span className={`badge ${['SUCCESS', 'APPROVED'].includes(l.result) ? 'badge-green' : ['DENIED', 'PURGED'].includes(l.result) ? 'badge-red' : 'badge-amber'}`}>{l.result}</span></td>
                        </tr>
                      ))}
                      {auditLogs.length === 0 && <tr><td colSpan={6} className="empty">No audit events yet.</td></tr>}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

        </div>
      </main>
    </div>
  );
}

function RecentTable({ docs, onOpen }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead><tr><th>Filename</th><th>Subsidiary</th><th>Type</th><th>Status</th><th></th></tr></thead>
        <tbody>
          {docs.map(d => (
            <tr key={d.id}>
              <td style={{ fontWeight: 560 }}>{d.original_filename}</td>
              <td>{d.subsidiary || '—'}</td>
              <td className="muted">{d.doc_type || 'unclassified'}</td>
              <td><StatusBadge status={d.status} /></td>
              <td style={{ textAlign: 'right' }}><button className="btn btn-ghost btn-sm" onClick={() => onOpen(d.id)}>Open</button></td>
            </tr>
          ))}
          {docs.length === 0 && <tr><td colSpan={5} className="empty">No documents yet — upload one to begin.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
