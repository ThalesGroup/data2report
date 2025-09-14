import logging
import os
from datetime import datetime
from pathlib import Path

_PROJECT_FOLDER = Path(os.path.dirname(os.path.abspath(__file__))).parent.absolute()


def get_project_folder() -> str:
    return str(_PROJECT_FOLDER)


def init_env_from_file():
    full_file_name = os.path.join(get_project_folder(), "config", "aws.env.list")
    if os.path.exists(full_file_name):
        logging.info(f"Going to set env variables from file: {full_file_name}")
        with open(full_file_name) as f:
            for line in f:
                key, value = line.strip().split("=")
                os.environ[key] = value


def get_reports_folder() -> str:
    return os.environ.get("REPORTS_FOLDER", "/data/data2report/")


def get_current_day() -> str:
    return str(datetime.today().date())
