import gzip
import logging
import os
import shutil
import threading
from datetime import datetime
from typing import Optional, Callable, Dict, Any

from llm_utils import invoke_llm
import concurrent.futures


def process_chunks_folder(
    chunks_folder: str,
    llm_config: dict,
    report_config: dict,
    chunked_reports_folder: str,
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    report_id: Optional[str] = None,
    run_id: Optional[str] = None,
    stop_event: Optional[threading.Event] = None,
) -> dict:
    if not os.path.exists(chunked_reports_folder):
        os.makedirs(chunked_reports_folder)
    llm_usage = {
        "input_tokens": 0,
        "output_tokens": 0,
    }
    exists = 0
    chunk_files = os.listdir(chunks_folder)
    max_workers = report_config.get("max_workers", 1)
    logging.info(
        f"Going to process {len(chunk_files)} chunks. Max workers: {max_workers}"
    )
    start_time = datetime.now()
    longest_duration = 0
    results = []
    shutdown_called = False
    total_chunks = len(chunk_files)
    completed = 0

    def _notify(result: dict, chunk_idx: int):
        nonlocal completed
        completed += 1
        if progress_cb:
            progress_cb(
                {
                    "event": "chunk_done",
                    "report_id": report_id,
                    "run_id": run_id,
                    "chunk_index": chunk_idx + 1,
                    "total_chunks": total_chunks,
                    "exists": result.get("exists", False),
                    "duration_seconds": result.get("duration-seconds", 0),
                    "usage": result.get(
                        "usage", {"input_tokens": 0, "output_tokens": 0}
                    ),
                    "completed_chunks": completed,
                }
            )

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max_workers, thread_name_prefix="data2report_"
    ) as thread_pool:
        futures = []
        prev_report_file = None
        for chunk_idx, chunk_file in enumerate(chunk_files):
            report_file = os.path.join(
                chunked_reports_folder, f"chunk_{chunk_idx + 1}_report.gz"
            )
            future = thread_pool.submit(
                _process_report,
                chunk_idx,
                os.path.join(chunks_folder, chunk_file),
                llm_config,
                report_file,
                prev_report_file,
                stop_event,
            )
            futures.append(future)
            if report_config["incremental"]:
                prev_report_file = report_file
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            longest_duration = max(longest_duration, result.get("duration-seconds", 0))
            _notify(result, result.get("_chunk_index", 0))
            if _should_stop(
                start_time, get_process_timeout_seconds(), longest_duration
            ):
                thread_pool.shutdown(wait=False, cancel_futures=True)
                shutdown_called = True
                break
    if shutdown_called:
        for f in concurrent.futures.as_completed(
            [f for f in futures if not f.cancelled()]
        ):
            results.append(f.result())
    for result in results:
        llm_usage["input_tokens"] += result["usage"].get("input_tokens", 0)
        llm_usage["output_tokens"] += result["usage"].get("output_tokens", 0)
        if result["exists"]:
            exists += 1

    return {
        "llm_usage": llm_usage,
        "chunks": len(chunk_files),
        "chunks_skipped": exists,
        "final_report": chunked_reports_folder,
        "duration_seconds": (datetime.now() - start_time).seconds,
        "longest_duration_seconds": longest_duration,
    }


def get_process_timeout_seconds() -> int:
    return os.environ.get("TIMEOUT", 800)


def _should_stop(
    start_time: datetime, timeout_seconds: int, longest_duration: int
) -> bool:
    elapsed_time = (datetime.now() - start_time).seconds
    if elapsed_time >= timeout_seconds:
        logging.info(
            f"Timeout of {timeout_seconds} seconds occurred. Elapsed time: {elapsed_time} seconds"
        )
        return True
    if longest_duration * 1.2 >= timeout_seconds - elapsed_time:
        logging.info(
            f"Canceling future tasks. Longest duration: {longest_duration} seconds. "
            f"Remaining time until timeout: {timeout_seconds - elapsed_time} seconds"
        )
        return True
    return False


def process_final_report(
    chunked_reports_folder: str, output_file: str, llm_config: dict, report_config: dict
) -> dict:
    result = {}
    if os.path.exists(output_file):
        logging.info(
            f"Skipping final report generation, output file '{output_file}' already exists"
        )
        result["exists"] = True
    else:
        result["exists"] = False
    if report_config["incremental"]:
        report_chunks = os.listdir(chunked_reports_folder)
        if len(report_chunks) > 0:
            last_report_name = sorted(report_chunks)[-1]
            last_report_file = os.path.join(chunked_reports_folder, last_report_name)
            logging.info(
                f"Generating final report from last chunk report: {last_report_name}"
            )
            shutil.copyfile(last_report_file, output_file)
    else:
        with gzip.open(output_file, "wt") as out_f:
            for f in os.listdir(chunked_reports_folder):
                chunk_file = os.path.join(chunked_reports_folder, f)
                with gzip.open(chunk_file, "rt") as in_f:
                    out_f.write(in_f.read())
                    out_f.write("\n\n")
    logging.info(f"Final report generated: {output_file}")
    return result


def _process_report(
    chunk_index: int,
    input_file: str,
    llm_config: dict,
    output_file: str,
    prev_report_file: str = None,
    stop_event: Optional[threading.Event] = None,
) -> dict:
    start_time = datetime.now()
    if stop_event and stop_event.is_set():
        return {
            "exists": False,
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "duration-seconds": 0,
            "_chunk_index": chunk_index,
        }
    exists = os.path.exists(output_file)
    if exists:
        logging.info(
            f"Skipping chunk {chunk_index} processing, output file '{output_file}' already exists"
        )
        usage = {"input_tokens": 0, "output_tokens": 0}
    else:
        logging.info(f"Processing chunk {chunk_index + 1}: {input_file}")
        if stop_event and stop_event.is_set():
            return {
                "exists": False,
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "duration-seconds": 0,
                "_chunk_index": chunk_index,
            }
        prompt_data = _file_to_prompt_data(input_file)
        if prev_report_file and os.path.exists(prev_report_file):
            prev_report_data = _file_to_prompt_data(prev_report_file)
            prompt_data = (
                f"\nPrevious findings:\n{prev_report_data}\n\nNew data:\n{prompt_data}"
            )
        llm_result = invoke_llm(
            llm_config["system_prompt"],
            prompt_data,
            llm_config["model_id"],
            llm_config.get("max_tokens"),
            llm_config.get("temperature"),
        )
        usage = llm_result["usage"]
        with gzip.open(output_file, "wt") as f:
            f.write(llm_result["content"])
    duration = (datetime.now() - start_time).seconds
    return {
        "exists": exists,
        "usage": usage,
        "duration-seconds": duration,
        "_chunk_index": chunk_index,
    }


def _file_to_prompt_data(input_file: str) -> str:
    with gzip.open(input_file, "rt") as f:
        return f.read()
