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

    def test_missing_model_id(self, valid_configuration):
        cfg = {**valid_configuration}
        cfg["llm"].pop("model_id")
        assert "llm.model_id is required" in validate_configuration(cfg, None)

    def test_bad_temperature(self, valid_configuration):
        cfg = {**valid_configuration}
        cfg["llm"]["temperature"] = 1.5
        assert "llm.temperature must be between 0 and 1" in \
               validate_configuration(cfg, None)

    def test_negative_max_tokens(self, valid_configuration):
        cfg = {**valid_configuration}
        cfg["llm"]["max_tokens"] = -10
        assert "llm.max_tokens must be a positive integer" in \
               validate_configuration(cfg, None)

    def test_negative_chunk_size(self, valid_configuration):
        cfg = {**valid_configuration}
        cfg["report"]["chunk_size"] = -5
        assert "report.chunk_size must be a positive integer" in \
               validate_configuration(cfg, None)

    def test_incremental_workers_gt1(self, valid_configuration):
        cfg = {**valid_configuration}
        cfg["report"]["incremental"] = True
        cfg["report"]["max_workers"] = 2
        assert "For incremental mode, report.max_workers must be 1" in \
               validate_configuration(cfg, None)

    def test_parallel_workers_lt1(self, valid_configuration):
        cfg = {**valid_configuration}
        cfg["report"]["incremental"] = False
        cfg["report"]["max_workers"] = 0
        assert "report.max_workers must be >=1" in \
               validate_configuration(cfg, None)