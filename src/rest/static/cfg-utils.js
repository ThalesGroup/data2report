const MODEL_OPTIONS = [
  { provider: 'Claude', label: 'Claude 3.5 Sonnet v2', value: 'anthropic.claude-3-5-sonnet-20241029-v2:0' },
  { provider: 'Claude', label: 'Claude 3.5 Haiku',     value: 'anthropic.claude-3-5-haiku-20241022-v1:0' },
  { provider: 'Claude', label: 'Claude 3 Opus',        value: 'anthropic.claude-3-opus-20240229-v1:0' },
  { provider: 'Nova',   label: 'Nova Pro',              value: 'amazon.nova-pro-v1:0' },
  { provider: 'Nova',   label: 'Nova Lite',             value: 'amazon.nova-lite-v1:0' },
  { provider: 'Gemini', label: 'Gemini 1.5 Pro',        value: 'gemini-1.5-pro' },
  { provider: 'Gemini', label: 'Gemini 1.5 Flash',      value: 'gemini-1.5-flash' },
];

function emptyCfg() {
  return {
    id: '',
    name: '',
    llm: { model_id: MODEL_OPTIONS[0].value, system_prompt: '', temperature: 0.3, max_tokens: 1000, tools: [] },
    report: { chunk_size: 100, incremental: false, max_workers: 4, output_format: null },
    input: { format: null, header: null },
  };
}

function cfgToJson(cfg) {
  const llmOut = {
    model_id: cfg.llm.model_id,
    system_prompt: cfg.llm.system_prompt,
    temperature: cfg.llm.temperature,
    max_tokens: cfg.llm.max_tokens,
  };
  if (cfg.llm.tools && cfg.llm.tools.length > 0) llmOut.tools = cfg.llm.tools;
  const out = {
    id: cfg.id,
    name: cfg.name,
    llm: llmOut,
    report: {
      chunk_size: cfg.report.chunk_size,
      incremental: cfg.report.incremental,
      max_workers: cfg.report.max_workers,
    },
  };
  if (cfg.report.output_format !== null) out.report.output_format = cfg.report.output_format;
  if (cfg.input.format !== null || cfg.input.header !== null) {
    out.input = {};
    if (cfg.input.format !== null) out.input.format = cfg.input.format;
    if (cfg.input.header !== null) out.input.header = cfg.input.header;
  }
  return out;
}

function jsonToCfg(json) {
  const base = emptyCfg();
  base.id   = json.id   ?? '';
  base.name = json.name ?? '';
  if (json.llm) {
    base.llm.model_id      = json.llm.model_id      ?? base.llm.model_id;
    base.llm.system_prompt = json.llm.system_prompt ?? '';
    base.llm.temperature   = json.llm.temperature   ?? 0.3;
    base.llm.max_tokens    = json.llm.max_tokens    ?? 1000;
    base.llm.tools         = Array.isArray(json.llm.tools) ? json.llm.tools : [];
  }
  if (json.report) {
    base.report.chunk_size    = json.report.chunk_size    ?? 100;
    base.report.incremental   = json.report.incremental   ?? false;
    base.report.max_workers   = json.report.max_workers   ?? 4;
    base.report.output_format = json.report.output_format ?? null;
  }
  if (json.input) {
    base.input.format = json.input.format ?? null;
    base.input.header = json.input.header ?? null;
  }
  return base;
}

if (typeof module !== 'undefined') module.exports = { MODEL_OPTIONS, emptyCfg, cfgToJson, jsonToCfg };
