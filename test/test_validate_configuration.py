import unittest

from conf_utils import validate_configuration

VALID_CONFIGURATION = {
    "id": "test_report",
    "name": "Test Report",
    "llm": {
        "model_id": "anthropic.claude-3-5-sonnet-20240620-v1:0",
        "system_prompt": (
            "Analyze my data and return the most interesting findings. "
            "Output should be in JSONL format with the following fields: "
            "start_time, end_time, finding_title, description. "
            "Ensure the JSONL is well-formed.\n"
            "Current findings: {findings}\nData: {data}"
        ),
        "temperature": 0.3,
        "max_tokens": 1_000,
    },
    "report": {
        "chunk_size": 10,
        "incremental": True,
        "max_workers": 1,
    },
}


class TestValidateConfiguration(unittest.TestCase):
    def test_valid_without_report_id(self):
        self.assertEqual(validate_configuration(VALID_CONFIGURATION, None), [])

    def test_valid_with_matching_report_id(self):
        self.assertEqual(
            validate_configuration(VALID_CONFIGURATION, "test_report"), []
        )

    def test_missing_id_field(self):
        cfg = {**VALID_CONFIGURATION}
        cfg.pop("id")
        self.assertIn(
            "Missing report id",
            validate_configuration(cfg, None),
        )

    def test_empty_id_value(self):
        cfg = {**VALID_CONFIGURATION, "id": ""}
        self.assertIn(
            "Missing report id",
            validate_configuration(cfg, None),
        )

    def test_mismatched_report_id(self):
        self.assertIn(
            "Report id in configuration does not match the provided report_id",
            validate_configuration(VALID_CONFIGURATION, "wrong_id"),
        )