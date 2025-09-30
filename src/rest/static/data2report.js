const form = document.getElementById('reportForm');
const configEl = document.getElementById('config');
const lintChips = document.getElementById('lintChips');
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('file');
const bar = document.getElementById('bar');
const statusEl = document.getElementById('status');
const resultBox = document.getElementById('result');
const resultPre = document.getElementById('resultPre');

const btnFormat = document.getElementById('btnFormat');
const btnExample = document.getElementById('btnExample');
const btnClear = document.getElementById('btnClear');
const btnCopy = document.getElementById('btnCopy');
const btnDownload = document.getElementById('btnDownload');
const savedSel = document.getElementById('savedReports');
const btnLoad = document.getElementById('btnLoad');
const btnSave = document.getElementById('btnSave');
const runBtn = document.querySelector('button.btn[type="submit"]');
const btnStop = document.getElementById('btnStop');

let currentRun = {reportId: null, runId: null};

function setStatus(msg) {
    statusEl.textContent = msg;
}

function setProgress(pct) {
    bar.style.width = pct + '%';
}

function resetRunUI() {
  if (typeof es !== 'undefined' && es) {
    try { es.close(); } catch {}
    es = null;
  }

  setProgress(0);
  setStatus('Starting...');

  const pane = document.getElementById('progressPane');
  if (pane) pane.innerHTML = '';

  resultPre.textContent = '';
  const container = resultPre.parentElement;
  if (container) {
    [...container.querySelectorAll('a.__open_report_link')].forEach(n => n.remove());
  }

  resultBox.hidden = true;

  currentRun = { reportId: null, runId: null };
}

function chip(text, tone = 'ok') {
    const div = document.createElement('div');
    div.className = 'chip';
    div.style.borderColor = tone === 'err' ? '#4a1f26' : tone === 'warn' ? '#4a3b1f' : '#214a40';
    div.style.background = tone === 'err' ? '#2a0f14' : tone === 'warn' ? '#2a1f0f' : '#0f1f2a';
    div.style.color = tone === 'err' ? '#ffb4c0' : tone === 'warn' ? '#ffd49a' : '#a7ffef';
    div.textContent = text;
    return div;
}

function lintJSON(str) {
    lintChips.innerHTML = '';
    if (!str.trim()) return;
    try {
        const parsed = JSON.parse(str);
        lintChips.appendChild(chip('Valid JSON', 'ok'));
        // Lightweight schema hints (non-blocking)
        if (!parsed.id) lintChips.appendChild(chip('Missing id', 'warn'));
        if (!parsed.llm) lintChips.appendChild(chip('Missing llm section', 'warn'));
        if (parsed.report && parsed.report.incremental === true && parsed.report.max_workers !== 1) {
            lintChips.appendChild(chip('incremental=true requires max_workers=1', 'warn'));
        }
        return true;
    } catch (e) {
        lintChips.appendChild(chip('Invalid JSON: ' + e.message, 'err'));
        return false;
    }
}

configEl.addEventListener('input', () => lintJSON(configEl.value));
btnFormat.addEventListener('click', () => {
    try {
        const obj = JSON.parse(configEl.value);
        configEl.value = JSON.stringify(obj, null, 2);
        lintJSON(configEl.value);
    } catch (e) {
        alert('Configuration must be valid JSON.');
    }
});
btnExample.addEventListener('click', async () => {
  try {
    const res = await fetch('/example-config');
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `HTTP ${res.status}`);
    }
    const example = await res.json();
    configEl.value = JSON.stringify(example, null, 2);
    await validateViaApi();
  } catch (e) {
    alert('Failed to load example configuration: ' + (e?.message || e));
  }
});
btnClear.addEventListener('click', () => {
    configEl.value = '';
    fileInput.value = '';
    lintChips.innerHTML = '';
    setProgress(0);
    setStatus('Idle');
    resultBox.hidden = true;
    resultPre.textContent = '';
});


