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

from rest import app
from utils import get_final_report_name, get_report_folder


class TestRestAppErrors:
    def test_verify_sql_method_not_allowed(self):
        result = app.test_client().post("/ping")
        assert result.status_code == 405


class TestRestApp:

    def test_pint(self):
        result = app.test_client().get("/ping")
        assert result.status_code == 200


class TestGetReport:
    @pytest.fixture
    def write_report(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REPORTS_FOLDER", str(tmp_path))

        def _write(content: str, report_id="r1", run_id="run1"):
            folder = get_report_folder(report_id, run_id)
            os.makedirs(folder, exist_ok=True)
            with gzip.open(os.path.join(folder, get_final_report_name()), "wt") as f:
                f.write(content)

        return _write

    def _get(self, query="id=r1&run_id=run1"):
        return app.test_client().get(f"/report?{query}")

    def test_default_returns_raw_text(self, write_report):
        write_report('{"a": 1}\n{"a": 2}\n')
        r = self._get()
        assert r.status_code == 200
        assert r.mimetype == "text/plain"
        assert r.get_data(as_text=True) == '{"a": 1}\n{"a": 2}\n'

    def test_format_json_converts_jsonl_to_array(self, write_report):
        write_report('{"a": 1}\n\n{"a": "é"}\n')
        r = self._get("id=r1&run_id=run1&format=json")
        assert r.mimetype == "application/json"
        assert json.loads(r.get_data(as_text=True)) == [{"a": 1}, {"a": "é"}]

    def test_format_json_leaves_csv_as_text(self, write_report):
        write_report("a,b\n1,2\n")
        r = self._get("id=r1&run_id=run1&format=json")
        assert r.mimetype == "text/plain"
        assert r.get_data(as_text=True) == "a,b\n1,2\n"

    def test_format_json_leaves_mixed_lines_as_text(self, write_report):
        write_report('{"a": 1}\nnot json\n')
        assert self._get("id=r1&run_id=run1&format=json").mimetype == "text/plain"

    def test_format_json_leaves_non_object_lines_as_text(self, write_report):
        write_report("1\n2\n")
        assert self._get("id=r1&run_id=run1&format=json").mimetype == "text/plain"

    def test_missing_report_does_not_leak_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REPORTS_FOLDER", str(tmp_path))
        r = self._get()
        assert r.status_code == 404
        assert r.get_json() == {"error": "Report not found"}
        assert str(tmp_path) not in r.get_data(as_text=True)
