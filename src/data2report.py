import json
import logging
import os
import shutil
from typing import List, Optional

from utils import get_reports_folder, get_current_day


def run_report(
    input_file: str,
    report_id: str = None,
    configuration: dict = None,
    run_id: str = None,
    output_folder: str = None,
    work_folder: str = None,
    force: bool = False,
) -> dict:
    if (not report_id and not configuration) or (report_id and configuration):
        raise ValueError("Either report_name or configuration must be provided")
    if not input_file:
        raise ValueError("input_file is required.")
    # TODO if s3 path, check s3
    if not os.path.exists(input_file) or not os.path.isfile(input_file):
        raise FileNotFoundError(f"Input file '{input_file}' not found")
    reports_folder = get_reports_folder()
    if report_id:
        configuration_file = os.path.join(
            reports_folder, "configuration", f"{report_id}.json"
        )
        # TODO if s3 path, check and download from s3
        if not os.path.exists(configuration_file) or not os.path.isfile(
            configuration_file
        ):
            raise FileNotFoundError(
                f"Report configuration file '{configuration_file}' not found"
            )
        with open(configuration_file, "r") as f:
            configuration = json.load(f)
    conf_errors = _validate_configuration(configuration, report_id)
    if len(conf_errors) > 0:
        raise ValueError(f"Invalid report configuration: {conf_errors}")
    if not os.path.exists(reports_folder) or not os.path.isdir(reports_folder):
        raise FileNotFoundError(f"Report folder '{reports_folder}' does not exist")
    if not run_id:
        run_id = get_current_day()
    if not output_folder:
        output_folder = os.path.join(
            reports_folder, "reports", "report=", configuration["id"], f"run={run_id}"
        )
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)
    if not work_folder:
        work_folder = os.path.join(
            reports_folder, "work", "report=", configuration["id"], f"run={run_id}"
        )
        if force:
            # TODO if s3 path, clear s3 folder
            shutil.rmtree(work_folder)
            logging.info(f"Work folder '{work_folder}' cleared")
        if not os.path.exists(work_folder):
            os.makedirs(work_folder)
    chunk_folder = os.path.join(work_folder, "chunks")
    chunks, records = _split_input_file(chunk_folder, input_file, configuration)
    logging.info(
        f"Report '{configuration['id']}' run '{run_id}' prepared: {chunks} chunks, {records} records"
    )
    return {
        "output_folder": output_folder,
        "work_folder": work_folder,
        "chunks": chunks,
        "records": records,
    }


def _validate_configuration(configuration: dict, report_id: Optional[str]) -> List[str]:
    errors = []
    if "id" not in configuration or not configuration["id"]:
        errors.append("Missing report id")
    elif report_id and configuration["id"] != report_id:
        errors.append(
            "Report id in configuration does not match the provided report_id"
        )
    # TODO: add more validations
    return errors


def _split_input_file(
    chunk_folder: str, input_file: str, configuration: dict
) -> (int, int):
    if not os.path.exists(chunk_folder):
        os.makedirs(chunk_folder)
        chunks = 0
    else:
        chunks = len(os.listdir(chunk_folder))
    if chunks > 0:
        return chunks, None
    chunk_size = configuration["report"]["chunk_size"]
    records = 0
    with open(input_file, "r") as f:
        for _ in f:
            if records % chunk_size == 0:
                chunks += 1
                # TODO write chunk (gz file). If s3 path, upload to s3
            records += 1
    return chunks, records
