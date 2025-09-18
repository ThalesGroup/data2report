import gzip
import logging
import os
import shutil

from llm_utils import invoke_llm


def process_chunks_folder(
    chunks_folder: str,
    llm_config: dict,
    chunked_reports_folder: str,
    max_workers: int = 1,
) -> dict:
    if not os.path.exists(chunked_reports_folder):
        os.makedirs(chunked_reports_folder)
    llm_usage = {
        "input_tokens": 0,
        "output_tokens": 0,
    }
    exists = 0
    chunk_files = os.listdir(chunks_folder)
    logging.info(
        f"Going to process {len(chunk_files)} chunks. Max workers: {max_workers}"
    )
    for chunk_idx, chunk_file in enumerate(chunk_files):
        report_file = os.path.join(
            chunked_reports_folder, f"chunk_{chunk_idx + 1}_report.gz"
        )
        logging.info(
            f"Processing chunk {chunk_idx + 1}/{len(chunk_files)}: {chunk_file}"
        )
        process_result = _process_report(
            os.path.join(chunks_folder, chunk_file), llm_config, report_file
        )
        llm_usage["input_tokens"] += process_result["usage"].get("input_tokens", 0)
        llm_usage["output_tokens"] += process_result["usage"].get("output_tokens", 0)
        if process_result["exists"]:
            exists += 1
    return {
        "llm_usage": llm_usage,
        "chunks": len(chunk_files),
        "chunks_skipped": exists,
        "final_report": chunked_reports_folder,
    }


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
        raise NotImplementedError(
            "Non-incremental final report generation is not implemented"
        )
    return result


def _process_report(input_file: str, llm_config: dict, output_file: str) -> dict:
    exists = os.path.exists(output_file)
    if exists:
        logging.info(
            f"Skipping chunk processing, output file '{output_file}' already exists"
        )
        usage = {"input_tokens": 0, "output_tokens": 0}
    else:
        prompt_data = _file_to_prompt_data(input_file)
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
    return {"exists": exists, "usage": usage}


def _file_to_prompt_data(input_file: str) -> str:
    with gzip.open(input_file, "rt") as f:
        return f.read()
