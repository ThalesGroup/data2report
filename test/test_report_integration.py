import gzip
import os.path

import pytest
from boto3.session import Session

from conftest import get_resources_folder
from data2report import run_report
from s3_utils import get_reports_bucket, clear_folder, get_data2report_prefix
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
        "model_id": "anthropic.claude-3-5-sonnet-20240620-v1:0",
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
