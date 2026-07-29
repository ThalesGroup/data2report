# Copyright 2026 Thales
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import gzip
import json
import os
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from conf_utils import validate_configuration
from conftest import get_config
from data2report import run_report
from tools.memory import MemoryTool, DEFAULT_SCHEMA


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_tool(schema=None, mode="incremental"):
    t = MemoryTool(schema or DEFAULT_SCHEMA, mode)
    t.initialize()
    return t


def _config_with_output(incremental=True, schema=None, fmt="jsonl"):
    cfg = get_config("test_report")
    cfg["report"]["incremental"] = incremental
    cfg["report"]["max_workers"] = 1 if incremental else 3
    cfg["report"]["output"] = {
        "format": fmt,
        "schema": schema or [c.copy() for c in DEFAULT_SCHEMA],
    }
    # Use a claude model so MemoryTool path activates
    cfg["llm"]["model_id"] = "anthropic.claude-3-5-sonnet-20241029-v2:0"
    return cfg


@contextmanager
def mock_llm_with_tool_calls(tool_name, rows):
    """
    Simulate an LLM that calls `tool_name` once per row, then ends.
    The mock fires the real MemoryTool.run() for each row so SQLite is populated.
    """
    def fake_invoke(system_prompt, user_prompt, model_id, max_tokens, temperature,
                    session=None, tools=None, chunk_path=None, shared_tools=None):
        all_tools = (tools or []) + (shared_tools or [])
        tool_map = {t.name: t for t in all_tools}
        tool = tool_map.get(tool_name)
        for row in rows:
            if tool:
                tool.run({"row": row})
        return {"content": "", "usage": {"input_tokens": 5, "output_tokens": 2}, "tool_calls": {tool_name: len(rows)}}

    with patch("report_processing.invoke_llm", side_effect=fake_invoke):
        yield


# ── MemoryTool unit tests ─────────────────────────────────────────────────────

class TestMemoryToolBasics:
    def test_initialize_creates_table(self):
        t = _make_tool()
        rows = t.dump()
        assert rows == []

    def test_write_and_dump(self):
        t = _make_tool()
        result = t.run({"row": {"entity": "SSH brute force", "label": "auth", "count": 10}})
        assert result == {"ok": True}
        rows = t.dump()
        assert len(rows) == 1
        assert rows[0]["entity"] == "SSH brute force"
        assert rows[0]["count"] == 10

    def test_dump_returns_all_columns(self):
        t = _make_tool()
        t.run({"row": {"entity": "X", "label": "Y", "count": 1}})
        row = t.dump()[0]
        assert set(row.keys()) == {"entity", "label", "count"}

    def test_setup_is_noop(self):
        t = _make_tool()
        t.setup("/some/path")  # must not raise

    def test_schema_shape(self):
        t = _make_tool()
        s = t.schema()
        assert s["name"] == "memory"
        assert "row" in s["input_schema"]["properties"]
        props = s["input_schema"]["properties"]["row"]["properties"]
        assert "entity" in props
        assert "count" in props

    def test_custom_schema_reflected_in_tool_schema(self):
        schema = [
            {"name": "ip", "type": "TEXT", "primary_key": True},
            {"name": "hits", "type": "INTEGER"},
        ]
        t = _make_tool(schema=schema)
        props = t.schema()["input_schema"]["properties"]["row"]["properties"]
        assert "ip" in props
        assert "hits" in props
        assert "entity" not in props


# ── Incremental mode (upsert) ─────────────────────────────────────────────────

class TestMemoryToolIncremental:
    def test_upsert_updates_existing_pk(self):
        t = _make_tool(mode="incremental")
        t.run({"row": {"entity": "Login failure", "label": "auth", "count": 5}})
        t.run({"row": {"entity": "Login failure", "label": "auth", "count": 50}})
        rows = t.dump()
        assert len(rows) == 1
        assert rows[0]["count"] == 50

    def test_multiple_distinct_rows(self):
        t = _make_tool(mode="incremental")
        t.run({"row": {"entity": "A", "label": "x", "count": 1}})
        t.run({"row": {"entity": "B", "label": "y", "count": 2}})
        assert len(t.dump()) == 2

    def test_partial_row_fills_nulls(self):
        t = _make_tool(mode="incremental")
        t.run({"row": {"entity": "E"}})  # only PK provided
        row = t.dump()[0]
        assert row["entity"] == "E"
        assert row["label"] is None
        assert row["count"] is None


# ── Parallel mode (insert-only) ───────────────────────────────────────────────

