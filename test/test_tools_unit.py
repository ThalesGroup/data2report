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

from tools.calculate import CalculateTool
from tools.chain_decoder import ChainDecoderTool, _decode_chain
from tools.query_data import QueryDataTool, load_chunk_into_sqlite
from tools.regex_extract import RegexExtractTool
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
        assert "calculate" in names
        assert "regex_extract" in names

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


# ── CalculateTool ─────────────────────────────────────────────────────────────


class TestCalculateTool:
    def _calc(self, expression):
        return CalculateTool().run({"expression": expression})

    @pytest.mark.parametrize(
        "expression,expected",
        [
            ("1 + 2 * 3", 7),
            ("(1 + 2) * 3", 9),
            ("7 // 2", 3),
            ("7 % 4", 3),
            ("2 ** 10", 1024),
            ("-5 + +2", -3),
            ("sum([1, 2, 3, 4])", 10),
            ("mean([2, 4, 6])", 4),
            ("median([5, 1, 3])", 3),
            ("max(3, 9, 4)", 9),
            ("round(7 / 3, 2)", 2.33),
            ("sqrt(16)", 4),
            ("len([1, 2, 3])", 3),
            ("percentile([1, 2, 3, 4, 5], 50)", 3),
            ("percentile([10, 20], 25)", 12.5),
            ("pct_change(120, 150)", 25),
            ("pct_change(200, 100)", -50),
        ],
    )
    def test_expressions(self, expression, expected):
        assert self._calc(expression)["result"] == pytest.approx(expected)

    def test_constants(self):
        assert self._calc("round(pi, 2)")["result"] == 3.14

    def test_stdev(self):
        assert self._calc("stdev([2, 4, 4, 4, 5, 5, 7, 9])")["result"] == pytest.approx(
            2.138, abs=1e-3
        )

    @pytest.mark.parametrize(
        "expression",
        [
            "__import__('os').system('ls')",
            "open('/etc/passwd')",
            "().__class__",
            "[x for x in range(3)]",
            "'a' * 3",
            "True + 1",
            "lambda: 1",
            "mean(values=[1, 2])",
            "unknown + 1",
        ],
    )
    def test_rejects_unsafe_or_unsupported(self, expression):
        assert "error" in self._calc(expression)

    def test_division_by_zero(self):
        assert self._calc("1 / 0") == {"error": "division by zero"}

    def test_pct_change_from_zero(self):
        assert "error" in self._calc("pct_change(0, 5)")

    def test_huge_exponent_rejected(self):
        assert "error" in self._calc("9 ** 9 ** 9")
        assert "error" in self._calc("10 ** 100000")

    def test_non_finite_result(self):
        assert "error" in self._calc("exp(1000)")

    def test_empty_and_syntax_errors(self):
        assert "error" in self._calc("")
        assert "error" in self._calc("1 +")

    def test_too_long(self):
        assert "error" in self._calc("1+" * 2000 + "1")

    def test_schema_shape(self):
        schema = CalculateTool().schema()
        assert schema["name"] == "calculate"
        assert schema["input_schema"]["required"] == ["expression"]


# ── RegexExtractTool ──────────────────────────────────────────────────────────


class TestRegexExtractTool:
    ROWS = [
        {"id": "1", "msg": "login from 10.0.0.1 failed", "user": "alice"},
        {"id": "2", "msg": "login from 10.0.0.2 ok, then 10.0.0.3", "user": "bob"},
        {"id": "3", "msg": "no address here", "user": "carol"},
        {"id": "4", "msg": "LOGIN from 192.168.1.9", "user": "dave"},
    ]

    def _tool(self):
        tool = RegexExtractTool()
        tool.setup(_make_csv_gz(self.ROWS))
        return tool

    def test_column_matches_and_counts(self):
        r = self._tool().run({"pattern": r"\d+\.\d+\.\d+\.\d+", "column": "msg"})
        assert [m["match"] for m in r["matches"]] == [
            "10.0.0.1", "10.0.0.2", "10.0.0.3", "192.168.1.9",
        ]
        assert r["match_count"] == 4
        assert r["rows_with_match"] == 3
        assert r["rows_scanned"] == 4
        assert r["truncated"] is False

    def test_row_ids_returned(self):
        r = self._tool().run({"pattern": r"10\.0\.0\.\d", "column": "msg"})
        assert [m["row"] for m in r["matches"]] == [1, 2, 2]

    def test_capture_groups(self):
        r = self._tool().run({"pattern": r"from (\d+)\.(\d+)", "column": "msg"})
        assert r["matches"][0]["groups"] == ["10", "0"]

    def test_named_groups(self):
        r = self._tool().run({"pattern": r"from (?P<first>\d+)\.", "column": "msg"})
        assert r["matches"][0]["named"] == {"first": "10"}

    def test_ignore_case(self):
        tool = self._tool()
        assert tool.run({"pattern": "login", "column": "msg"})["match_count"] == 2
        assert tool.run({"pattern": "login", "column": "msg", "ignore_case": True})["match_count"] == 3

    def test_max_matches_truncates_but_counts_all(self):
        r = self._tool().run({"pattern": r"10\.0\.0\.\d", "column": "msg", "max_matches": 1})
        assert len(r["matches"]) == 1
        assert r["match_count"] == 3
        assert r["truncated"] is True

    def test_text_mode(self):
        r = RegexExtractTool().run({"pattern": r"[A-Z]{3}-\d+", "text": "see ABC-12 and XYZ-9"})
        assert [m["match"] for m in r["matches"]] == ["ABC-12", "XYZ-9"]
        assert r["matches"][0]["row"] is None

    def test_no_match(self):
        r = self._tool().run({"pattern": "zzz", "column": "msg"})
        assert r["matches"] == [] and r["match_count"] == 0

    def test_works_on_jsonl(self):
        tool = RegexExtractTool()
        tool.setup(_make_jsonl_gz([{"a": "x1"}, {"a": "y22"}]))
        r = tool.run({"pattern": r"\d+", "column": "a"})
        assert [m["match"] for m in r["matches"]] == ["1", "22"]

    def test_unknown_column(self):
        r = self._tool().run({"pattern": "a", "column": "nope"})
        assert "unknown column" in r["error"]

    def test_requires_exactly_one_source(self):
        assert "error" in self._tool().run({"pattern": "a"})
        assert "error" in self._tool().run({"pattern": "a", "column": "msg", "text": "x"})

    def test_column_without_chunk(self):
        assert "error" in RegexExtractTool().run({"pattern": "a", "column": "msg"})

    def test_invalid_regex(self):
        assert "invalid regex" in self._tool().run({"pattern": "(", "column": "msg"})["error"]

    def test_missing_pattern(self):
        assert "error" in self._tool().run({"column": "msg"})

    def test_pattern_too_long(self):
        assert "error" in self._tool().run({"pattern": "a" * 501, "column": "msg"})

    @pytest.mark.parametrize("pattern", ["(a+)+$", "(.*)*x", "(\\w+\\s*)+", "(a|b*)+"])
    def test_nested_quantifiers_rejected(self, pattern):
        assert "nested quantifiers" in RegexExtractTool().run({"pattern": pattern, "text": "aaa"})["error"]

    def test_long_values_clipped(self):
        r = RegexExtractTool().run({"pattern": "a+", "text": "a" * 1500})
        assert len(r["matches"][0]["match"]) <= 501

    def test_schema_shape(self):
        schema = RegexExtractTool().schema()
        assert schema["name"] == "regex_extract"
        assert schema["input_schema"]["required"] == ["pattern"]
