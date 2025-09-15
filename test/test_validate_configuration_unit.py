import unittest

from conf_utils import validate_configuration
from conftest import get_config

VALID_CONFIGURATION = get_config("test_report")


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