btnStop.addEventListener('click', async () => {
    if (!currentRun.reportId || !currentRun.runId) {
        return alert('No running job to stop.');
    }
    try {
        await fetch('/stop', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({report_id: currentRun.reportId, run_id: currentRun.runId}),
        });
        setStatus('Stop requested');
        if (es) es.close();   // stop receiving SSE
    } catch (e) {
        alert('Failed to request stop: ' + (e?.message || e));
    }
});

// Drag & drop
const openPicker = () => fileInput.click();
dropzone.addEventListener('click', openPicker);
dropzone.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openPicker();
    }
});
dropzone.addEventListener('dragover', e => {
    e.preventDefault();
    dropzone.classList.add('dragover');
});
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
dropzone.addEventListener('drop', e => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    if (e.dataTransfer.files.length) {
        fileInput.files = e.dataTransfer.files;
        setStatus('File attached: ' + e.dataTransfer.files[0].name);
    }
});
fileInput.addEventListener('change', () => {
    if (fileInput.files.length) setStatus('File attached: ' + fileInput.files[0].name);
});

let es;

function makeRunId() {
    const d = new Date();
    return d.toISOString().slice(0, 10) + '-' + Math.random().toString(36).slice(2, 8);
}

function subscribeProgress(reportId, runId) {
    if (es) { try { es.close(); } catch {} }
  es = new EventSource(`/progress/stream?report_id=${encodeURIComponent(reportId)}&run_id=${encodeURIComponent(runId)}`);

  let totalIn = 0, totalOut = 0;

  es.addEventListener('hello', () => {
    // optional: mark that the stream connected for this run
    setStatus(`Connected for ${reportId}/${runId}...`);
  });
    es.addEventListener('progress', (e) => {
        const evt = JSON.parse(e.data);
        totalIn += evt.usage?.input_tokens ?? 0;
        totalOut += evt.usage?.output_tokens ?? 0;
        const total = evt.total_chunks || 1;
        const done = evt.completed_chunks || evt.chunk_index || 1;
        const pct = Math.max(5, Math.min(99, Math.floor((done / total) * 100)));
        setProgress(pct);
        document.getElementById('progressPane').innerHTML =
            `Chunk ${done}/${total} done<br>` +
            `Tokens in: ${totalIn} &nbsp; Tokens out: ${totalOut}<br>` +
            `Last chunk duration: ${evt.duration_seconds ?? 0}s`;
    });
    es.onerror = () => {
    };
}

// Submit with progress + client-side JSON validation + optional numeric params
form.addEventListener('submit', async (event) => {
    event.preventDefault();
    resetRunUI();
    runBtn.disabled = true;
    try {
    const ok = await validateViaApi(true);
    if (!ok) { alert('Fix configuration errors first'); return; }

    const cfg = JSON.parse(configEl.value);
    if (!cfg.id) { alert("Configuration must include 'id'"); return; }
    const runId = cfg.run_id || makeRunId();
    currentRun = { reportId: cfg.id, runId: runId };

    // subscribe before posting to catch early events
    subscribeProgress(cfg.id, runId);
    setStatus('Uploading...');
    setProgress(5);

    const fd = new FormData(form);
    fd.set('config', configEl.value);
    fd.set('run_id', runId);

    const res = await fetch(form.action, { method: 'POST', body: fd });

    setProgress(100);
    setStatus(res.ok ? 'Completed' : 'Failed');
    resultBox.hidden = false;

    // JSON-first + single link
    const container = resultPre.parentElement;
    [...container.querySelectorAll('a.__open_report_link')].forEach(n => n.remove());
    try {
      const payload = await res.json();
      resultPre.textContent = JSON.stringify(payload, null, 2);
      if (payload.report_id && payload.run_id) {
        const a = document.createElement('a');
        a.className = '__open_report_link';
        a.href = `/report?id=${encodeURIComponent(payload.report_id)}&run_id=${encodeURIComponent(payload.run_id)}`;
        a.textContent = 'Open final report';
        a.target = '_blank';
        container.appendChild(a);
      }
    } catch {
      resultPre.textContent = await res.text();
    }
  } catch (e) {
    setStatus('Network error');
    alert('Failed to submit: ' + (e?.message || e));
  } finally {
    setTimeout(() => setProgress(0), 800);
    // keep SSE open to show “Completed” progress; close after a grace period
    setTimeout(() => { if (es) es.close(); }, 30000);
    runBtn.disabled = false;
  }
});

