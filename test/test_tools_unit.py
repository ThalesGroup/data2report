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

import csv
import gzip
import json
import tempfile

import pytest

from tools.chain_decoder import ChainDecoderTool, _decode_chain
from tools.query_data import QueryDataTool, load_chunk_into_sqlite
from tools.registry import get_tool, list_tools, REGISTRY
from conf_utils import validate_configuration
from conftest import get_config


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_csv_gz(rows: list[dict], include_header: bool = True) -> str:
    """Write rows to a temp gzipped CSV and return the path."""
    f = tempfile.NamedTemporaryFile(suffix=".csv.gz", delete=False)
    with gzip.open(f.name, "wt") as gz:
        if rows:
            writer = csv.DictWriter(gz, fieldnames=list(rows[0].keys()))
            if include_header:
                writer.writeheader()
            writer.writerows(rows)
    return f.name


def _make_jsonl_gz(rows: list[dict]) -> str:
    f = tempfile.NamedTemporaryFile(suffix=".jsonl.gz", delete=False)
    with gzip.open(f.name, "wt") as gz:
        for row in rows:
            gz.write(json.dumps(row) + "\n")
    return f.name


# ── Registry ──────────────────────────────────────────────────────────────────


class TestRegistry:
    def test_list_tools_returns_all(self):
        tools = list_tools()
        names = [t["name"] for t in tools]
        assert "query_data" in names
        assert "chain_decoder" in names

    def test_list_tools_has_descriptions(self):
        for t in list_tools():
            assert t["description"]

    def test_get_tool_known(self):
        tool = get_tool("query_data")
        assert tool.name == "query_data"

    def test_get_tool_unknown(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            get_tool("does_not_exist")


# ── load_chunk_into_sqlite ─────────────────────────────────────────────────────


class TestLoadChunkIntoSqlite:
    def test_csv_row_count(self):
        path = _make_csv_gz([{"ip": "1.2.3.4", "port": "22"} for _ in range(5)])
        conn = load_chunk_into_sqlite(path)
        count = conn.execute("SELECT COUNT(*) FROM chunk").fetchone()[0]
        assert count == 5

    def test_csv_columns(self):
        path = _make_csv_gz([{"src": "a", "dst": "b"}])
        conn = load_chunk_into_sqlite(path)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(chunk)").fetchall()]
        assert "src" in cols
        assert "dst" in cols

    def test_jsonl_row_count(self):
        path = _make_jsonl_gz([{"cmd": "wget", "ip": "1.2.3.4"} for _ in range(3)])
        conn = load_chunk_into_sqlite(path)
        count = conn.execute("SELECT COUNT(*) FROM chunk").fetchone()[0]
        assert count == 3

    def test_jsonl_columns(self):
        path = _make_jsonl_gz([{"cmd": "wget", "ip": "1.2.3.4"}])
        conn = load_chunk_into_sqlite(path)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(chunk)").fetchall()]
        assert "cmd" in cols
        assert "ip" in cols


# ── QueryDataTool ──────────────────────────────────────────────────────────────


class TestQueryDataTool:
    def _tool_on(self, rows):
        path = _make_csv_gz(rows)
        tool = QueryDataTool()
        tool.setup(path)
        return tool

    def test_count_query(self):
        tool = self._tool_on([{"ip": "1.1.1.1"} for _ in range(10)])
        result = tool.run({"sql": "SELECT COUNT(*) as n FROM chunk"})
        assert result["rows"][0][0] == "10"

    def test_group_by(self):
        rows = [{"ip": "1.1.1.1"}] * 3 + [{"ip": "2.2.2.2"}] * 7
        tool = self._tool_on(rows)
        result = tool.run({"sql": "SELECT ip, COUNT(*) as n FROM chunk GROUP BY ip ORDER BY n DESC"})
        assert result["rows"][0][0] == "2.2.2.2"
        assert result["rows"][0][1] == "7"

    def test_rejects_non_select(self):
        tool = self._tool_on([{"ip": "x"}])
        result = tool.run({"sql": "DROP TABLE chunk"})
        assert "error" in result

    def test_row_cap(self):
        tool = self._tool_on([{"ip": str(i)} for i in range(200)])
        result = tool.run({"sql": "SELECT * FROM chunk"})
        assert len(result["rows"]) == 100
        assert result["truncated"] is True

    def test_not_initialized(self):
        tool = QueryDataTool()
        result = tool.run({"sql": "SELECT 1"})
        assert "error" in result

    def test_schema_shape(self):
        tool = QueryDataTool()
        s = tool.schema()
        assert s["name"] == "query_data"
        assert "input_schema" in s
        assert "sql" in s["input_schema"]["properties"]


# ── ChainDecoderTool ───────────────────────────────────────────────────────────


class TestChainDecoderTool:
    def test_url_decode(self):
        tool = ChainDecoderTool()
        result = tool.run({"value": "hello%20world"})
        assert result["decoded"] == "hello world"
        assert "url" in result["chain"]

    def test_base64_decode(self):
        import base64
        encoded = base64.b64encode(b"secret payload").decode()
        tool = ChainDecoderTool()
        result = tool.run({"value": encoded})
        assert result["decoded"] == "secret payload"
        assert "base64" in result["chain"]

    def test_no_decode_needed(self):
        tool = ChainDecoderTool()
        result = tool.run({"value": "plain text"})
        assert result["decoded"] == "plain text"
        assert result["chain"] == []

    def test_chain_url_then_base64(self):
        import base64, urllib.parse
        # Use bytes that produce +/= in base64 so URL-quoting actually changes the string
        raw = b"\xfb\xef\xbe"  # base64 → ++++  contains '+'
        b64 = base64.b64encode(raw).decode()  # e.g. ++8+
        encoded = urllib.parse.quote(b64)     # + → %2B, etc.
        assert encoded != b64, "test setup: URL encoding must change the string"
        tool = ChainDecoderTool()
        result = tool.run({"value": encoded})
        assert "url" in result["chain"]
        assert "base64" in result["chain"]
        assert result["chain"].index("url") < result["chain"].index("base64")

    def test_schema_shape(self):
        tool = ChainDecoderTool()
        s = tool.schema()
        assert s["name"] == "chain_decoder"
        assert "value" in s["input_schema"]["properties"]

    def test_truncated_flag(self):
        long_value = "A" * 10000
        decoded, chain, truncated = _decode_chain(long_value)
        assert truncated is True
        assert len(decoded.encode("utf-8")) <= 4096 + 3  # +3 for possible multi-byte at boundary


# ── conf_utils validation ─────────────────────────────────────────────────────


class TestValidateConfigurationTools:
    def _base(self):
        return get_config("test_report")

    def test_no_tools_field_is_valid(self):
        cfg = self._base()
        assert validate_configuration(cfg, None) == []

    def test_empty_tools_list_is_valid(self):
        cfg = self._base()
        cfg["llm"]["tools"] = []
        assert validate_configuration(cfg, None) == []

    def test_valid_tool_names(self):
        cfg = self._base()
        cfg["llm"]["tools"] = ["query_data", "chain_decoder"]
        assert validate_configuration(cfg, None) == []

    def test_unknown_tool_name(self):
        cfg = self._base()
        cfg["llm"]["tools"] = ["query_data", "nonexistent_tool"]
        errs = validate_configuration(cfg, None)
        assert any("unknown tool 'nonexistent_tool'" in e for e in errs)

    def test_tools_must_be_list(self):
        cfg = self._base()
        cfg["llm"]["tools"] = "query_data"
        errs = validate_configuration(cfg, None)
        assert any("llm.tools must be a list" in e for e in errs)

    def test_tools_entries_must_be_strings(self):
        cfg = self._base()
        cfg["llm"]["tools"] = [42]
        errs = validate_configuration(cfg, None)
        assert any("must be strings" in e for e in errs)