class TestMemoryToolParallel:
    def test_insert_succeeds(self):
        t = _make_tool(mode="parallel")
        result = t.run({"row": {"entity": "A", "label": "x", "count": 1}})
        assert result == {"ok": True}

    def test_duplicate_pk_returns_error(self):
        t = _make_tool(mode="parallel")
        t.run({"row": {"entity": "A", "label": "x", "count": 1}})
        result = t.run({"row": {"entity": "A", "label": "x", "count": 2}})
        assert "error" in result
        assert "duplicate key" in result["error"]

    def test_duplicate_does_not_overwrite(self):
        t = _make_tool(mode="parallel")
        t.run({"row": {"entity": "A", "label": "x", "count": 1}})
        t.run({"row": {"entity": "A", "label": "x", "count": 99}})
        assert t.dump()[0]["count"] == 1


# ── Row-shape validation ──────────────────────────────────────────────────────

class TestMemoryToolValidation:
    def test_missing_pk_returns_error(self):
        t = _make_tool()
        result = t.run({"row": {"label": "x", "count": 1}})
        assert "error" in result
        assert "entity" in result["error"]

    def test_unknown_column_returns_error(self):
        t = _make_tool()
        result = t.run({"row": {"entity": "X", "bogus": "value"}})
        assert "error" in result
        assert "bogus" in result["error"]

    def test_integer_coercion_from_string(self):
        t = _make_tool()
        result = t.run({"row": {"entity": "X", "count": "42"}})
        assert result == {"ok": True}
        assert t.dump()[0]["count"] == 42

    def test_non_numeric_integer_returns_error(self):
        t = _make_tool()
        result = t.run({"row": {"entity": "X", "count": "not-a-number"}})
        assert "error" in result
        assert "count" in result["error"]

    def test_row_not_a_dict_returns_error(self):
        t = _make_tool()
        result = t.run({"row": ["entity", "label"]})
        assert "error" in result

    def test_missing_row_key_returns_error(self):
        t = _make_tool()
        result = t.run({})
        assert "error" in result


# ── conf_utils validation ─────────────────────────────────────────────────────

class TestValidateConfigurationOutput:
    def _base(self):
        return get_config("test_report")

    def test_no_output_section_is_valid(self):
        cfg = self._base()
        assert validate_configuration(cfg, None) == []

    def test_valid_output_section(self):
        cfg = self._base()
        cfg["report"]["output"] = {
            "format": "jsonl",
            "schema": [
                {"name": "entity", "type": "TEXT", "primary_key": True},
                {"name": "count", "type": "INTEGER"},
            ],
        }
        assert validate_configuration(cfg, None) == []

    def test_valid_csv_format(self):
        cfg = self._base()
        cfg["report"]["output"] = {
            "format": "csv",
            "schema": [{"name": "entity", "type": "TEXT", "primary_key": True}],
        }
        assert validate_configuration(cfg, None) == []

    def test_invalid_format_rejected(self):
        cfg = self._base()
        cfg["report"]["output"] = {
            "format": "txt",
            "schema": [{"name": "entity", "type": "TEXT", "primary_key": True}],
        }
        errs = validate_configuration(cfg, None)
        assert any("format" in e for e in errs)

    def test_missing_pk_rejected(self):
        cfg = self._base()
        cfg["report"]["output"] = {
            "schema": [
                {"name": "entity", "type": "TEXT"},
                {"name": "count", "type": "INTEGER"},
            ],
        }
        errs = validate_configuration(cfg, None)
        assert any("primary_key" in e for e in errs)

    def test_multiple_pks_rejected(self):
        cfg = self._base()
        cfg["report"]["output"] = {
            "schema": [
                {"name": "entity", "type": "TEXT", "primary_key": True},
                {"name": "label", "type": "TEXT", "primary_key": True},
            ],
        }
        errs = validate_configuration(cfg, None)
        assert any("primary_key" in e for e in errs)

    def test_unknown_column_type_rejected(self):
        cfg = self._base()
        cfg["report"]["output"] = {
            "schema": [{"name": "entity", "type": "VARCHAR", "primary_key": True}],
        }
        errs = validate_configuration(cfg, None)
        assert any("type" in e.lower() for e in errs)

    def test_unknown_output_key_rejected(self):
        cfg = self._base()
        cfg["report"]["output"] = {
            "schema": [{"name": "entity", "type": "TEXT", "primary_key": True}],
            "surprise": True,
        }
        errs = validate_configuration(cfg, None)
        assert any("surprise" in e for e in errs)

    def test_empty_schema_rejected(self):
        cfg = self._base()
        cfg["report"]["output"] = {"schema": []}
        errs = validate_configuration(cfg, None)
        assert any("schema" in e for e in errs)


