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

from conf_utils import validate_configuration
from conftest import get_config


@pytest.fixture
def valid_configuration() -> dict:
    return get_config("test_report")


class TestValidateConfigurationBasic:
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
        assert (
            "Report id in configuration does not match the provided report_id"
            in validate_configuration(valid_configuration, "wrong_id")
        )


class TestValidateConfigurationLLM:
    def test_missing_llm_section(self, valid_configuration):
        cfg = valid_configuration
        cfg.pop("llm")
        assert "Missing 'llm' section in configuration" in validate_configuration(
            cfg, None
        )

    def test_empty_llm_section(self, valid_configuration):
        cfg = valid_configuration
        cfg["llm"] = {}
        assert "Missing 'llm' section in configuration" not in validate_configuration(
            cfg, None
        )

    def test_missing_model_id(self, valid_configuration):
        cfg = {**valid_configuration}
        cfg["llm"].pop("model_id")
        assert "llm.model_id is required" in validate_configuration(cfg, None)

    def test_llm_model_id_prefix_invalid(self, valid_configuration):
        cfg = {**valid_configuration}
        cfg["llm"] = {**cfg["llm"], "model_id": "some.other-provider-model"}
        errs = validate_configuration(cfg, None)
        assert any(
            "llm.model_id 'some.other-provider-model' is not supported" in e
            for e in errs
        )

    @pytest.mark.parametrize(
        "model_id",
        [
            "anthropic.claude-3-haiku-20240307-v1:0",
            "anthropic.claude-3-5-sonnet-20240620-v1:0",
            "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
            "ai21.jamba-1-5-mini-v1:0",
            "amazon.titan-text-lite-v1",
            "amazon.nova-lite-v1:0",
        ],
    )
    def test_llm_model_id_prefix_valid_examples(self, valid_configuration, model_id):
        cfg = {**valid_configuration}
        cfg["llm"] = {**cfg["llm"], "model_id": model_id}
        errs = validate_configuration(cfg, None)
        assert "llm.model_id is required" not in errs
        assert not any("llm.model_id" in e and "not supported" in e for e in errs)

    def test_llm_system_prompt_missing(self, valid_configuration):
        cfg = {**valid_configuration}
        cfg["llm"] = {**cfg["llm"]}
        cfg["llm"].pop("system_prompt", None)
        errs = validate_configuration(cfg, None)
        assert "llm.system_prompt is required and must be a non-empty string" in errs

    def test_llm_system_prompt_empty(self, valid_configuration):
        cfg = {**valid_configuration}
        cfg["llm"] = {**cfg["llm"], "system_prompt": "   "}
        errs = validate_configuration(cfg, None)
        assert "llm.system_prompt is required and must be a non-empty string" in errs

    def test_bad_temperature(self, valid_configuration):
        cfg = {**valid_configuration}
        cfg["llm"]["temperature"] = 1.5
        assert "llm.temperature must be between 0 and 1" in validate_configuration(
            cfg, None
        )

    def test_negative_max_tokens(self, valid_configuration):
        cfg = {**valid_configuration}
        cfg["llm"]["max_tokens"] = -10
        assert "llm.max_tokens must be a positive integer" in validate_configuration(
            cfg, None
        )


class TestValidateConfigurationReport:
    def test_missing_report_section(self, valid_configuration):
        cfg = {**valid_configuration}
        cfg.pop("report")
        errs = validate_configuration(cfg, None)
        assert "Missing 'report' section in configuration" in errs

    def test_negative_chunk_size(self, valid_configuration):
        cfg = {**valid_configuration}
        cfg["report"]["chunk_size"] = -5
        assert "report.chunk_size must be a positive integer" in validate_configuration(
            cfg, None
        )

    def test_incremental_workers_gt1(self, valid_configuration):
        cfg = {**valid_configuration}
        cfg["report"]["incremental"] = True
        cfg["report"]["max_workers"] = 2
        assert (
            "For incremental mode, report.max_workers must be 1"
            in validate_configuration(cfg, None)
        )

    def test_parallel_workers_lt1(self, valid_configuration):
        cfg = {**valid_configuration}
        cfg["report"]["incremental"] = False
        cfg["report"]["max_workers"] = 0
        assert "report.max_workers must be >=1" in validate_configuration(cfg, None)


class TestValidateConfigurationInput:
    def test_input_non_object(self, valid_configuration):
        cfg = {**valid_configuration, "input": "csv"}
        errs = validate_configuration(cfg, None)
        assert "input must be an object when provided" in errs

    @pytest.mark.parametrize("fmt", ["parquet", "txt", "", None])
    def test_input_format_invalid_values(self, valid_configuration, fmt):
        cfg = {**valid_configuration, "input": {"format": fmt}}
        errs = validate_configuration(cfg, None)
        # If fmt is None => allowed (missing)
        # provided and not csv/jsonl => error
        if fmt is None:
            assert not any("input.format" in e for e in errs)
        else:
            assert "input.format must be 'csv' or 'jsonl'" in errs

    @pytest.mark.parametrize("fmt", ["csv", "jsonl"])
    def test_input_format_valid_values(self, valid_configuration, fmt):
        cfg = {**valid_configuration, "input": {"format": fmt}}
        errs = validate_configuration(cfg, None)
        assert not any("input.format" in e for e in errs)

    def test_input_header_type_invalid(self, valid_configuration):
        cfg = {**valid_configuration, "input": {"header": "true"}}
        errs = validate_configuration(cfg, None)
        assert "input.header must be a boolean" in errs

    @pytest.mark.parametrize("header", [True, False])
    def test_input_header_type_valid(self, valid_configuration, header):
        cfg = {**valid_configuration, "input": {"header": header}}
        errs = validate_configuration(cfg, None)
        assert not any("input.header" in e for e in errs)


class TestValidateConfigurationRootKeys:
    def test_no_unknown_keys(self, valid_configuration):
        errs = validate_configuration(valid_configuration, None)
        assert not any("Unknown keys at root" in e for e in errs)

    def test_one_unknown_key(self, valid_configuration):
        cfg = {**valid_configuration, "extra": 123}
        errs = validate_configuration(cfg, None)
        assert "Unknown keys at root: extra" in errs

    def test_multiple_unknown_keys(self, valid_configuration):
        cfg = {**valid_configuration, "foo": 1, "bar": 2}
        errs = validate_configuration(cfg, None)
        assert "Unknown keys at root: bar, foo" in errs

    def test_allowed_keys_only(self, valid_configuration):
        allowed = {"name", "id", "llm", "report", "input"}
        cfg = {k: valid_configuration[k] for k in allowed if k in valid_configuration}
        errs = validate_configuration(cfg, None)
        assert not any("Unknown keys at root" in e for e in errs)
