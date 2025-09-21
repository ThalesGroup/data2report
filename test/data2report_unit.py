import os
from unittest.mock import patch

import pytest

from conftest import get_config
from data2report import run_report


def test_generate_empty_report(reports_folder, empty_file):
    result = run_report(empty_file, configuration=get_config("test_report"))
    assert result["work_folder"] is not None
    assert result["output_folder"] is not None
    assert result["chunks"] == 0
    assert result["records"] == 0
    assert result["llm_usage"]["input_tokens"] == 0
    assert result["llm_usage"]["output_tokens"] == 0


@pytest.mark.parametrize("incremental", [True, False])
def test_generate_report(reports_folder, csv_file_with_1k_lines, incremental: bool):
    mocked_response = {
        "usage": {"input_tokens": 10, "output_tokens": 20},
        "content": "Report",
    }
    config = get_config("test_report")
    if incremental:
        config["report"]["incremental"] = True
        config["report"]["max_workers"] = 1
    else:
        config["report"]["incremental"] = False
        config["report"]["max_workers"] = 3
    with patch("report_processing.invoke_llm", return_value=mocked_response):
        configuration = config
        configuration["report"]["incremental"] = incremental
        result = run_report(
            csv_file_with_1k_lines,
            configuration=configuration,
        )
        assert result["work_folder"] is not None
        assert result["output_folder"] is not None
        assert result["chunks"] == 2
        assert result["records"] == 1000
        assert result["llm_usage"]["input_tokens"] == 20
        assert result["llm_usage"]["output_tokens"] == 40
        assert result["duration_seconds"] >= 0
        assert result["longest_chunk_duration_seconds"] >= 0
        assert os.path.exists(result["output_folder"])
        assert os.path.exists(os.path.join(result["output_folder"], "final_report.gz"))
        assert os.path.exists(os.path.join(result["output_folder"], "result.json"))