# ── Integration: run_report with mocked LLM ───────────────────────────────────

class TestRunReportWithOutput:
    def test_incremental_accumulates_rows(self, reports_folder, csv_file_with_1k_lines):
        rows_per_chunk = [
            {"entity": "Login failure", "label": "auth", "count": 10},
            {"entity": "Port scan", "label": "recon", "count": 5},
        ]
        cfg = _config_with_output(incremental=True)
        with mock_llm_with_tool_calls("memory", rows_per_chunk):
            result = run_report(csv_file_with_1k_lines, configuration=cfg)
        assert result["chunks"] == 2
        out_file = os.path.join(result["output_folder"], "final_report.gz")
        assert os.path.exists(out_file)
        with gzip.open(out_file, "rt") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        # Incremental mode upserts — same PK from both chunks collapses to one row each
        entities = {r["entity"] for r in rows}
        assert "Login failure" in entities
        assert "Port scan" in entities

    def test_parallel_all_rows_present(self, reports_folder, csv_file_with_1k_lines):
        rows_per_chunk = [
            {"entity": "SYN flood", "label": "dos", "count": 20},
        ]
        cfg = _config_with_output(incremental=False)
        with mock_llm_with_tool_calls("memory", rows_per_chunk):
            result = run_report(csv_file_with_1k_lines, configuration=cfg)
        out_file = os.path.join(result["output_folder"], "final_report.gz")
        with gzip.open(out_file, "rt") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        assert any(r["entity"] == "SYN flood" for r in rows)

    def test_output_is_valid_jsonl(self, reports_folder, csv_file_with_1k_lines):
        cfg = _config_with_output(incremental=True)
        with mock_llm_with_tool_calls("memory", [{"entity": "X", "label": "y", "count": 1}]):
            result = run_report(csv_file_with_1k_lines, configuration=cfg)
        out_file = os.path.join(result["output_folder"], "final_report.gz")
        with gzip.open(out_file, "rt") as f:
            for line in f:
                if line.strip():
                    obj = json.loads(line)
                    assert isinstance(obj, dict)

    def test_unexpected_text_counter(self, reports_folder, csv_file_with_1k_lines):
        def fake_invoke(system_prompt, user_prompt, model_id, max_tokens, temperature,
                        session=None, tools=None, chunk_path=None, shared_tools=None):
            # LLM ignores instructions and returns narrative instead of using tool
            return {"content": "Here is my analysis...", "usage": {"input_tokens": 5, "output_tokens": 10}, "tool_calls": {}}

        cfg = _config_with_output(incremental=True)
        with patch("report_processing.invoke_llm", side_effect=fake_invoke):
            result = run_report(csv_file_with_1k_lines, configuration=cfg)
        assert result["chunks_with_unexpected_text"] == result["chunks"]

    def test_system_prompt_has_schema_appended(self, reports_folder, csv_file_with_1k_lines):
        received_prompts = []

        def fake_invoke(system_prompt, user_prompt, model_id, max_tokens, temperature,
                        session=None, tools=None, chunk_path=None, shared_tools=None):
            received_prompts.append(system_prompt)
            return {"content": "", "usage": {"input_tokens": 5, "output_tokens": 2}, "tool_calls": {}}

        cfg = _config_with_output(incremental=True)
        with patch("report_processing.invoke_llm", side_effect=fake_invoke):
            run_report(csv_file_with_1k_lines, configuration=cfg)

        assert received_prompts, "invoke_llm was never called"
        for prompt in received_prompts:
            assert "entity" in prompt
            assert "memory tool" in prompt.lower() or "memory" in prompt.lower()

    def test_non_claude_system_prompt_has_schema(self, reports_folder, csv_file_with_1k_lines):
        received_prompts = []

        def fake_invoke(system_prompt, user_prompt, model_id, max_tokens, temperature,
                        session=None, tools=None, chunk_path=None, shared_tools=None):
            received_prompts.append(system_prompt)
            return {"content": '{"entity":"X","label":"y","count":1}', "usage": {"input_tokens": 5, "output_tokens": 10}, "tool_calls": {}}

        cfg = _config_with_output(incremental=True)
        cfg["llm"]["model_id"] = "amazon.nova-pro-v1:0"
        with patch("report_processing.invoke_llm", side_effect=fake_invoke):
            run_report(csv_file_with_1k_lines, configuration=cfg)

        assert received_prompts
        for prompt in received_prompts:
            assert "entity" in prompt
            assert "JSON" in prompt
