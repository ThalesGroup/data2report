import json
import logging
import os
import shutil

from chunks_utils import split_input_file
from conf_utils import validate_configuration, get_report_config
from report_processing import (
    process_chunks_folder,
    process_final_report,
)
from utils import (
    get_reports_folder,
    get_current_day,
    get_report_folder,
    get_final_report_name,
)


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
        configuration = get_report_config(report_id)
    conf_errors = validate_configuration(configuration, report_id)
    if len(conf_errors) > 0:
        raise ValueError(f"Invalid report configuration: {conf_errors}")
    if not os.path.exists(reports_folder) or not os.path.isdir(reports_folder):
        raise FileNotFoundError(f"Report folder '{reports_folder}' does not exist")
    if not run_id:
        run_id = get_current_day()
    if not output_folder:
        output_folder = get_report_folder(configuration["id"], run_id)
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)
    if not work_folder:
        work_folder = os.path.join(
            reports_folder, "work", f"report={configuration['id']}", f"run={run_id}"
        )
        if force:
            # TODO if s3 path, clear s3 folder
            shutil.rmtree(work_folder)
            logging.info(f"Work folder '{work_folder}' cleared")
        if not os.path.exists(work_folder):
            os.makedirs(work_folder)
    chunks_folder = os.path.join(work_folder, "chunks")
    if not max_records:
        max_records = configuration["report"].get("max_records")
    chunks, records = split_input_file(
        chunks_folder,
        input_file,
        configuration["report"]["chunk_size"],
        max_records,
        input_format=configuration["report"].get("input", {}).get("format"),
        header=configuration.get("header", False),
    )
    logging.info(
        f"Report '{configuration['id']}' run '{run_id}' prepared: {chunks} chunks, {records} records"
    )
    report_chunks_folder = os.path.join(work_folder, "chunk_reports")
    process_result = process_chunks_folder(
        chunks_folder,
        configuration["llm"],
        configuration["report"],
        report_chunks_folder,
    )
    llm_usage = process_result["llm_usage"]
    final_report_file = os.path.join(output_folder, get_final_report_name())
    final_result = process_final_report(
        report_chunks_folder,
        final_report_file,
        configuration["llm"],
        configuration["report"],
    )
    if "llm_usage" in final_result:
        llm_usage["input_tokens"] += final_result["llm_usage"].get("input_tokens", 0)
        llm_usage["output_tokens"] += final_result["llm_usage"].get("output_tokens", 0)
    result = {
        "report_id": configuration["id"],
        "run_id": run_id,
        "output_folder": output_folder,
        "work_folder": work_folder,
        "chunks": chunks,
        "records": records,
        "records_limit_reached": max_records is not None and records >= max_records,
        "llm_usage": process_result["llm_usage"],
        "chunks_skipped": process_result["chunks_skipped"],
        "duration_seconds": process_result["duration_seconds"],
        "longest_chunk_duration_seconds": process_result["longest_duration_seconds"],
    }
    with open(os.path.join(output_folder, "result.json"), "w") as f:
        json.dump(result, f, indent=2)
    logging.info("Report processing completed. Result: " + str(result))
    return result
