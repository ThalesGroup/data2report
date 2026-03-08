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

import pytest

from conftest import get_config, mock_llm
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
    config = get_config("test_report")
    if incremental:
        config["report"]["incremental"] = True
        config["report"]["max_workers"] = 1
    else:
        config["report"]["incremental"] = False
        config["report"]["max_workers"] = 3
    with mock_llm():
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


def test_generate_report_change_input(
    reports_folder, csv_file_with_1k_lines, csv_file_with_500_lines
):
    with mock_llm():
        config = get_config("test_report")
        result = run_report(csv_file_with_1k_lines, configuration=config, force=False)
        assert result["chunks_skipped"] == 0
        result = run_report(csv_file_with_1k_lines, configuration=config, force=False)
        assert result["chunks_skipped"] == 2
        result = run_report(csv_file_with_1k_lines, configuration=config, force=True)
        assert result["chunks_skipped"] == 0
        config["report"]["chunk_size"] = 400
        result = run_report(csv_file_with_1k_lines, configuration=config, force=False)
        assert result["chunks_skipped"] == 0
        result = run_report(csv_file_with_1k_lines, configuration=config, force=False)
        assert result["chunks_skipped"] == 3
        result = run_report(csv_file_with_500_lines, configuration=config, force=False)
        assert result["chunks_skipped"] == 0


def test_generate_report_jsonl_output_mixed_json(
    reports_folder, csv_file_with_1k_lines
):
    config = get_config("test_report")
    config["report"]["output_format"] = "jsonl"
    with mock_llm("{}\n\n{}\nInvalid JSON\n{\n}\nPrefix{}Suffix"):
        result = run_report(
            csv_file_with_1k_lines,
            configuration=config,
        )
        output_file = os.path.join(result["output_folder"], "final_report.gz")
        result = []
        with gzip.open(output_file, "rt") as out_f:
            for line in out_f:
                result.append(json.loads(line))
        assert result == [{}, {}, {}]
