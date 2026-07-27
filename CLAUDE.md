# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

**data2report** is an LLM-powered pipeline that generates reports from structured data files (CSV, JSONL, Parquet, `.gz`). It splits large files into chunks, sends each chunk to an LLM with a configured prompt, and merges the results. It supports AWS Bedrock (Claude, Jamba, Titan, Nova, Inference Profiles) and Google Gemini.

## Commands

### Install dependencies
```bash
pip install -r requirements.txt
pip install -r test/test.requirements.txt
```

### Run unit tests
```bash
PYTHONPATH=src:test python -m pytest --color=yes test/*_unit.py
```

### Run a single test file
```bash
PYTHONPATH=src:test python -m pytest --color=yes test/test_chunk_utils_unit.py
```

### Run integration tests (requires AWS credentials)
```bash
PYTHONPATH=src:test python -m pytest test/*_integration.py
```

### Run the REST server locally
```bash
./start_server.sh
```
Starts Flask on port 5001 (port 5000 is reserved by macOS AirPlay Receiver) and tees logs to `logs/`. Override the port with `APP_PORT=5002 ./start_server.sh`.

### Restart the server
When asked to restart the server, just run `./start_server.sh` in the background — the script already kills any existing instance. No separate `pkill` needed beforehand.

### Docker
```bash
docker build -t data2report:latest .
docker run --rm -v /tmp/reports:/data/data2report/ --env-file config/aws.env.list -p 5000:5000 data2report
```

## Architecture

### Core Pipeline

```
Input file (CSV/JSONL/Parquet/.gz)
  → chunks_utils.split_input_file()     # splits into chunk_0001.csv.gz, ...
  → report_processing.process_chunks_folder()   # invokes LLM per chunk (parallel or incremental)
  → report_processing.process_final_report()    # merges into final_report.gz
  → s3_utils (optional)                 # uploads to S3
```

**Incremental mode**: each chunk's LLM call includes the previous chunk's report as context — good for narrative continuity.  
**Parallel mode**: all chunks are processed independently, then concatenated — good for independent aggregation.

### Entry Points

| Entry Point | File | Use Case |
|---|---|---|
| Python API | `src/data2report.py` → `run_report()` | Programmatic use |
| REST + Web UI | `src/rest/data2report_rest.py` | Flask on port 5001 (default) |
| AWS Lambda | `src/lambda_function.py` | S3-triggered serverless |

### Key Source Files

- **`data2report.py`** — top-level `run_report()` orchestrator; resolves config, splits input, kicks off processing
- **`report_processing.py`** — chunk processing with `ThreadPoolExecutor`; incremental vs. parallel logic; merging final report
- **`chunks_utils.py`** — file splitting into gzipped chunks by row count; format detection
- **`llm_utils.py`** — model invocation for all supported providers; single-shot path and agentic tool-use loop (Bedrock/Claude only); prompt caching
- **`conf_utils.py`** — config loading, validation, and defaults; `validate_configuration()` is the canonical validator
- **`s3_utils.py`** — S3 read/write/list operations
- **`utils.py`** — path resolution, env vars, JSON extraction from LLM responses
- **`tools/`** — LLM tool primitives (see below)

### LLM Tools

Reports can expose tools to the LLM via `llm.tools` in the config. When tools are present, `llm_utils` runs an agentic loop (Bedrock/Claude only; other providers fall back to single-shot). Without tools the pipeline is unchanged.

**Tool registry**: `src/tools/registry.py` maps names → classes. Adding a primitive = one new file + one registry entry.

**Current primitives:**

| Tool | Purpose |
|---|---|
| `query_data` | Read-only SQL (`SELECT` only) over the current chunk via `sqlite3`. Table name: `chunk`. Returns `{columns, rows, truncated}`. Guardrails: 100-row cap, 3 s timeout, cell truncation. |
| `chain_decoder` | Greedily decodes obfuscated strings (URL → base64 → hex → gzip → utf-8 → JS-escape). Returns `{decoded, chain, truncated}`. Guardrails: depth 5, 4 KB output cap, printable-ratio check. |

**REST endpoint**: `GET /api/tools` returns `[{name, description}]` — used by the UI Tools tab.

### Report Configuration Schema

Configs are JSON files (stored locally or on S3) with this shape:
```json
{
  "id": "report_id",
  "name": "Human-readable name",
  "llm": {
    "model_id": "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "system_prompt": "...",
    "temperature": 0.3,
    "max_tokens": 1000,
    "tools": ["query_data", "chain_decoder"]
  },
  "report": {
    "chunk_size": 100,
    "incremental": true,
    "max_workers": 1
  },
  "input": {
    "format": "csv",
    "header": true
  }
}
```

`llm.tools` is optional — omitting it preserves the original single-shot behaviour. Tool names must match entries in `src/tools/registry.py`; `validate_configuration()` rejects unknown names.

### Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `REPORTS_FOLDER` | `/data/data2report/` | Local output folder |
| `REPORTS_BUCKET` | — | S3 bucket for reports |
| `DATA2REPORT_PREFIX` | `data2report` | S3 key prefix |
| `AWS_REGION` | `us-east-1` | AWS region |
| `GEMINI_API_KEY` | — | Required for Gemini models |
| `TIMEOUT` | `800` | Per-chunk processing timeout (seconds) |
| `PREFIX_TO_REPORT` | — | Lambda: maps S3 prefixes to report IDs |

### AWS / Authentication

The project uses AWS Bedrock. Local development uses the `claude` AWS profile (see `.claude/settings.local.json`). The `saml2aws login` command refreshes credentials. For Lambda, credentials are passed via the `CREDS` env var or standard IAM roles.

### Testing Patterns

- Unit tests use `moto` to mock AWS services — no real AWS calls needed.
- Test fixtures in `test/conftest.py` generate synthetic CSV data and mock LLM responses.
- Integration tests (`*_integration.py`) hit real AWS services and require valid credentials.
- Lambda integration tests are in `test_utils_integration.py` and `test_report_integration.py`.