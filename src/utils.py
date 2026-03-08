# Copyright 2026 Thales
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Generator

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


def is_s3_configured() -> bool:
    return "REPORTS_BUCKET" in os.environ and len(os.environ["REPORTS_BUCKET"]) > 0


def get_reports_folder() -> str:
    return os.environ.get(
        "REPORTS_FOLDER", "/tmp/reports" if is_s3_configured() else "/data/data2report/"
    )


def get_current_day() -> str:
    return str(datetime.today().date())


def get_report_run_partition_name() -> str:
    return os.environ.get("RUN_PARTITION", "run")


def get_report_folder(report_id: str, run_id: str) -> str:
    reports_folder = get_reports_folder()
    return os.path.join(
        reports_folder,
        "reports",
        f"report={report_id}",
        f"{get_report_run_partition_name()}={run_id}",
    )


def get_final_report_name() -> str:
    return "final_report.gz"


def get_json_lines(text: str) -> Generator[str, None, None]:
    """
    split text into json lines, per line remove leading and trailing info before and after the json
    :param text: input text
    :return: generator lines with JSON data
    """
    if len(text) == 0:
        return
    current = 0
    warnings = 0
    while True:
        newline = text.find("\n", current)
        start_json = (
            text.find("{", current, newline)
            if newline != -1
            else text.find("{", current)
        )
        if start_json == -1:
            if logging.getLogger().isEnabledFor(logging.DEBUG):
                logging.warning(
                    f"Could not find start of json in text: {text[current:] if newline == -1 else text[current:newline]}"
                )
            warnings += 1
        else:
            end_json = (
                text.rfind("}", start_json)
                if newline == -1
                else text.rfind("}", start_json, newline)
            )
            if end_json == -1:
                if logging.getLogger().isEnabledFor(logging.DEBUG):
                    logging.warning(
                        f"Could not find end of json in text: {text[start_json: newline] if newline != -1 else text[start_json:]}"
                    )
                warnings += 1
            if end_json != -1:
                yield text[start_json : end_json + 1]
        if newline == -1:
            break
        current = newline + 1
        if current == len(text):
            break
    if warnings > 0:
        logging.warning(f"Total warnings while parsing json lines: {warnings}")
    return
