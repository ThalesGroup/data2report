import json
import logging
import os
import shutil
import threading
from tempfile import NamedTemporaryFile
from typing import Callable, Optional, Dict, Any

from chunks_utils import split_input_file
from conf_utils import validate_configuration, get_report_config
from report_processing import (
    process_chunks_folder,
    process_final_report,
)
from s3_utils import (
    is_s3_uri,
    download_s3_uri,
    upload_file,
    get_reports_bucket,
    get_data2report_prefix,
)
from boto3.session import Session
from utils import (
    is_s3_configured,
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
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    stop_event: Optional[threading.Event] = None,
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
        progress_cb (Callable[[Dict[str, Any]], None], optional): Optional callback function to report progress. The function should accept a dictionary with progress information.
        stop_event (threading.Event, optional): Optional threading event to signal stopping the process. If provided, the process should periodically check this event and stop if it is set.

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
    if is_s3_uri(input_file):
        with NamedTemporaryFile(delete=False) as tmp:
            download_s3_uri(input_file, tmp.name, session=Session())
            input_file = tmp.name
    if not os.path.exists(input_file) or not os.path.isfile(input_file):
        raise FileNotFoundError(f"Input file '{input_file}' not found")
    session = Session()
    reports_folder = get_reports_folder()
    if report_id:
        configuration = get_report_config(
            report_id, session=session if is_s3_configured() else None
        )
    else:
        report_id = configuration.get("id")
    conf_errors = validate_configuration(configuration, report_id)
    if len(conf_errors) > 0:
        raise ValueError(f"Invalid report configuration: {conf_errors}")
    if not os.path.exists(reports_folder) or not os.path.isdir(reports_folder):
        raise FileNotFoundError(f"Report folder '{reports_folder}' does not exist")
    if not run_id:
        run_id = get_current_day()
    if not work_folder:
        work_folder = os.path.join(
            reports_folder, "work", f"report={report_id}", f"run={run_id}"
        )
        input_details_file = os.path.join(work_folder, "input_details.json")
        input_details = _get_input_details(input_details_file)
        input_details_match = False
        if not force and input_details:
            if (
                input_details["input_size_bytes"] == os.path.getsize(input_file)
                and input_details["chunk_size"] == configuration["report"]["chunk_size"]
            ):
                input_details_match = True
            else:
                logging.info(
                    "Input file size or chunk size changed, forcing reprocessing"
                )
        if force or not input_details_match:
            shutil.rmtree(work_folder, ignore_errors=True)
            logging.info(f"Work folder '{work_folder}' cleared")
        if not os.path.exists(work_folder):
            os.makedirs(work_folder)
        if not input_details_match:
            _write_input_details(
                input_details_file, input_file, configuration["report"]["chunk_size"]
            )
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
        f"Report '{report_id}' run '{run_id}' prepared: {chunks} chunks, {records} records"
    )
    report_chunks_folder = os.path.join(work_folder, "chunk_reports")
    process_result = process_chunks_folder(
        chunks_folder,
        configuration["llm"],
        configuration["report"],
        report_chunks_folder,
        progress_cb=progress_cb,
        report_id=report_id,
        run_id=run_id,
        stop_event=stop_event,
    )
    llm_usage = process_result["llm_usage"]
    if not output_folder:
        output_folder = get_report_folder(report_id, run_id)
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)
    final_report_file = os.path.join(output_folder, get_final_report_name())
    final_result = process_final_report(
        report_chunks_folder,
        final_report_file,
        configuration["llm"],
        configuration["report"],
    )
    if is_s3_configured():
        output_key = final_report_file[len(get_reports_folder()) + 1 :]
        if get_data2report_prefix():
            if get_data2report_prefix().endswith("/"):
                output_key = get_data2report_prefix() + output_key
            else:
                output_key = get_data2report_prefix() + "/" + output_key
        upload_file(
            get_reports_bucket(), final_report_file, output_key, session=session
        )
        s3_uri = f"s3://{get_reports_bucket()}/{output_key}"
    else:
        s3_uri = None
    if "llm_usage" in final_result:
        llm_usage["input_tokens"] += final_result["llm_usage"].get("input_tokens", 0)
        llm_usage["output_tokens"] += final_result["llm_usage"].get("output_tokens", 0)
    result = {
        "report_id": report_id,
        "run_id": run_id,
        "output_folder": output_folder,
        "work_folder": work_folder,
        "chunks": chunks,
        "records": records,
        "records_limit_reached": max_records is not None,
        "stopped": (
            bool(stop_event.is_set())
            if stop_event
            else False and records is not None and records >= max_records
        ),
        "llm_usage": process_result["llm_usage"],
        "chunks_skipped": process_result["chunks_skipped"],
        "duration_seconds": process_result["duration_seconds"],
        "longest_chunk_duration_seconds": process_result["longest_duration_seconds"],
        "s3_uri": s3_uri,
    }
    with open(os.path.join(output_folder, "result.json"), "w") as f:
        json.dump(result, f, indent=2)
    logging.info("Report processing completed. Result: " + str(result))
    return result


def _get_input_details(input_details_file: str) -> Optional[dict[str, Any]]:
    if os.path.exists(input_details_file) and os.path.isfile(input_details_file):
        with open(input_details_file, "r") as f:
            return json.load(f)
    return None


def _write_input_details(input_details_file: str, input_file: str, chunk_size: int):
    with open(input_details_file, "w") as f:
        json.dump(
            {
                "input_size_bytes": os.path.getsize(input_file),
                "chunk_size": chunk_size,
            },
            f,
            indent=2,
        )
