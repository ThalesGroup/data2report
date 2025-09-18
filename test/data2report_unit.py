import logging

from conftest import get_config
from data2report import run_report
from unittest.mock import patch


def test_generate_empty_report(reports_folder, empty_file):
    result = run_report(empty_file, configuration=get_config("test_report"))
    assert result["work_folder"] is not None
    assert result["output_folder"] is not None
    assert result["chunks"] == 0
    assert result["records"] == 0
    assert result["llm_usage"]["input_tokens"] == 0
    assert result["llm_usage"]["output_tokens"] == 0


def test_generate_report(reports_folder, csv_file_with_1k_lines):
    mocked_response = {
        "usage": {"input_tokens": 10, "output_tokens": 20},
        "content": "Report",
    }
    with patch("report_processing.invoke_llm", return_value=mocked_response):
        result = run_report(
            csv_file_with_1k_lines, configuration=get_config("test_report")
        )
        assert result["work_folder"] is not None
        assert result["output_folder"] is not None
        assert result["chunks"] == 2
        assert result["records"] == 1000
        assert result["llm_usage"]["input_tokens"] == 20
        assert result["llm_usage"]["output_tokens"] == 40
