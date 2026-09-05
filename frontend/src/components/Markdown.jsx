import React from 'react';

export default function Markdown({ text }) {
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
            <tbody>{rows.map((r, ri) => <tr key={ri}>{r.map((c, ci) => <td key={ci} className={/^[0-9.,\-+%]+$/.test(c) ? 'cell-num' : ''}>{inline(c)}</td>)}</tr>)}</tbody>
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
