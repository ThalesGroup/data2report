import os

from utils import get_project_folder


def test_get_project_folder():
    project_folder = get_project_folder()
    assert os.path.exists(project_folder)
