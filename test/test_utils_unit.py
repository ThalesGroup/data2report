import os

from utils import get_project_folder, get_current_day


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
