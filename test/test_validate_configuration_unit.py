import pytest

from conf_utils import validate_configuration
from conftest import get_config

@pytest.fixture
def valid_configuration() -> dict:
    return get_config("test_report")

class TestValidateConfiguration:
    def test_valid_without_report_id(self, valid_configuration):
        assert validate_configuration(valid_configuration, None) == []

    def test_missing_id_field(self, valid_configuration):
        cfg = {**valid_configuration}
        cfg.pop("id")
        assert "Missing report id" in validate_configuration(cfg, None)

    def test_empty_id_value(self, valid_configuration):
        cfg = {**valid_configuration, "id": ""}
        assert "Missing report id" in validate_configuration(cfg, None)

    def test_mismatched_report_id(self, valid_configuration):
        assert "Report id in configuration does not match the provided report_id" in validate_configuration(valid_configuration, "wrong_id")

    def test_missing_llm_section(self, valid_configuration):
        cfg = valid_configuration
        cfg.pop("llm")
        assert "Missing 'llm' section in configuration" in validate_configuration(cfg, None)

    def test_empty_llm_section(self, valid_configuration):
        cfg = valid_configuration
        cfg["llm"] = {}
        assert "Missing 'llm' section in configuration" not in validate_configuration(cfg, None)