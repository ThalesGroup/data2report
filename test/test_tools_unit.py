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
import tools.cve_search as cve_search_module
from tools.cve_search import CveSearchTool
from tools.query_data import QueryDataTool, load_chunk_into_sqlite
from tools.regex_extract import RegexExtractTool
from tools.registry import get_tool, list_tools, REGISTRY
from tools.template_cluster import TemplateClusterTool, to_template
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
        assert "template_cluster" in names
        assert "cve_search" in names

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


# ── TemplateClusterTool ───────────────────────────────────────────────────────


class TestToTemplate:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("took 120 ms", "took <NUM> ms"),
            ("took 3.5 s", "took <NUM> s"),
            ("login from 10.0.0.1 failed", "login from <IP> failed"),
            ("user a@b.com logged in", "user <EMAIL> logged in"),
            ("id 123e4567-e89b-12d3-a456-426614174000 done", "id <UUID> done"),
            ("at 2026-11-05T10:20:30Z ok", "at <TS> ok"),
            ("at 2026-11-05 ok", "at <TS> ok"),
            ("at 10:20:30 ok", "at <TIME> ok"),
            ("hash d41d8cd98f00b204e9800998ecf8427e seen", "hash <HEX> seen"),
            ("addr 0xdeadbeef", "addr <HEX>"),
            ("session abc123def456ghi7 expired", "session <ID> expired"),
            ("a   b\t c", "a b c"),
            ("user123 stays", "user123 stays"),
            ("no variables", "no variables"),
        ],
    )
    def test_masks(self, text, expected):
        assert to_template(text) == expected


class TestTemplateClusterTool:
    ROWS = (
        [{"id": str(i), "msg": f"login from 10.0.0.{i} failed after {i} tries"} for i in range(1, 6)]
        + [{"id": "6", "msg": "disk full on /dev/sda1"}]
        + [{"id": "7", "msg": "disk full on /dev/sda1"}]
        + [{"id": "8", "msg": "service restarted"}]
        + [{"id": "9", "msg": ""}]
    )

    def _tool(self, rows=None):
        tool = TemplateClusterTool()
        tool.setup(_make_csv_gz(rows or self.ROWS))
        return tool

    def test_groups_and_counts(self):
        r = self._tool().run({"column": "msg"})
        top = r["templates"][0]
        assert top["template"] == "login from <IP> failed after <NUM> tries"
        assert top["count"] == 5
        assert top["percent"] == 62.5  # share of non-empty rows (5 of 8)
        assert r["distinct_templates"] == 3
        assert r["rows_scanned"] == 9
        assert r["empty_rows"] == 1
        assert r["truncated"] is False

    def test_sorted_by_count_desc(self):
        counts = [t["count"] for t in self._tool().run({"column": "msg"})["templates"]]
        assert counts == sorted(counts, reverse=True)

    def test_example_and_row(self):
        top = self._tool().run({"column": "msg"})["templates"][0]
        assert top["example"] == "login from 10.0.0.1 failed after 1 tries"
        assert top["example_row"] == 1

    def test_ascending_returns_rarest_first(self):
        r = self._tool().run({"column": "msg", "ascending": True})
        assert r["templates"][0]["template"] == "service restarted"

    def test_max_templates_truncates(self):
        r = self._tool().run({"column": "msg", "max_templates": 1})
        assert len(r["templates"]) == 1
        assert r["distinct_templates"] == 3
        assert r["truncated"] is True

    def test_works_on_jsonl(self):
        tool = TemplateClusterTool()
        tool.setup(_make_jsonl_gz([{"m": "err 1"}, {"m": "err 2"}, {"m": "ok"}]))
        r = tool.run({"column": "m"})
        assert r["templates"][0] == {
            "template": "err <NUM>", "count": 2, "percent": 66.7,
            "example": "err 1", "example_row": 1,
        }

    def test_unknown_column(self):
        assert "unknown column" in self._tool().run({"column": "nope"})["error"]

    def test_missing_column(self):
        assert "error" in self._tool().run({})

    def test_bad_max_templates(self):
        assert "error" in self._tool().run({"column": "msg", "max_templates": "x"})

    def test_no_chunk(self):
        assert "error" in TemplateClusterTool().run({"column": "msg"})

    def test_long_values_clipped(self):
        r = self._tool([{"m": "x" * 900}]).run({"column": "m"})
        assert len(r["templates"][0]["example"]) <= 301

    def test_schema_shape(self):
        schema = TemplateClusterTool().schema()
        assert schema["name"] == "template_cluster"
        assert schema["input_schema"]["required"] == ["column"]


