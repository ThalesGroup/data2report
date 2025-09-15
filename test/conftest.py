import json
import os
import tempfile

import pytest
from typing import Generator


def get_resources_folder() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")


def get_config(name: str) -> dict:
    conf_file = os.path.join(get_resources_folder(), f"{name}.json")
    return json.load(open(conf_file))


@pytest.fixture
def reports_folder(monkeypatch) -> Generator[str, None, None]:
    with tempfile.TemporaryDirectory() as f:
        monkeypatch.setenv("REPORTS_FOLDER", f)
        yield f


@pytest.fixture
def empty_file() -> Generator[str, None, None]:
    with tempfile.NamedTemporaryFile() as f:
        with open(f.name, "w") as _:
            pass
        yield f.name
