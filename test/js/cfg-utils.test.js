const { MODEL_OPTIONS, emptyCfg, cfgToJson, jsonToCfg } = require('../../src/rest/static/cfg-utils');

describe('emptyCfg', () => {
  test('returns defaults', () => {
    const c = emptyCfg();
    expect(c.id).toBe('');
    expect(c.name).toBe('');
    expect(c.llm.model_id).toBe(MODEL_OPTIONS[0].value);
    expect(c.llm.temperature).toBe(0.3);
    expect(c.llm.max_tokens).toBe(1000);
    expect(c.report.chunk_size).toBe(100);
    expect(c.report.incremental).toBe(false);
    expect(c.report.max_workers).toBe(4);
    expect(c.report.output_format).toBeNull();
    expect(c.input.format).toBeNull();
    expect(c.input.header).toBeNull();
  });
});

describe('cfgToJson', () => {
  test('omits optional fields when null', () => {
    const cfg = emptyCfg();
    cfg.id = 'my_report'; cfg.name = 'My Report';
    const j = cfgToJson(cfg);
    expect(j.report.output_format).toBeUndefined();
    expect(j.input).toBeUndefined();
  });

  test('includes output_format when set', () => {
    const cfg = emptyCfg();
    cfg.report.output_format = 'csv';
    expect(cfgToJson(cfg).report.output_format).toBe('csv');
  });

  test('includes input block when format set', () => {
    const cfg = emptyCfg();
    cfg.input.format = 'jsonl';
    const j = cfgToJson(cfg);
    expect(j.input.format).toBe('jsonl');
    expect(j.input.header).toBeUndefined();
  });

  test('includes input block when header set', () => {
    const cfg = emptyCfg();
    cfg.input.header = true;
    const j = cfgToJson(cfg);
    expect(j.input.header).toBe(true);
    expect(j.input.format).toBeUndefined();
  });
});

describe('jsonToCfg', () => {
  test('round-trips a full config', () => {
    const original = emptyCfg();
    original.id = 'test'; original.name = 'Test';
    original.llm.system_prompt = 'You are helpful.';
    original.report.output_format = 'jsonl';
    original.input.format = 'csv'; original.input.header = true;
    const round = jsonToCfg(cfgToJson(original));
    expect(round).toEqual(original);
  });

  test('uses defaults for missing fields', () => {
    const cfg = jsonToCfg({});
    expect(cfg.llm.temperature).toBe(0.3);
    expect(cfg.report.chunk_size).toBe(100);
    expect(cfg.report.incremental).toBe(false);
  });

  test('preserves explicit values', () => {
    const cfg = jsonToCfg({ id: 'x', llm: { temperature: 0.7, max_tokens: 500 }, report: { chunk_size: 50, incremental: true, max_workers: 1 } });
    expect(cfg.llm.temperature).toBe(0.7);
    expect(cfg.llm.max_tokens).toBe(500);
    expect(cfg.report.chunk_size).toBe(50);
    expect(cfg.report.incremental).toBe(true);
  });
});
