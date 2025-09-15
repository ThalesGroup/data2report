from conftest import get_config
from data2report import run_report


def test_generate_empty_report(reports_folder, empty_file):
    result = run_report(empty_file, configuration=get_config("test_report"))
    assert result["work_folder"] is not None
    assert result["output_folder"] is not None
    assert result["chunks"] == 0
    assert result["records"] == 0
