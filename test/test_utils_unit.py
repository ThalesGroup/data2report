import os

from utils import get_project_folder, get_current_day, get_json_lines


def test_get_project_folder():
    project_folder = get_project_folder()
    assert os.path.exists(project_folder)


def test_get_current_day():
    day = get_current_day()
    assert len(day) == 10
    assert day[4] == "-"
    assert day[7] == "-"
    assert int(day[:4]) > 2000
    assert 1 <= int(day[5:7]) <= 12
    assert 1 <= int(day[8:10]) <= 31


class TestJsonLinesGenerator:
    def test_empty(self):
        assert list(get_json_lines("")) == []

    def test_non_json(self):
        assert list(get_json_lines("not a json\nagain not json")) == []

    def test_valid_json(self):
        assert list(get_json_lines('{}\n{}\n\n{"a": 1}')) == [
            "{}",
            "{}",
            '{"a": 1}',
        ]
        assert list(get_json_lines('{}\n{}\n{"a": 1}')) == ["{}", "{}", '{"a": 1}']

    def test_valid_json_with_spaces(self):
        assert list(get_json_lines("   {}\n   {}\n{}   ")) == ["{}", "{}", "{}"]

    def test_mixed_data(self):
        assert list(get_json_lines("not a json\nprefix{} suffix\nagain not json")) == [
            "{}"
        ]
