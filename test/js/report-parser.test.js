const { parseCsv, parseReportContent, _splitCsvLine } = require('../../src/rest/static/report-parser');

describe('_splitCsvLine', () => {
  test('splits simple CSV', () => {
    expect(_splitCsvLine('a,b,c')).toEqual(['a', 'b', 'c']);
  });

  test('handles quoted fields', () => {
    expect(_splitCsvLine('"hello world",b')).toEqual(['hello world', 'b']);
  });

  test('handles escaped quotes inside quoted field', () => {
    expect(_splitCsvLine('"say ""hi""",b')).toEqual(['say "hi"', 'b']);
  });

  test('handles empty fields', () => {
    expect(_splitCsvLine('a,,c')).toEqual(['a', '', 'c']);
  });
});

describe('parseCsv', () => {
  test('parses header + data rows', () => {
    const text = 'name,age\nAlice,30\nBob,25\n';
    const result = parseCsv(text);
    expect(result.columns).toEqual(['name', 'age']);
    expect(result.rows).toHaveLength(2);
    expect(result.rows[0]).toEqual({ name: 'Alice', age: '30' });
  });

  test('skips blank lines', () => {
    const text = 'a,b\n\n1,2\n\n3,4\n';
    expect(parseCsv(text).rows).toHaveLength(2);
  });

  test('returns null for empty input', () => {
    expect(parseCsv('')).toBeNull();
    expect(parseCsv('\n\n')).toBeNull();
  });

  test('fills missing cells with empty string', () => {
    const text = 'a,b,c\n1,2\n';
    expect(parseCsv(text).rows[0].c).toBe('');
  });
});

describe('parseReportContent', () => {
  test('detects JSONL', () => {
    const text = '{"name":"Alice","score":10}\n{"name":"Bob","score":20}\n';
    const r = parseReportContent(text);
    expect(r.format).toBe('jsonl');
    expect(r.columns).toEqual(['name', 'score']);
    expect(r.rows).toHaveLength(2);
    expect(r.rows[0].name).toBe('Alice');
  });

  test('detects CSV', () => {
    const text = 'city,pop\nLondon,9000000\nParis,2000000\n';
    const r = parseReportContent(text);
    expect(r.format).toBe('csv');
    expect(r.columns).toEqual(['city', 'pop']);
    expect(r.rows).toHaveLength(2);
  });

  test('falls back to text for single-column / plain text', () => {
    const text = 'Summary line one\nSummary line two\n';
    const r = parseReportContent(text);
    expect(r.format).toBe('text');
    expect(r.columns).toEqual(['line']);
    expect(r.rows[0].line).toBe('Summary line one');
  });

  test('returns empty result for blank input', () => {
    const r = parseReportContent('');
    expect(r.format).toBeNull();
    expect(r.rows).toHaveLength(0);
  });

  test('JSONL columns union across all rows', () => {
    const text = '{"a":1}\n{"a":2,"b":3}\n';
    const r = parseReportContent(text);
    expect(r.columns).toContain('a');
    expect(r.columns).toContain('b');
  });
});
