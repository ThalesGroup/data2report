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

import csv
import gzip
import json
import logging
import os
import shutil
import threading
from datetime import datetime
from typing import Optional, Callable, Dict, Any

from llm_utils import invoke_llm
import concurrent.futures

from utils import get_json_lines


def _is_claude_model(model_id: str) -> bool:
    return isinstance(model_id, str) and "claude" in model_id.lower()


def _build_schema_description(schema: list) -> str:
    def _col_label(c):
        parts = [c["type"]]
        if c.get("primary_key"):
            parts.append("primary key")
        if c.get("description"):
            parts.append(c["description"])
        return f'{c["name"]} ({", ".join(parts)})'
    return ", ".join(_col_label(c) for c in schema)


def _build_schema_user_prefix(schema: list) -> str:
    return f"Emit one JSON object per line matching this schema:\n  {_build_schema_description(schema)}\n"


def _build_system_prompt_suffix(schema: list, use_tool: bool) -> str:
    col_desc = _build_schema_description(schema)
    if use_tool:
        return (
            f"\n\nOutput schema: {col_desc}. "
            "Use the memory tool to write one row per finding. Return no narrative text."
        )
    else:
        return (
            f"\n\nOutput each finding as a single JSON object on its own line "
            f"matching this schema: {col_desc}. Return no narrative text."
        )


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
    tool_calls = {}  # { tool_name: total_count }
    exists = 0
    chunks_with_unexpected_text = 0
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

    # Set up MemoryTool for Claude models when report.output is configured
    output_config = report_config.get("output")
    memory_tool = None
    if output_config and _is_claude_model(llm_config.get("model_id", "")):
        from tools.memory import MemoryTool, DEFAULT_SCHEMA
        schema = output_config.get("schema", DEFAULT_SCHEMA)
        mode = "incremental" if report_config.get("incremental") else "parallel"
        memory_tool = MemoryTool(schema, mode)
        memory_tool.initialize()
        logging.info(f"MemoryTool initialized with schema: {schema}, mode: {mode}")

    schema_prompt = None
    system_prompt = llm_config["system_prompt"]
    if output_config:
        from tools.memory import DEFAULT_SCHEMA
        schema = output_config.get("schema", DEFAULT_SCHEMA)
        system_prompt = system_prompt + _build_system_prompt_suffix(schema, use_tool=memory_tool is not None)
        if not memory_tool:
            # Non-Claude: also inject schema into user prompt so it's per-chunk visible
            schema_prompt = _build_schema_user_prefix(schema)

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
                report_config.get("output_format"),
                prev_report_file if not memory_tool else None,
                stop_event,
                memory_tool,
                schema_prompt,
                system_prompt,
                progress_cb,
                report_id,
                run_id,
                total_chunks,
            )
            futures.append(future)
            if report_config["incremental"] and not memory_tool:
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
        for name, count in result.get("tool_calls", {}).items():
            tool_calls[name] = tool_calls.get(name, 0) + count
        if result["exists"]:
            exists += 1
        chunks_with_unexpected_text += result.get("unexpected_text", 0)

    return {
        "llm_usage": llm_usage,
        "tool_calls": tool_calls,
        "chunks": len(chunk_files),
        "chunks_skipped": exists,
        "chunks_with_unexpected_text": chunks_with_unexpected_text,
        "final_report": chunked_reports_folder,
        "duration_seconds": (datetime.now() - start_time).seconds,
        "longest_duration_seconds": longest_duration,
        "_memory_tool": memory_tool,
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
    chunked_reports_folder: str,
    output_file: str,
    llm_config: dict,
    report_config: dict,
    memory_tool=None,
) -> dict:
    result = {}
    if os.path.exists(output_file):
        logging.info(
            f"Skipping final report generation, output file '{output_file}' already exists"
        )
        result["exists"] = True
        return result
    result["exists"] = False

    # Claude path with memory: dump the accumulated table
    if memory_tool is not None:
        output_config = report_config.get("output", {})
        fmt = output_config.get("format", "jsonl")
        rows = memory_tool.dump()
        logging.info(f"Dumping memory table: {len(rows)} rows, format={fmt}")
        with gzip.open(output_file, "wt") as f:
            if fmt == "csv" and rows:
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            else:
                for row in rows:
                    f.write(json.dumps(row) + "\n")
        logging.info(f"Final report generated from memory: {output_file}")
        return result

    # Default path (incremental file copy or parallel concat)
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
    output_format: Optional[str] = None,
    prev_report_file: str = None,
    stop_event: Optional[threading.Event] = None,
    memory_tool=None,
    schema_prompt: Optional[str] = None,
    system_prompt: Optional[str] = None,
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    report_id: Optional[str] = None,
    run_id: Optional[str] = None,
    total_chunks: int = 0,
) -> dict:
    start_time = datetime.now()
    empty_result = {
        "exists": False,
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "tool_calls": {},
        "unexpected_text": 0,
        "duration-seconds": 0,
        "_chunk_index": chunk_index,
    }
    if stop_event and stop_event.is_set():
        return empty_result
    exists = os.path.exists(output_file)
    chunk_tool_calls = {}
    unexpected_text = 0
    if exists:
        logging.info(
            f"Skipping chunk {chunk_index} processing, output file '{output_file}' already exists"
        )
        usage = {"input_tokens": 0, "output_tokens": 0}
    else:
        logging.info(f"Processing chunk {chunk_index + 1}: {input_file}")
        if progress_cb:
            progress_cb({
                "event": "chunk_started",
                "report_id": report_id,
                "run_id": run_id,
                "chunk_index": chunk_index + 1,
                "total_chunks": total_chunks,
            })
        if stop_event and stop_event.is_set():
            return empty_result
        prompt_data = _file_to_prompt_data(input_file)

        if memory_tool:
            dump = memory_tool.dump()
            dump_json = json.dumps(dump)
            logging.info(
                f"Chunk {chunk_index + 1}: injecting memory dump "
                f"({len(dump)} rows, {len(dump_json.encode('utf-8'))} bytes)"
            )
            prompt_data = f"Current memory state:\n{dump_json}\n\nNew data:\n" + prompt_data
        elif schema_prompt:
            prompt_data = schema_prompt + "\n" + prompt_data
        elif prev_report_file and os.path.exists(prev_report_file):
            # Default incremental handoff
            prev_report_data = _file_to_prompt_data(prev_report_file)
            prompt_data = (
                f"\nPrevious findings:\n{prev_report_data}\n\nNew data:\n{prompt_data}"
            )

        shared = [memory_tool] if memory_tool else None
        llm_result = invoke_llm(
            system_prompt or llm_config["system_prompt"],
            prompt_data,
            llm_config["model_id"],
            llm_config.get("max_tokens"),
            llm_config.get("temperature"),
            tools=llm_config.get("tools"),
            chunk_path=input_file,
            shared_tools=shared,
        )
        usage = llm_result["usage"]
        chunk_tool_calls = llm_result.get("tool_calls", {})
        content = llm_result["content"]

        if memory_tool:
            # Claude memory path: skip writing chunk file; log unexpected text
            if content.strip():
                logging.info(
                    f"Chunk {chunk_index + 1}: unexpected text output "
                    f"({len(content)} chars): {content[:200]!r}"
                )
                unexpected_text = 1
        else:
            _write_output_file(output_file, content, output_format)
    duration = (datetime.now() - start_time).seconds
    return {
        "exists": exists,
        "usage": usage,
        "tool_calls": chunk_tool_calls,
        "unexpected_text": unexpected_text,
        "duration-seconds": duration,
        "_chunk_index": chunk_index,
    }


def _write_output_file(output_file: str, content: str, output_format: Optional[str]):
    if output_format is None:
        with gzip.open(output_file, "wt") as f:
            f.write(content)
    elif output_format == "jsonl":
        logging.info(f"Writing {output_file} as JSONL")
        with gzip.open(output_file, "wt") as f:
            for line in get_json_lines(content):
                if line:
                    f.write(line)
                    f.write("\n")
    else:
        raise ValueError(f"Unsupported output format: {output_format}")


def _file_to_prompt_data(input_file: str) -> str:
    with gzip.open(input_file, "rt") as f:
        return f.read()
