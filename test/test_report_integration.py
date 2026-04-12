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
import gzip
import json
import os.path

import pytest
from boto3.session import Session

from conftest import get_resources_folder, get_config
from data2report import run_report
from lambda_function import lambda_handler
from s3_utils import (
    get_reports_bucket,
    clear_folder,
    get_data2report_prefix,
    upload_file,
)
from utils import init_env_from_file

_TEST_BUCKET_NAME = "data2report"


@pytest.fixture(autouse=True, scope="module")
def set_aws_api_key():
    init_env_from_file()


@pytest.fixture()
def reports_bucket(monkeypatch):
    monkeypatch.setenv("REPORTS_BUCKET", _TEST_BUCKET_NAME)
    monkeypatch.setenv("DATA2REPORTS_PREFIX", "temp/data2report/")
    yield get_reports_bucket()
    monkeypatch.delenv("REPORTS_BUCKET", raising=False)
    monkeypatch.delenv("DATA2REPORTS_PREFIX", raising=False)


_CONF = {
    "id": "test_report",
    "name": "Test Report",
    "input": {"format": "csv", "header": True},
    "llm": {
        "model_id": "inference-profile/us.anthropic.claude-sonnet-4-6",
        "system_prompt": "Here is a web attacks dataset, please analyze it and return ONLY interesting finding for investigation. Return the result in jsonl format top insights. Only actionable ones (with specific urls). Not about specific attacks. do not include any prefix or suffix. only jsonl. One json object per line with finding title and description. Here is the data:\n",
        "temperature": 0.3,
        "max_tokens": 100,
    },
    "report": {
        "chunk_size": 10,
        "incremental": True,
        "max_workers": 1,
        "max_records": 20,
    },
}


def test_run_report(reports_folder, reports_bucket):
    clear_folder(
        reports_bucket,
        get_data2report_prefix() + "reports/report=test_report",
        session=Session(),
    )
    input_file = os.path.join(get_resources_folder(), "urls.csv.gz")
    result = run_report(
        input_file,
        configuration=_CONF,
    )
    output_folder = result["output_folder"]
    with gzip.open(os.path.join(output_folder, "final_report.gz"), "rt") as f:
        output_lines = f.readlines()
    assert result["llm_usage"]["output_tokens"] > 0
    assert len(output_lines) > 0


def test_lambda_handler(reports_folder, reports_bucket, csv_file_with_500_lines):
    session = Session()
    clear_folder(
        reports_bucket, get_data2report_prefix() + "reports/report=test_report", session
    )
    conf = get_config("test_report")
    b64_conf = base64.b64encode(json.dumps(conf).encode("utf-8"))
    result = lambda_handler({"operation": "upload_report", "data": b64_conf}, None)
    assert result["s3_key"] == "data2report/configuration/test_report.json"
    input_key = "tmp/input/input.csv"
    if csv_file_with_500_lines.endswith(".gz"):
        input_key += ".gz"
    upload_file(get_reports_bucket(), csv_file_with_500_lines, input_key, session)
    full_key = f"s3://{get_reports_bucket()}/{input_key}"
    result = lambda_handler(
        {"operation": "run_report", "report_id": conf["id"], "input_key": full_key},
        None,
    )
    assert result["report_id"] == "test_report"
    assert isinstance(result["run_id"], str) and len(result["run_id"]) == 10 and result["run_id"].count("-") == 2
    assert result["chunks"] == 1
    assert result["records"] == 500
    assert result["records_limit_reached"] is False
    assert result["stopped"] is False
    assert result["chunks_skipped"] == 0
    assert result["duration_seconds"] > 0
    assert result["longest_chunk_duration_seconds"] > 0
    assert result["llm_usage"]["input_tokens"] > 0
    assert result["llm_usage"]["output_tokens"] > 0
    assert "s3_uri" in result
    assert result["s3_uri"].startswith("s3://data2report")