# ── CveSearchTool ─────────────────────────────────────────────────────────────


def _nvd_cve(cve_id="CVE-2021-44228", kev=True):
    cve = {
        "id": cve_id,
        "published": "2021-12-10T10:15:09.143",
        "lastModified": "2024-01-01T00:00:00.000",
        "vulnStatus": "Analyzed",
        "descriptions": [
            {"lang": "es", "value": "descripcion"},
            {"lang": "en", "value": "Apache Log4j2 JNDI features allow RCE."},
        ],
        "metrics": {
            "cvssMetricV2": [{"cvssData": {"version": "2.0", "baseScore": 9.3}, "baseSeverity": "HIGH"}],
            "cvssMetricV31": [
                {"type": "Secondary", "cvssData": {"version": "3.1", "baseScore": 8.0, "baseSeverity": "HIGH", "vectorString": "SEC"}},
                {"type": "Primary", "cvssData": {"version": "3.1", "baseScore": 10.0, "baseSeverity": "CRITICAL", "vectorString": "CVSS:3.1/AV:N"}},
            ],
        },
        "weaknesses": [{"description": [
            {"lang": "en", "value": "CWE-502"}, {"lang": "en", "value": "CWE-20"},
            {"lang": "en", "value": "NVD-CWE-Other"},
        ]}],
        "references": [{"url": f"https://example.com/{i}"} for i in range(6)],
    }
    if kev:
        cve["cisaExploitAdd"] = "2021-12-10"
    return {"cve": cve}


@pytest.fixture
def nvd(monkeypatch):
    """Patch the NVD HTTP call; returns a list recording the params of each request."""
    class Calls(list):
        response = None

    cve_search_module._cache.clear()
    calls = Calls()
    response = {"totalResults": 1, "vulnerabilities": [_nvd_cve()]}

    def fake_get(params):
        calls.append(params)
        return response

    monkeypatch.setattr(cve_search_module, "_http_get_json", fake_get)
    calls.response = response
    return calls