// Copy / Download
btnCopy.addEventListener('click', async () => {
    try {
        await navigator.clipboard.writeText(resultPre.textContent || '');
        setStatus('Copied to clipboard');
    } catch {
        setStatus('Clipboard not available');
    }
});
btnDownload.addEventListener('click', () => {
    const blob = new Blob([resultPre.textContent || ''], {type: 'text/plain;charset=utf-8'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'report.txt';
    a.click();
    URL.revokeObjectURL(a.href);
});

async function refreshSavedReports() {
    try {
        const res = await fetch('/reports');
        const ids = await res.json(); // ["test_report", ...]
        savedSel.innerHTML = '';
        const ph = document.createElement('option');
        ph.value = '';
        ph.textContent = '— Select report —';
        savedSel.appendChild(ph);
        ids.forEach(id => {
            const opt = document.createElement('option');
            opt.value = id;
            opt.textContent = id;
            savedSel.appendChild(opt);
        });
    } catch (e) {
        console.warn('Failed to load reports list', e);
    }
}

btnLoad.addEventListener('click', async () => {
    const id = savedSel.value;
    if (!id) return alert('Pick a report to load');
    try {
        const res = await fetch(`/report-config?id=${encodeURIComponent(id)}`);
        if (!res.ok) throw new Error(await res.text());
        const cfg = await res.json();
        configEl.value = JSON.stringify(cfg, null, 2);
        await validateViaApi(); // reflect chips and enable/disable run
    } catch (e) {
        alert('Failed to load configuration: ' + e.message);
    }
});

btnSave.addEventListener('click', async () => {
    const ok = await validateViaApi(true); // strict
    if (!ok) return;

    try {
        const cfg = JSON.parse(configEl.value);
        const res = await fetch('/save-report-config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(cfg),
        });
        const payload = await res.json();
        if (!res.ok) throw new Error((payload && payload.errors) ? payload.errors.join('; ') : JSON.stringify(payload));
        setStatus(`Saved: ${payload.id}`);
        await refreshSavedReports();
        savedSel.value = cfg.id;
    } catch (e) {
        alert('Failed to save configuration: ' + e.message);
    }
});

async function validateViaApi(strict = false) {
    let cfg;
    try {
        if (configEl.value.length === 0) {
            showChips(['Empty'], 'warn');
            return true;
        }
        cfg = JSON.parse(configEl.value);
    } catch (e) {
        showChips(['Invalid JSON: ' + e.message], 'err');
        if (strict) return false; else return true;
    }

    const res = await fetch('/validate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(cfg),
    });
    const errors = await res.json(); // array of strings
    lintChips.innerHTML = '';
    if (errors.length) {
        errors.forEach(e => lintChips.appendChild(chip(e, 'err')));
        runBtn.disabled = true;
        return false;
    } else {
        lintChips.appendChild(chip('Valid configuration', 'ok'));
        runBtn.disabled = false;
        return true;
    }
}

function showChips(msgs, tone) {
    lintChips.innerHTML = '';
    msgs.forEach(m => lintChips.appendChild(chip(m, tone)));
}

// live validate with debounce
let vTimer;
configEl.addEventListener('input', () => {
    clearTimeout(vTimer);
    vTimer = setTimeout(() => validateViaApi().catch(() => {
    }), 250);
});

document.addEventListener('DOMContentLoaded', () => {
    refreshSavedReports();
    validateViaApi().catch(() => {
    });
});
