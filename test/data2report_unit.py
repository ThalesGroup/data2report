import tempfile
from typing import Generator

from conftest import get_config
from data2report import run_report
import pytest


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


def test_generate_empty_report(reports_folder, empty_file):
    result = run_report(empty_file, configuration=get_config("test_report"))
    assert result["work_folder"] is not None
    assert result["output_folder"] is not None
    assert result["chunks"] == 0
    assert result["records"] == 0
