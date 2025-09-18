import gzip
import json
import logging
import os
from typing import TextIO


def _smart_open(path: str, mode: str = "rt") -> TextIO:
    """Open plain text and *.gz* files transparently in *text* mode."""
    return (
        gzip.open(path, mode, encoding="utf-8")
        if path.endswith(".gz")
        else open(path, mode, encoding="utf-8")
    )


def split_input_file(
    chunk_folder: str,
    input_file: str,
    chunk_size: int,
    max_records: int = None,
    header: bool = False,
) -> (int, int):
    """
        Splits the input file into chunks and stores them in the specified chunk folder.
    ´
        Args:
            chunk_folder (str): Path to the folder where chunks will be stored.
            input_file (str): Path to the input file to split. Can be a text file or a gzipped (.gz) file.
            chunk_size (int): Number of records per chunk.
            max_records (int): if the limit is defined and reached, stop processing records
            header (bool): if True, the first line is treated as a CSV header and written at the top of every chunk.

        Returns:
            tuple: (chunks, records)
                - chunks (int): Number of chunks created or found.
                - records (int): Number of records processed, or None if chunks already exist.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer")

    if os.path.isdir(chunk_folder):
        existing = [
            f
            for f in os.listdir(chunk_folder)
            if f.startswith("chunk_") and f.endswith(".gz")
        ]
        if existing:
            return len(existing), None
    else:
        os.makedirs(chunk_folder, exist_ok=True)

    is_jsonl = input_file.endswith(".jsonl") or input_file.endswith(".jsonl.gz")
    chunks = records = bad_lines = 0
    out_f: TextIO | None = None
    header_line: str | None = None
    if chunks > 0:
        return chunks, None

    try:
        with _smart_open(input_file) as in_f:
            if header:
                try:
                    header_line = next(in_f)
                except StopIteration:
                    return 0, 0
            for line in in_f:
                if max_records is not None and records >= max_records:
                    break

                if records % chunk_size == 0:
                    if out_f:
                        out_f.close()
                    chunks += 1
                    out_name = (
                        f"chunk_{chunks:04d}.jsonl.gz"
                        if is_jsonl
                        else f"chunk_{chunks:04d}.csv.gz"
                    )
                    out_f = gzip.open(
                        os.path.join(chunk_folder, out_name), "wt", encoding="utf-8"
                    )
                    if header_line is not None:
                        out_f.write(header_line)

                if not line.strip():  # skip empty lines
                    continue

                if is_jsonl:
                    try:
                        json.loads(line)  # validate JSON
                    except json.JSONDecodeError:
                        bad_lines += 1
                        continue
                else:
                    if line.count(",") < 1:  # CSV validation
                        bad_lines += 1
                        continue

                out_f.write(line)
                records += 1

    finally:
        if out_f:
            out_f.close()
    if bad_lines:
        logging.warning(f"Skipped {bad_lines} bad lines in {input_file}")
        # TODO write chunk (gz file). If s3 path, upload to s3
        # TODO used the csv_file_with_1k_lines fixture for testing
    return chunks, records
