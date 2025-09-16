import json
import logging
import os
import shutil

from chunks_utils import split_input_file
from conf_utils import validate_configuration
from utils import get_reports_folder, get_current_day


def run_report(
    input_file: str,
    report_id: str = None,
    configuration: dict = None,
    run_id: str = None,
    output_folder: str = None,
    work_folder: str = None,
    force: bool = False,
    max_records: int = None,
) -> dict:
    """
    Prepares and runs a report based on the provided input file and configuration.

    Args:
        input_file (str): Path to the input file to process. Can be S3 path or local path. If S3 path, the file will be downloaded to a local temporary folder.
        for example: s3://my-bucket/path/to/file.csv or /path/to/file.csv
        report_id (str, optional): Identifier for the report configuration. Either this or `configuration` must be provided.
        configuration (dict, optional): Report configuration dictionary. Either this or `report_id` must be provided.
        run_id (str, optional): Unique identifier for this run. If not provided, uses the current day.
        output_folder (str, optional): Path to the output folder. If not provided, a default path is used.
        work_folder (str, optional): Path to the working folder, which contains the intermediate data, like reports for chunks. If not provided, a default path is used.
        force (bool, optional): If True, clears the work folder before running.
        max_records (int, optional): Maximum number of records to process from the input file. If not provided, all records are processed.

    Returns:
        dict: Dictionary containing paths and statistics:
            - output_folder (str): Path to the output folder.
            - work_folder (str): Path to the work folder.
            - chunks (int): Number of chunks created.
            - records (int): Number of records processed.

    Raises:
        ValueError: If required arguments are missing or configuration is invalid.
        FileNotFoundError: If input or configuration files/folders are missing.
    """
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
    conf_errors = validate_configuration(configuration, report_id)
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
    # TODO send max records to split_input_file
    chunks, records = split_input_file(
        chunk_folder, input_file, configuration["report"]["chunk_size"]
    )
    logging.info(
        f"Report '{configuration['id']}' run '{run_id}' prepared: {chunks} chunks, {records} records"
    )
    return {
        "output_folder": output_folder,
        "work_folder": work_folder,
        "chunks": chunks,
        "records": records,
        "records_limit_reached": max_records is not None and records >= max_records,
    }
