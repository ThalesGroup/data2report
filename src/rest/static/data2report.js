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
    updateClearButtonState();
}

function setProgress(pct) {
    bar.style.width = pct + '%';
    updateClearButtonState();
}

function setRunningState(running) {
  runBtn.disabled = running ? true : runBtn.disabled;
  btnStop.disabled = !running;
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
  setRunningState(false);
  updateClearButtonState();
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
        setDirty(configEl.value !== pristineConfigText);
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
    pristineConfigText = configEl.value;
    setDirty(false);
    await validateViaApi();
  } catch (e) {
    alert('Failed to load example configuration: ' + (e?.message || e));
  }
});
btnClear.addEventListener('click', () => {
    setProgress(0);
    setStatus('Idle');

    const pane = document.getElementById('progressPane');
    if (pane) pane.innerHTML = '';

    resultPre.textContent = '';
    const container = resultPre.parentElement;
    if (container) {
    [...container.querySelectorAll('a.__open_report_link')].forEach(n => n.remove());
    }
    resultBox.hidden = true;

    setRunningState(false);
    updateClearButtonState();
});


btnStop.addEventListener('click', async () => {
    if (!currentRun.reportId || !currentRun.runId) {
        return alert('No running job to stop.');
    }
    btnStop.disabled = true; // prevent multiple clicks
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
        hasFile = true;
        updateRunButtonState();
        setStatus('File attached: ' + e.dataTransfer.files[0].name);
    }
});
fileInput.addEventListener('change', () => {
    hasFile = fileInput.files && fileInput.files.length > 0;
    updateRunButtonState();
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
    if (!isConfigValid) return alert('Configuration is invalid.');
    if (!hasFile) return alert('Please choose a data file.');
    try {
    const ok = await validateViaApi(true);
    if (!ok) { alert('Fix configuration errors first'); return; }

    const cfg = JSON.parse(configEl.value);
    if (!cfg.id) { alert("Configuration must include 'id'"); return; }
    const runId = cfg.run_id || makeRunId();
    currentRun = { reportId: cfg.id, runId: runId };
    setRunningState(true);

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
      updateClearButtonState();
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
    setRunningState(false);
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
    if (isDirty) {
    const ok = confirm('You have unsaved changes. Loading a configuration will discard them. Continue?');
    if (!ok) return;
    }
    const id = savedSel.value;
    if (!id) return alert('Pick a report to load');
    try {
        const res = await fetch(`/report-config?id=${encodeURIComponent(id)}`);
        if (!res.ok) throw new Error(await res.text());
        const cfg = await res.json();
        configEl.value = JSON.stringify(cfg, null, 2);
        pristineConfigText = configEl.value;
        setDirty(false);
        await validateViaApi(); // reflect chips and enable/disable run
    } catch (e) {
        alert('Failed to load configuration: ' + e.message);
    }
});

window.addEventListener('beforeunload', (e) => {
  if (!isDirty) return;
  e.preventDefault();
  e.returnValue = ''; // required for Chrome to show the prompt
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
        pristineConfigText = configEl.value;
        setDirty(false);

    } catch (e) {
        alert('Failed to save configuration: ' + e.message);
    }
});


let pristineConfigText = "";   // last loaded or saved JSON text
let isDirty = false;

function setDirty(nextDirty) {
  isDirty = !!nextDirty;
  const chipId = "__dirty_chip";
  const has = document.getElementById(chipId);
  if (isDirty) {
    if (!has) {
      const mark = document.createElement('div');
      mark.id = chipId;
      mark.className = 'chip';
      mark.textContent = 'Edited';
      document.getElementById('lintChips').prepend(mark);
    }
  } else if (has) {
    has.remove();
  }
  // Save button enabled only when dirty
  btnSave.disabled = !isDirty;
}

let isConfigValid = false;
let hasFile = false;

function updateRunButtonState() {
  runBtn.disabled = !(isConfigValid && hasFile);
}

function hasClearableLog() {
  const pane = document.getElementById('progressPane');
  const hasProgressPane = !!(pane && pane.textContent.trim().length);

  const hasResponse = !!(resultPre.textContent && resultPre.textContent.trim().length);
  const hasLink = !!(resultPre.parentElement && resultPre.parentElement.querySelector('a.__open_report_link'));

  const barNonZero = !!(bar.style.width && bar.style.width !== '0%');
  const statusNotIdle = !!(statusEl.textContent && statusEl.textContent !== 'Idle');

  return hasProgressPane || hasResponse || hasLink || barNonZero || statusNotIdle;
}

function updateClearButtonState() {
  btnClear.disabled = !hasClearableLog();
}

async function validateViaApi(strict = false) {
    let cfg;
    try {
        if (configEl.value.length === 0) {
            showChips(['Empty'], 'warn');
            isConfigValid = true;
            updateRunButtonState();
            return true;
        }
        cfg = JSON.parse(configEl.value);
    } catch (e) {
        showChips(['Invalid JSON: ' + e.message], 'err');
        isConfigValid = !strict;
        updateRunButtonState();
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
        isConfigValid = false;
        runBtn.disabled = true;
        return false;
    } else {
        lintChips.appendChild(chip('Valid configuration', 'ok'));
        isConfigValid = true;
        runBtn.disabled = false;
        return true;
    }
    updateRunButtonState();
    return isConfigValid;
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
    setDirty(configEl.value !== pristineConfigText);
});

btnSave.disabled = true;
document.addEventListener('DOMContentLoaded', () => {
    refreshSavedReports();
    pristineConfigText = configEl.value || '';
    setDirty(false);
    hasFile = fileInput.files && fileInput.files.length > 0;
    isConfigValid = false;
    updateRunButtonState();
    validateViaApi().catch(() => {
    });
    setTimeout(() => { btnSave.disabled = !isDirty; }, 0);
    btnStop.disabled = true;
    updateClearButtonState();
});
