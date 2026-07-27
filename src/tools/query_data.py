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

import gzip
import json
import logging
import sqlite3
from typing import Optional

_TABLE_NAME = "chunk"
_MAX_ROWS = 100
_QUERY_TIMEOUT_SECONDS = 3
_MAX_CELL_CHARS = 500


def load_chunk_into_sqlite(chunk_path: str) -> sqlite3.Connection:
    """Load a gzipped CSV or JSONL chunk file into an in-memory sqlite3 connection."""
    with gzip.open(chunk_path, "rt") as f:
        first_line = f.readline().rstrip("\n")

    if _looks_like_json(first_line):
        return _load_jsonl(chunk_path)
    else:
        return _load_csv(chunk_path, first_line)


def _looks_like_json(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("{") or stripped.startswith("[")


def _load_csv(chunk_path: str, header_line: str) -> sqlite3.Connection:
    columns = [c.strip().strip('"') for c in header_line.split(",")]
    conn = sqlite3.connect(":memory:")
    col_defs = ", ".join(f'"{c}" TEXT' for c in columns)
    conn.execute(f'CREATE TABLE "{_TABLE_NAME}" ({col_defs})')
    placeholders = ", ".join("?" for _ in columns)
    with gzip.open(chunk_path, "rt") as f:
        f.readline()  # skip header
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            row = _parse_csv_row(line, len(columns))
            if row:
                conn.execute(
                    f'INSERT INTO "{_TABLE_NAME}" VALUES ({placeholders})', row
                )
    conn.commit()
    logging.debug(f"Loaded CSV chunk into sqlite: {chunk_path}")
    return conn


def _parse_csv_row(line: str, expected_cols: int) -> Optional[list]:
    import csv
    import io
    try:
        reader = csv.reader(io.StringIO(line))
        row = next(reader)
        if len(row) != expected_cols:
            return None
        return row
    except Exception:
        return None


def _load_jsonl(chunk_path: str) -> sqlite3.Connection:
    columns: Optional[list] = None
    rows = []
    with gzip.open(chunk_path, "rt") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    continue
                if columns is None:
                    columns = list(obj.keys())
                rows.append([str(obj.get(c, "")) for c in columns])
            except json.JSONDecodeError:
                continue

    if not columns:
        columns = ["line"]
        rows = []

    conn = sqlite3.connect(":memory:")
    col_defs = ", ".join(f'"{c}" TEXT' for c in columns)
    conn.execute(f'CREATE TABLE "{_TABLE_NAME}" ({col_defs})')
    placeholders = ", ".join("?" for _ in columns)
    for row in rows:
        conn.execute(f'INSERT INTO "{_TABLE_NAME}" VALUES ({placeholders})', row)
    conn.commit()
    logging.debug(f"Loaded JSONL chunk into sqlite: {chunk_path}")
    return conn


class QueryDataTool:
    name = "query_data"
    description = (
        "Run a read-only SQL SELECT query against the current data chunk. "
        "The table is named 'chunk'. All columns are TEXT — use CAST when needed. "
        "Use this to get exact counts, top-N rankings, or filtered rows."
    )

    def __init__(self):
        self._conn: Optional[sqlite3.Connection] = None

    def setup(self, chunk_path: str) -> None:
        self._conn = load_chunk_into_sqlite(chunk_path)

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": (
                            "A SQL SELECT statement to run against the 'chunk' table. "
                            "Must be a SELECT — other statements are rejected."
                        ),
                    }
                },
                "required": ["sql"],
            },
        }

    def run(self, args: dict) -> dict:
        sql = args.get("sql", "").strip()
        if not sql.upper().startswith("SELECT"):
            return {"error": "Only SELECT statements are allowed."}
        if self._conn is None:
            return {"error": "query_data is not initialized for this chunk."}
        try:
            self._conn.execute(f"PRAGMA busy_timeout = {_QUERY_TIMEOUT_SECONDS * 1000}")
            cursor = self._conn.execute(sql)
            columns = [d[0] for d in cursor.description]
            rows = []
            truncated = False
            for i, row in enumerate(cursor):
                if i >= _MAX_ROWS:
                    truncated = True
                    break
                rows.append([_truncate_cell(v) for v in row])
            return {"columns": columns, "rows": rows, "truncated": truncated}
        except sqlite3.Error as e:
            return {"error": str(e)}


def _truncate_cell(value) -> str:
    s = str(value) if value is not None else ""
    if len(s) > _MAX_CELL_CHARS:
        return s[:_MAX_CELL_CHARS] + "…"
    return s
