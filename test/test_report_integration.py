import gzip
import os.path

import pytest

from conftest import get_resources_folder
from data2report import run_report
from utils import init_env_from_file


@pytest.fixture(autouse=True, scope="module")
def set_aws_api_key():
    init_env_from_file()


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


def test_run_report(reports_folder):
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
