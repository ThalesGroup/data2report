import logging
import os
import re
from datetime import datetime
from pathlib import Path

_PROJECT_FOLDER = Path(os.path.dirname(os.path.abspath(__file__))).parent.absolute()


def get_project_folder() -> str:
    return str(_PROJECT_FOLDER)


def init_env_from_file():
    creds_str = os.environ.get("CREDS")
    if creds_str is not None:
        logging.info("Going to set env variables from CREDS environment variable")
        creds_str = creds_str.replace('"', "")
        m = re.search("accessKey: ([^,]+),", creds_str, flags=re.MULTILINE)
        if m:
            os.environ["AWS_ACCESS_KEY_ID"] = m.groups()[0]
        m = re.search("secretKey: ([^,]+),", creds_str, flags=re.MULTILINE)
        if m:
            os.environ["AWS_SECRET_ACCESS_KEY"] = m.groups()[0]
        m = re.search("securityToken: ([^,]+),", creds_str, flags=re.MULTILINE)
        if m:
            os.environ["AWS_SECURITY_TOKEN"] = m.groups()[0]
    else:
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


def get_report_folder(report_id: str, run_id: str) -> str:
    reports_folder = get_reports_folder()
    return os.path.join(
        reports_folder, "reports", f"report={report_id}", f"run={run_id}"
    )


def get_final_report_name() -> str:
    return "final_report.gz"
