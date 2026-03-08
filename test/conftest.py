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

import contextlib
import csv
import gzip
import json
import os
import tempfile
from unittest.mock import patch

import pytest
from typing import Generator


def get_resources_folder() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")


def get_config(name: str) -> dict:
    conf_file = os.path.join(get_resources_folder(), f"{name}.json")
    return json.load(open(conf_file))


@pytest.fixture
def reports_folder(monkeypatch) -> Generator[str, None, None]:
    with tempfile.TemporaryDirectory() as f:
        monkeypatch.setenv("REPORTS_FOLDER", f)
        yield f


@pytest.fixture
def empty_file() -> Generator[str, None, None]:
    with tempfile.NamedTemporaryFile() as f:
        with open(f.name, "w") as _:
            pass
        yield f.name


@pytest.fixture
def csv_file_with_500_lines() -> Generator[str, None, None]:
    yield from _generate_csv(500, True)


@pytest.fixture
def csv_file_with_1k_lines() -> Generator[str, None, None]:
    yield from _generate_csv(1000, True)


@pytest.fixture
def csv_gz_file_with_1k_lines() -> Generator[str, None, None]:
    yield from _generate_csv(1000, True, True)


@pytest.fixture
def csv_file_with_1k_lines_no_header() -> Generator[str, None, None]:
    yield from _generate_csv(1000, False)


@pytest.fixture(params=["csv_gz_file_with_1k_lines", "csv_file_with_1k_lines"])
def csv_and_csv_gz_with_1k_lines(
    request, csv_gz_file_with_1k_lines, csv_file_with_1k_lines
):
    if request.param == "csv_gz_file_with_1k_lines":
        return csv_gz_file_with_1k_lines
    else:
        return csv_file_with_1k_lines


def _generate_csv(
    lines: int, header: bool, gz: bool = False
) -> Generator[str, None, None]:
    with tempfile.NamedTemporaryFile(suffix=".csv.gz" if gz else ".csv") as temp_f:
        with gzip.open(temp_f.name, "wt") if gz else open(temp_f.name, "w") as open_f:
            writer = csv.DictWriter(open_f, fieldnames=["id", "name", "value"])
            if header:
                writer.writeheader()
            for i in range(lines):
                writer.writerow({"id": i, "name": f"name_{i}", "value": f"value_{i}"})
        yield temp_f.name


@pytest.fixture
def report_for_analytics() -> Generator[str, None, None]:
    with tempfile.NamedTemporaryFile() as temp_f:
        with open(temp_f.name, "w") as open_f:
            writer = csv.DictWriter(open_f, fieldnames=["id", "value"])
            for i in range(10):
                for j in range(100):
                    writer.writerow({"id": i, "value": j})
        yield temp_f.name


@contextlib.contextmanager
def mock_llm(content: str = "Report", input_tokens: int = 10, output_tokens: int = 20):
    mocked_response = {
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        "content": content,
    }
    with patch("report_processing.invoke_llm", return_value=mocked_response):
        yield