class TestCveSearchTool:
    def test_lookup_by_id(self, nvd):
        r = CveSearchTool().run({"cve_id": "cve-2021-44228"})
        assert nvd == [{"cveId": "CVE-2021-44228"}]
        item = r["results"][0]
        assert item["id"] == "CVE-2021-44228"
        assert item["cvss"] == {"version": "3.1", "score": 10.0, "severity": "CRITICAL", "vector": "CVSS:3.1/AV:N"}
        assert item["description"] == "Apache Log4j2 JNDI features allow RCE."
        assert item["cwes"] == ["CWE-20", "CWE-502"]
        assert item["in_cisa_kev"] is True
        assert len(item["references"]) == 3
        assert r["total_results"] == 1 and r["truncated"] is False

    def test_falls_back_to_older_cvss(self, nvd):
        cve = nvd.response["vulnerabilities"][0]["cve"]
        del cve["metrics"]["cvssMetricV31"]
        item = CveSearchTool().run({"cve_id": "CVE-2021-44228"})["results"][0]
        assert item["cvss"]["version"] == "2.0" and item["cvss"]["score"] == 9.3

    def test_missing_metrics_and_kev(self, nvd):
        nvd.response["vulnerabilities"] = [_nvd_cve(kev=False)]
        nvd.response["vulnerabilities"][0]["cve"]["metrics"] = {}
        item = CveSearchTool().run({"cve_id": "CVE-2021-44228"})["results"][0]
        assert item["cvss"] is None and item["in_cisa_kev"] is False

    def test_keyword_search_params(self, nvd):
        CveSearchTool().run({"keyword": "log4j", "severity": "critical", "max_results": 3})
        assert nvd == [{"keywordSearch": "log4j", "resultsPerPage": 3, "cvssV3Severity": "CRITICAL"}]

    def test_max_results_capped(self, nvd):
        CveSearchTool().run({"keyword": "x", "max_results": 500})
        assert nvd[0]["resultsPerPage"] == 10

    def test_truncated_when_more_results_exist(self, nvd):
        nvd.response["totalResults"] = 42
        r = CveSearchTool().run({"keyword": "apache"})
        assert r["total_results"] == 42 and r["truncated"] is True

    def test_long_description_clipped(self, nvd):
        nvd.response["vulnerabilities"][0]["cve"]["descriptions"] = [{"lang": "en", "value": "x" * 2000}]
        item = CveSearchTool().run({"cve_id": "CVE-2021-44228"})["results"][0]
        assert len(item["description"]) <= 601

    def test_unknown_cve(self, nvd):
        nvd.response["vulnerabilities"] = []
        nvd.response["totalResults"] = 0
        assert "not found" in CveSearchTool().run({"cve_id": "CVE-1999-0001"})["error"]

    def test_keyword_no_results_is_not_an_error(self, nvd):
        nvd.response["vulnerabilities"] = []
        nvd.response["totalResults"] = 0
        assert CveSearchTool().run({"keyword": "zzzz"})["results"] == []

    def test_results_are_cached(self, nvd):
        tool = CveSearchTool()
        tool.run({"cve_id": "CVE-2021-44228"})
        tool.run({"cve_id": "CVE-2021-44228"})
        assert len(nvd) == 1

    @pytest.mark.parametrize(
        "args",
        [
            {},
            {"cve_id": "CVE-2021-44228", "keyword": "log4j"},
            {"cve_id": "not-a-cve"},
            {"cve_id": "CVE-2021-44228; DROP"},
            {"keyword": "x" * 101},
            {"keyword": "log4j", "severity": "SEVERE"},
            {"keyword": "log4j", "max_results": "many"},
        ],
    )
    def test_invalid_input_makes_no_request(self, nvd, args):
        assert "error" in CveSearchTool().run(args)
        assert nvd == []

    def test_network_error_returned_not_raised(self, monkeypatch):
        cve_search_module._cache.clear()

        def boom(params):
            raise RuntimeError("could not reach NVD: down")

        monkeypatch.setattr(cve_search_module, "_http_get_json", boom)
        assert CveSearchTool().run({"keyword": "log4j"}) == {"error": "could not reach NVD: down"}

    def test_schema_shape(self):
        schema = CveSearchTool().schema()
        assert schema["name"] == "cve_search"
        assert set(schema["input_schema"]["properties"]) == {"cve_id", "keyword", "severity", "max_results"}


class TestCveSearchHttp:
    """The real _http_get_json, with urlopen mocked."""

    class _Resp:
        def __init__(self, body):
            self._body = body

        def read(self, n=-1):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def test_success_sends_api_key_and_params(self, monkeypatch):
        seen = {}

        def fake_urlopen(request, timeout):
            seen["url"], seen["headers"], seen["timeout"] = request.full_url, dict(request.header_items()), timeout
            return self._Resp(b'{"totalResults": 0, "vulnerabilities": []}')

        monkeypatch.setenv("NVD_API_KEY", "secret")
        monkeypatch.setattr(cve_search_module.urllib.request, "urlopen", fake_urlopen)
        data = cve_search_module._http_get_json({"keywordSearch": "a b"})
        assert data["totalResults"] == 0
        assert seen["url"].endswith("?keywordSearch=a+b")
        assert seen["headers"]["Apikey"] == "secret"
        assert seen["timeout"] == 10

    @pytest.mark.parametrize("code,text", [(403, "rate limit"), (429, "rate limit"), (404, "404"), (500, "HTTP 500")])
    def test_http_errors(self, monkeypatch, code, text):
        def fake_urlopen(request, timeout):
            raise cve_search_module.urllib.error.HTTPError(request.full_url, code, "x", {}, None)

        monkeypatch.setattr(cve_search_module.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(RuntimeError, match=text):
            cve_search_module._http_get_json({"cveId": "CVE-2021-44228"})

    def test_connection_error(self, monkeypatch):
        def fake_urlopen(request, timeout):
            raise cve_search_module.urllib.error.URLError("no route")

        monkeypatch.setattr(cve_search_module.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(RuntimeError, match="could not reach NVD"):
            cve_search_module._http_get_json({})

    def test_invalid_json(self, monkeypatch):
        monkeypatch.setattr(
            cve_search_module.urllib.request, "urlopen", lambda r, timeout: self._Resp(b"<html>")
        )
        with pytest.raises(RuntimeError, match="invalid response"):
            cve_search_module._http_get_json({})
