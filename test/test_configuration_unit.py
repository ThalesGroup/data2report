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

import pytest

from conf_utils import (
    get_conf_folder,
    get_config_file,
    save_report,
    list_reports,
    get_report_config,
)
from conftest import get_config


@pytest.fixture
def valid_configuration() -> dict:
    return get_config("test_report")


class TestConfiguration:
    def test_get_conf_folder(self):
        folder = get_conf_folder()
        assert folder.endswith("configuration")

    def test_get_config_file(self, valid_configuration):
        conf_file = get_config_file(valid_configuration["id"])
        assert conf_file.endswith(f"configuration/{valid_configuration['id']}.json")

    def test_save_report(self, reports_folder, valid_configuration):
        assert list_reports() == []
        save_report(valid_configuration)
        assert list_reports() == [valid_configuration["id"]]
        config = get_report_config(valid_configuration["id"])
        assert config == valid_configuration
