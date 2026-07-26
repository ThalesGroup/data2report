function _splitCsvLine(line) {
  const cells = []; let cur = ''; let inQ = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQ && line[i + 1] === '"') { cur += '"'; i++; }
      else inQ = !inQ;
    } else if (ch === ',' && !inQ) {
      cells.push(cur); cur = '';
    } else { cur += ch; }
  }
  cells.push(cur);
  return cells;
}

function parseCsv(text) {
  const lines = text.split('\n');
  const rows = [];
  let headers = null;
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    const cells = _splitCsvLine(line);
    if (!headers) { headers = cells; continue; }
    const row = {};
    headers.forEach((h, i) => { row[h] = cells[i] ?? ''; });
    rows.push(row);
  }
  return headers ? { columns: headers, rows } : null;
}

function parseReportContent(text) {
  const lines = text.split('\n').map(l => l.trim()).filter(l => l.length > 0);
  if (!lines.length) return { format: null, columns: [], rows: [] };

  // Try JSONL: first 5 non-empty lines all parse as objects
  const sample = lines.slice(0, 5).map(l => { try { return JSON.parse(l); } catch { return null; } });
  if (sample.every(r => r !== null && typeof r === 'object')) {
    const rows = lines.map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
    const columns = [...new Set(rows.flatMap(r => Object.keys(r)))];
    return { format: 'jsonl', columns, rows };
  }

  // Try CSV: must have more than one column
  const csv = parseCsv(text);
  if (csv && csv.columns.length > 1) {
    return { format: 'csv', columns: csv.columns, rows: csv.rows };
  }

  // Fallback: plain text, one line per row
  return { format: 'text', columns: ['line'], rows: lines.map(l => ({ line: l })) };
}

if (typeof module !== 'undefined') module.exports = { parseCsv, parseReportContent, _splitCsvLine };
