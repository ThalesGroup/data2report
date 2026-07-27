const HISTORY_KEY  = 'd2r_history';
const THEME_KEY    = 'd2r_theme';
const HISTORY_MAX  = 10;
let _toastId = 0;

// ── Alpine component ──────────────────────────────────────────────────────
window.appData = function () {
  return {
    theme: 'light',

    // Tabs
    activeTab: 'config',
    selectedHistoryIdx: null,

    // Config
    cfg: emptyCfg(),
    pristineCfg: '',
    isDirty: false,
    fieldErrors: {},
    savedReports: [],
    selectedSavedReport: '',
    modelOptions: MODEL_OPTIONS,

    // File
    hasFile: false,
    fileName: '',
    fileSize: '',
    isDragging: false,
    selectedFile: null,
    maxRecords: '',
    force: false,
    runName: '',

    // Run
    isRunning: false,
    statusText: 'Ready',
    progress: 0,
    hasClearable: false,
    currentRun: { reportId: null, runId: null },

    // Chunks
    chunks: [],
    totalTokensIn: 0,
    totalTokensOut: 0,
    totalElapsedSec: null,

    // Report table
    reportRows: [],
    reportColumns: [],
    reportFormat: null,
    reportFilter: '',
    reportPage: 1,
    reportPageSize: 25,
    reportColFilters: {},   // { colName: filterString }
    reportSort: { col: null, dir: 1 }, // dir: 1=asc, -1=desc
    reportColWidths: {},    // { colName: widthPx }
    _resizeState: null,     // { col, startX, startW }

    // History
    history: [],

    // Compare
    compareAvailable: false,
    compareSelected: [],   // up to 2 history indices
    compareLoading: false,
    compareResult: null,   // { text, usage, labelA, labelB } | null
    compareError: null,

    // Tools
    availableTools: [],

    // Toasts
    toasts: [],

    _es: null,
    _vTimer: null,
    _crawlTimer: null,
    _elapsedTimer: null,
    elapsedSec: 0,

    // ── Computed ────────────────────────────────────────────────────────

    get canRun() {
      return this.hasFile && !this.isRunning
        && Object.keys(this.fieldErrors).length === 0
        && this.cfg.id.trim() && this.cfg.name.trim()
        && this.cfg.llm.model_id && this.cfg.llm.system_prompt.trim();
    },

    get filteredReportRows() {
      let rows = this.reportRows;
      // Global filter
      if (this.reportFilter.trim()) {
        const q = this.reportFilter.toLowerCase();
        rows = rows.filter(row => Object.values(row).some(v => String(v).toLowerCase().includes(q)));
      }
      // Per-column filters
      for (const [col, val] of Object.entries(this.reportColFilters)) {
        if (!val.trim()) continue;
        const q = val.toLowerCase();
        rows = rows.filter(row => String(row[col] ?? '').toLowerCase().includes(q));
      }
      // Sort
      if (this.reportSort.col !== null) {
        const { col, dir } = this.reportSort;
        rows = [...rows].sort((a, b) => {
          const av = a[col] ?? '', bv = b[col] ?? '';
          const an = Number(av), bn = Number(bv);
          const cmp = (!isNaN(an) && !isNaN(bn)) ? an - bn : String(av).localeCompare(String(bv));
          return cmp * dir;
        });
      }
      return rows;
    },

    get reportPageCount() {
      return Math.max(1, Math.ceil(this.filteredReportRows.length / this.reportPageSize));
    },

    get pagedReportRows() {
      const start = (this.reportPage - 1) * this.reportPageSize;
      return this.filteredReportRows.slice(start, start + this.reportPageSize);
    },

    sortBy(col) {
      if (this.reportSort.col === col) {
        this.reportSort = { col, dir: this.reportSort.dir * -1 };
      } else {
        this.reportSort = { col, dir: 1 };
      }
      this.reportPage = 1;
    },

    startResize(col, e) {
      e.preventDefault();
      const th = e.target.closest('th');
      this._resizeState = { col, startX: e.clientX, startW: th.offsetWidth };
      const onMove = (ev) => {
        if (!this._resizeState) return;
        const delta = ev.clientX - this._resizeState.startX;
        this.reportColWidths = { ...this.reportColWidths, [col]: Math.max(40, this._resizeState.startW + delta) };
      };
      const onUp = () => {
        this._resizeState = null;
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
      };
      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', onUp);
    },

    get completedChunks() {
      return this.chunks.filter(c => c.status === 'done' || c.status === 'error').length;
    },

    get totalChunks() {
      if (!this.chunks.length) return 0;
      return this.chunks[this.chunks.length - 1].total ?? this.chunks.length;
    },

    get selectedHistoryEntry() {
      if (this.selectedHistoryIdx === null) return null;
      return this.history[this.selectedHistoryIdx] ?? null;
    },

    get compareMismatch() {
      if (this.compareSelected.length !== 2) return null;
      const [ia, ib] = this.compareSelected;
      const a = this.history[ia], b = this.history[ib];
      if (!a || !b) return null;
      if (a.reportId !== b.reportId) return `Different report IDs (${a.reportId} vs ${b.reportId})`;
      if (a.fileName && b.fileName && a.fileName !== b.fileName) return `Different files (${a.fileName} vs ${b.fileName})`;
      return null;
    },

    // ── Lifecycle ───────────────────────────────────────────────────────

    init() {
      this.applyTheme(localStorage.getItem(THEME_KEY) || 'light');
      this.restoreHistory();
      if (this.history.length > 0) {
        this.selectedHistoryIdx = 0;
        this.fetchReportContent(this.history[0].reportId, this.history[0].runId);
      }
      this.refreshSavedReports();
      this.fetchAvailableTools();
      this.fetchCompareAvailable();
      this.pristineCfg = JSON.stringify(cfgToJson(this.cfg));
      window.addEventListener('beforeunload', (e) => {
        if (this.isDirty) { e.preventDefault(); e.returnValue = ''; }
      });
    },

    // ── Theme ───────────────────────────────────────────────────────────

    toggleTheme() { this.applyTheme(this.theme === 'dark' ? 'light' : 'dark'); },

    applyTheme(t) {
      this.theme = t;
      localStorage.setItem(THEME_KEY, t);
      document.documentElement.classList.toggle('dark', t === 'dark');
    },

    // ── Toast ───────────────────────────────────────────────────────────

    toast(message, tone = 'ok', duration = 3000) {
      const id = ++_toastId;
      this.toasts.push({ id, message, tone });
      setTimeout(() => { this.toasts = this.toasts.filter(t => t.id !== id); }, duration);
    },

    toastClass(tone) {
      return 'toast toast-' + ({ ok: 'ok', warn: 'warn', err: 'err' }[tone] ?? 'ok');
    },

    // ── Dirty tracking ──────────────────────────────────────────────────

    markDirty() {
      this.isDirty = JSON.stringify(cfgToJson(this.cfg)) !== this.pristineCfg;
      this._scheduleValidate();
    },

    // ── Textarea auto-resize ────────────────────────────────────────────

    autoResize(event) {
      const el = event.target ?? event;
      el.style.height = 'auto';
      el.style.height = el.scrollHeight + 'px';
    },

    // ── Field validation ────────────────────────────────────────────────

    fieldErr(path) { return this.fieldErrors[path] ?? null; },

    _validateFields() {
      const e = {};
      const c = this.cfg;
      if (!c.id.trim())                             e['id'] = 'Required';
      else if (/[/\\:*?"<>|]/.test(c.id))           e['id'] = 'Contains invalid characters';
      if (!c.name.trim())                            e['name'] = 'Required';
      if (!c.llm.model_id)                           e['llm.model_id'] = 'Select or enter a model';
      if (!c.llm.system_prompt.trim())               e['llm.system_prompt'] = 'Required';
      if (c.llm.temperature < 0 || c.llm.temperature > 1) e['llm.temperature'] = 'Must be 0–1';
      if (!c.llm.max_tokens || c.llm.max_tokens < 1) e['llm.max_tokens'] = 'Must be > 0';
      if (!c.report.chunk_size || c.report.chunk_size < 1) e['report.chunk_size'] = 'Must be > 0';
      if (c.report.incremental && c.report.max_workers !== 1) e['report.max_workers'] = 'Must be 1 in incremental mode';
      this.fieldErrors = e;
    },

    _scheduleValidate() {
      clearTimeout(this._vTimer);
      this._vTimer = setTimeout(() => this._validateFields(), 150);
    },

    // ── Saved configs ───────────────────────────────────────────────────

    async refreshSavedReports() {
      try {
        const res = await fetch('/reports');
        this.savedReports = await res.json();
      } catch { /* non-fatal */ }
    },

    async loadConfig() {
      if (this.isDirty && !confirm('Discard unsaved changes and load?')) return;
      const id = this.selectedSavedReport;
      if (!id) { this.toast('Select a config to load', 'warn'); return; }
      try {
        const res = await fetch(`/report-config?id=${encodeURIComponent(id)}`);
        if (!res.ok) throw new Error(await res.text());
        this.cfg = jsonToCfg(await res.json());
        this.pristineCfg = JSON.stringify(cfgToJson(this.cfg));
        this.isDirty = false;
        this._validateFields();
        this.$nextTick(() => {
          const ta = document.getElementById('cfg-prompt');
          if (ta) this.autoResize({ target: ta });
        });
      } catch (e) {
        this.toast('Failed to load config: ' + e.message, 'err');
      }
    },

    async saveConfig() {
      this._validateFields();
      if (Object.keys(this.fieldErrors).length) { this.toast('Fix errors before saving', 'err'); return; }
      try {
        const payload = cfgToJson(this.cfg);
        const res = await fetch('/save-report-config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const resp = await res.json();
        if (!res.ok) throw new Error(resp.errors?.join('; ') || JSON.stringify(resp));
        this.pristineCfg = JSON.stringify(payload);
        this.isDirty = false;
        await this.refreshSavedReports();
        this.selectedSavedReport = payload.id;
        this.toast(`Saved: ${resp.id}`);
      } catch (e) {
        this.toast('Failed to save: ' + e.message, 'err');
      }
    },

    // ── File handling ───────────────────────────────────────────────────

    onFileSelect(e) { const f = e.target.files[0]; if (f) this._attachFile(f); },

    onDrop(e) {
      this.isDragging = false;
      const f = e.dataTransfer.files[0];
      if (!f) return;
      const dt = new DataTransfer(); dt.items.add(f);
      this.$refs.fileInput.files = dt.files;
      this._attachFile(f);
    },

    _attachFile(file) {
      this.selectedFile = file;
      this.hasFile = true;
      this.fileName = file.name;
      this.fileSize = this._fmtSize(file.size);
      this.hasClearable = true;
    },

    clearFile() {
      this.selectedFile = null; this.hasFile = false;
      this.fileName = ''; this.fileSize = '';
      this.$refs.fileInput.value = '';
    },

    _fmtSize(b) {
      if (b < 1024)    return b + ' B';
      if (b < 1048576) return (b / 1024).toFixed(1) + ' KB';
      return (b / 1048576).toFixed(1) + ' MB';
    },

    // ── Run lifecycle ───────────────────────────────────────────────────

    makeRunId() {
      return new Date().toISOString().slice(0, 10) + '-' + Math.random().toString(36).slice(2, 8);
    },

    _resetRunState() {
      this.reportRows = []; this.reportColumns = []; this.reportFormat = null;
      this.reportFilter = ''; this.reportPage = 1; this.reportColFilters = {}; this.reportSort = { col: null, dir: 1 };
      this.chunks = []; this.totalTokensIn = 0; this.totalTokensOut = 0; this.totalElapsedSec = null;
      if (this._crawlTimer) { clearInterval(this._crawlTimer); this._crawlTimer = null; }
    },

    _startCrawl() {
      // Slowly advance the bar toward 30% while waiting for the first real event
      if (this._crawlTimer) { clearInterval(this._crawlTimer); }
      this._crawlTimer = setInterval(() => {
        if (!this.isRunning || this.chunks.length > 0) { clearInterval(this._crawlTimer); this._crawlTimer = null; return; }
        if (this.progress < 30) this.progress = Math.min(30, this.progress + 1);
      }, 600);
    },

    async runReport() {
      this._validateFields();
      if (!this.hasFile) { this.toast('Choose a data file', 'warn'); return; }
      if (Object.keys(this.fieldErrors).length) { this.toast('Fix configuration errors first', 'err'); return; }

      const payload = cfgToJson(this.cfg);
      const runId   = this.makeRunId();
      this.currentRun = { reportId: payload.id, runId };
      this.isRunning  = true;
      this.activeTab  = 'run';
      this._resetRunState();
      this.progress = 5; this.statusText = 'Uploading...'; this.hasClearable = true;

      this.subscribeProgress(payload.id, runId);
      this._startCrawl();
      this.elapsedSec = 0;
      this._elapsedTimer = setInterval(() => { this.elapsedSec++; }, 1000);

      const fd = new FormData();
      fd.set('config', JSON.stringify(payload));
      fd.set('run_id', runId);
      fd.set('file', this.selectedFile);
      if (this.maxRecords) fd.set('max_records', this.maxRecords);
      if (this.force)      fd.set('force', 'true');

      const t0 = Date.now();
      try {
        const res    = await fetch('/report', { method: 'POST', body: fd });
        const text   = await res.text();
        let parsed   = null;
        try { parsed = JSON.parse(text); } catch {}

        let summary = null, reportLink = null, s3Uri = null, outputFolder = null, errorMessage = null;

        if (!res.ok) {
          errorMessage = parsed?.error || parsed?.errors?.join('; ') || text;
          this.statusText = 'Failed';
        } else {
          this.statusText = 'Completed';
          if (parsed) {
            summary = {
              records:               parsed.records              ?? null,
              records_limit_reached: parsed.records_limit_reached ?? false,
              chunks:                parsed.chunks               ?? null,
              chunks_skipped:        parsed.chunks_skipped       ?? 0,
              duration_seconds:      parsed.duration_seconds     ?? null,
              stopped:               parsed.stopped              ?? false,
              input_tokens:          parsed.llm_usage?.input_tokens  ?? null,
              output_tokens:         parsed.llm_usage?.output_tokens ?? null,
              tool_calls:            parsed.tool_calls           ?? {},
            };
            if (parsed.report_id && parsed.run_id) {
              reportLink = `/report?id=${encodeURIComponent(parsed.report_id)}&run_id=${encodeURIComponent(parsed.run_id)}`;
              await this.fetchReportContent(parsed.report_id, parsed.run_id);
            }
            s3Uri        = parsed.s3_uri       ?? null;
            outputFolder = parsed.output_folder ?? null;
          }
        }
        this.progress = 100;
        this.addToHistory({
          reportId: payload.id, runId, runName: this.runName.trim() || null, timestamp: new Date().toISOString(),
          status: res.ok ? 'completed' : 'failed',
          fileName: this.fileName || null,
          runConfig: {
            model_id:    payload.llm.model_id,
            temperature: payload.llm.temperature,
            max_tokens:  payload.llm.max_tokens,
            chunk_size:  payload.report.chunk_size,
            incremental: payload.report.incremental,
            max_workers: payload.report.max_workers,
            tools:       payload.llm.tools ?? [],
          },
          summary, reportLink, s3Uri, outputFolder, errorMessage,
          totalTokensIn: this.totalTokensIn, totalTokensOut: this.totalTokensOut,
          durationMs: Date.now() - t0,
        });
      } catch (e) {
        this.statusText  = 'Network error';
        this.addToHistory({
          reportId: payload.id, runId, runName: this.runName.trim() || null, timestamp: new Date().toISOString(),
          status: 'failed',
          runConfig: { model_id: payload.llm.model_id, temperature: payload.llm.temperature, max_tokens: payload.llm.max_tokens, chunk_size: payload.report.chunk_size, incremental: payload.report.incremental, max_workers: payload.report.max_workers, tools: payload.llm.tools ?? [] },
          summary: null, reportLink: null, s3Uri: null, outputFolder: null,
          errorMessage: 'Network error: ' + (e?.message || String(e)),
          totalTokensIn: this.totalTokensIn, totalTokensOut: this.totalTokensOut,
          durationMs: Date.now() - t0,
        });
      } finally {
        this.isRunning = false;
        if (this._crawlTimer) { clearInterval(this._crawlTimer); this._crawlTimer = null; }
        if (this._elapsedTimer) { clearInterval(this._elapsedTimer); this._elapsedTimer = null; }
        setTimeout(() => { this.progress = 0; }, 800);
        setTimeout(() => { if (this._es) { this._es.close(); this._es = null; } }, 30000);
      }
    },

    subscribeProgress(reportId, runId) {
      if (this._es) { try { this._es.close(); } catch {} }
      this._es = new EventSource(`/progress/stream?report_id=${encodeURIComponent(reportId)}&run_id=${encodeURIComponent(runId)}`);
      this._es.addEventListener('hello', () => { this.statusText = 'Splitting data…'; if (this.progress < 10) this.progress = 10; });
      this._es.addEventListener('progress', (e) => {
        const evt   = JSON.parse(e.data);
        const idx   = evt.chunk_index ?? evt.completed_chunks ?? 1;
        const total = evt.total_chunks ?? 1;
        const tokIn  = evt.usage?.input_tokens  ?? 0;
        const tokOut = evt.usage?.output_tokens ?? 0;
        const dur    = evt.duration_seconds     ?? null;
        this.totalTokensIn  += tokIn;
        this.totalTokensOut += tokOut;
        if (dur != null) this.totalElapsedSec = (this.totalElapsedSec ?? 0) + dur;
        const ex = this.chunks.find(c => c.index === idx);
        if (ex) {
          Object.assign(ex, { status: 'done', tokensIn: tokIn, tokensOut: tokOut, durationSec: dur });
        } else {
          this.chunks.forEach(c => { if (c.status === 'running') c.status = 'done'; });
          this.chunks.push({ index: idx, total, status: 'done', tokensIn: tokIn, tokensOut: tokOut, durationSec: dur });
        }
        this.progress    = Math.max(10, Math.min(99, Math.floor((idx / total) * 100)));
        const tokStr = this.totalTokensIn > 0 ? ` · ${this.totalTokensIn.toLocaleString()} / ${this.totalTokensOut.toLocaleString()} tok` : '';
        this.statusText  = `Chunk ${idx} / ${total}${tokStr}`;
      });
      this._es.onerror = () => {
        if (this.isRunning) this.toast('Lost connection to progress stream', 'warn');
      };
    },

    async stopReport() {
      if (!this.currentRun.reportId) return;
      try {
        await fetch('/stop', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ report_id: this.currentRun.reportId, run_id: this.currentRun.runId }),
        });
        this.statusText = 'Stopped';
        if (this._es) { this._es.close(); this._es = null; }
        this.isRunning = false;
        this.addToHistory({
          reportId: this.currentRun.reportId, runId: this.currentRun.runId,
          timestamp: new Date().toISOString(), runName: this.runName.trim() || null, status: 'stopped',
          fileName: this.fileName || null,
          runConfig: { model_id: this.cfg.llm.model_id, temperature: this.cfg.llm.temperature, max_tokens: this.cfg.llm.max_tokens, chunk_size: this.cfg.report.chunk_size, incremental: this.cfg.report.incremental, max_workers: this.cfg.report.max_workers, tools: this.cfg.llm.tools ?? [] },
          summary: null, reportLink: null, s3Uri: null, outputFolder: null, errorMessage: null,
          totalTokensIn: this.totalTokensIn, totalTokensOut: this.totalTokensOut, durationMs: null,
        });
      } catch (e) { this.toast('Failed to stop: ' + e.message, 'err'); }
    },

    clearAll() {
      this.progress = 0; this.statusText = 'Ready';
      this._resetRunState();
      this.hasClearable = false; this.isRunning = false;
    },

    chunkStatusClass(s) {
      return { done: 'chunk-done', running: 'chunk-running', error: 'chunk-error' }[s] ?? 'chunk-pending';
    },

    // ── Report content ──────────────────────────────────────────────────

    async fetchReportContent(reportId, runId) {
      this.reportRows = []; this.reportColumns = []; this.reportFormat = null;
      this.reportFilter = ''; this.reportPage = 1; this.reportColFilters = {}; this.reportSort = { col: null, dir: 1 };
      try {
        const res = await fetch(`/report?id=${encodeURIComponent(reportId)}&run_id=${encodeURIComponent(runId)}`);
        if (!res.ok) return;
        const { format, columns, rows } = parseReportContent(await res.text());
        this.reportFormat  = format;
        this.reportColumns = columns;
        this.reportRows    = rows;
        this.hasClearable  = true;
      } catch { /* non-fatal */ }
    },

    // ── History ─────────────────────────────────────────────────────────

    addToHistory(entry) {
      this.history.unshift(entry);
      if (this.history.length > HISTORY_MAX) this.history = this.history.slice(0, HISTORY_MAX);
      this.persistHistory();
      this.selectedHistoryIdx = 0;
      this.activeTab = 'history';
    },

    selectHistory(i) {
      this.selectedHistoryIdx = i;
      this.compareResult = null; this.compareError = null;
      const entry = this.history[i];
      if (entry?.reportId && entry?.runId) {
        this.fetchReportContent(entry.reportId, entry.runId);
      } else {
        this.reportRows = []; this.reportColumns = []; this.reportFormat = null;
        this.reportColFilters = {}; this.reportSort = { col: null, dir: 1 };
      }
    },

    clearHistory() {
      this.history = []; this.selectedHistoryIdx = null;
      this.compareSelected = []; this.compareResult = null; this.compareError = null;
      localStorage.removeItem(HISTORY_KEY);
    },

    toggleCompareSelect(i) {
      const pos = this.compareSelected.indexOf(i);
      if (pos !== -1) {
        this.compareSelected = this.compareSelected.filter(x => x !== i);
      } else if (this.compareSelected.length < 2) {
        this.compareSelected = [...this.compareSelected, i];
      } else {
        // replace the older selection with the new one
        this.compareSelected = [this.compareSelected[1], i];
      }
      this.compareResult = null;
      this.compareError = null;
    },

    async compareRuns() {
      if (this.compareSelected.length !== 2) return;
      const [ia, ib] = this.compareSelected;
      const ea = this.history[ia];
      const eb = this.history[ib];
      if (!ea?.reportId || !ea?.runId || !eb?.reportId || !eb?.runId) {
        this.compareError = 'Selected runs are missing report/run IDs.';
        return;
      }
      this.compareLoading = true;
      this.compareResult = null;
      this.compareError = null;
      try {
        const res = await fetch('/api/compare', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            run_a: { report_id: ea.reportId, run_id: ea.runId, config: ea.runConfig ?? {} },
            run_b: { report_id: eb.reportId, run_id: eb.runId, config: eb.runConfig ?? {} },
          }),
        });
        const data = await res.json();
        if (!res.ok) {
          this.compareError = data.error || 'Compare failed';
        } else {
          this.compareResult = {
            text: data.comparison,
            usage: data.usage,
            labelA: `${ea.reportId} / ${ea.runId}${ea.runName ? ' — ' + ea.runName : ''}`,
            labelB: `${eb.reportId} / ${eb.runId}${eb.runName ? ' — ' + eb.runName : ''}`,
          };
        }
      } catch (e) {
        this.compareError = 'Network error: ' + (e?.message || String(e));
      } finally {
        this.compareLoading = false;
      }
    },

    persistHistory() {
      try { localStorage.setItem(HISTORY_KEY, JSON.stringify(this.history)); } catch {}
    },

    restoreHistory() {
      try { const r = localStorage.getItem(HISTORY_KEY); if (r) this.history = JSON.parse(r); }
      catch { this.history = []; }
    },

    formatHistoryTime(iso) {
      try { return new Date(iso).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' }); }
      catch { return iso; }
    },

    // ── Tools ───────────────────────────────────────────────────────────

    async fetchCompareAvailable() {
      try {
        const res = await fetch('/api/compare/available');
        if (res.ok) this.compareAvailable = (await res.json()).available;
      } catch { /* non-fatal */ }
    },

    async fetchAvailableTools() {
      try {
        const res = await fetch('/api/tools');
        if (res.ok) this.availableTools = await res.json();
      } catch { /* non-fatal */ }
    },

    toggleTool(name) {
      const tools = this.cfg.llm.tools;
      const idx = tools.indexOf(name);
      if (idx === -1) {
        this.cfg.llm.tools = [...tools, name];
      } else {
        this.cfg.llm.tools = tools.filter(t => t !== name);
      }
      this.markDirty();
    },

    historyStatusClass(s) {
      return {
        completed: 'chip chip-completed',
        failed:    'chip chip-failed',
        error:     'chip chip-failed',
        stopped:   'chip chip-stopped',
      }[s] ?? 'chip';
    },
  };
};
