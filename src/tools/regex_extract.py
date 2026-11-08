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

import re
import time
from typing import Optional

from tools.query_data import load_chunk_into_sqlite

_TABLE_NAME = "chunk"
_MAX_PATTERN_CHARS = 500
_MAX_CELL_CHARS = 2000      # longer cells are only scanned up to this length
_MAX_RETURNED = 100
_DEFAULT_RETURNED = 50
_MAX_VALUE_CHARS = 500
_SCAN_TIMEOUT_SECONDS = 3

# Nested quantifiers such as (a+)+ or (.*)* cause catastrophic backtracking, and
# Python's `re` cannot be interrupted, so such patterns are refused up front.
_NESTED_QUANTIFIER = re.compile(r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)[+*{]")


def _clip(value):
    if isinstance(value, str) and len(value) > _MAX_VALUE_CHARS:
        return value[:_MAX_VALUE_CHARS] + "…"
    return value


class RegexExtractTool:
    name = "regex_extract"
    description = (
        "Find regex matches (Python `re` syntax) in a column of the current data chunk, "
        "or in a single text string. Pass `pattern` plus either `column` (scans every "
        "row of the 'chunk' table) or `text`. Returns the matches with their capture "
        "groups, the row id they came from, the total match count and the number of rows "
        "with a match. Use it to extract IDs, IPs, emails, error codes, or other "
        "patterns, and to count how often a pattern occurs."
    )
    ui_description = (
        "Lets the LLM pull values out of a column or text with a regular expression "
        "and count how often they occur."
    )

    def __init__(self):
        self._chunk_path: Optional[str] = None
        self._conn = None

    def setup(self, chunk_path: str) -> None:
        self._chunk_path = chunk_path
        self._conn = None  # loaded lazily, only if a column scan is requested

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regular expression (Python syntax).",
                    },
                    "column": {
                        "type": "string",
                        "description": "Column of the 'chunk' table to scan. Use this or `text`.",
                    },
                    "text": {
                        "type": "string",
                        "description": "A single string to scan. Use this or `column`.",
                    },
                    "ignore_case": {
                        "type": "boolean",
                        "description": "Case-insensitive matching. Default false.",
                    },
                    "max_matches": {
                        "type": "integer",
                        "description": (
                            f"Max matches to return (default {_DEFAULT_RETURNED}, "
                            f"cap {_MAX_RETURNED}). Counts still cover all rows."
                        ),
                    },
                },
                "required": ["pattern"],
            },
        }

    def run(self, args: dict) -> dict:
        pattern = args.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            return {"error": "pattern is required"}
        if len(pattern) > _MAX_PATTERN_CHARS:
            return {"error": f"pattern longer than {_MAX_PATTERN_CHARS} characters"}
        if _NESTED_QUANTIFIER.search(pattern):
            return {"error": "pattern rejected: nested quantifiers can hang the matcher"}
        column, text = args.get("column"), args.get("text")
        if (column is None) == (text is None):
            return {"error": "provide exactly one of `column` or `text`"}
        try:
            regex = re.compile(pattern, re.IGNORECASE if args.get("ignore_case") else 0)
        except re.error as e:
            return {"error": f"invalid regex: {e}"}
        try:
            limit = int(args.get("max_matches") or _DEFAULT_RETURNED)
        except (TypeError, ValueError):
            return {"error": "max_matches must be an integer"}
        limit = max(1, min(limit, _MAX_RETURNED))

        if text is not None:
            return self._scan(regex, [(None, str(text))], limit)
        return self._scan_column(regex, str(column), limit)

    def _scan_column(self, regex, column: str, limit: int) -> dict:
        if not self._chunk_path:
            return {"error": "no data chunk available; pass `text` instead"}
        if self._conn is None:
            self._conn = load_chunk_into_sqlite(self._chunk_path)
        columns = [r[1] for r in self._conn.execute(f'PRAGMA table_info("{_TABLE_NAME}")')]
        if column not in columns:
            return {"error": f"unknown column '{column}'. Columns: {columns}"}
        cursor = self._conn.execute(f'SELECT rowid, "{column}" FROM "{_TABLE_NAME}"')
        return self._scan(regex, cursor, limit)

    @staticmethod
    def _scan(regex, rows, limit: int) -> dict:
        deadline = time.monotonic() + _SCAN_TIMEOUT_SECONDS
        matches, total, rows_scanned, rows_with_match = [], 0, 0, 0
        timed_out = False
        for row_id, value in rows:
            if time.monotonic() > deadline:
                timed_out = True
                break
            rows_scanned += 1
            found = False
            for m in regex.finditer(str(value or "")[:_MAX_CELL_CHARS]):
                found = True
                total += 1
                if len(matches) < limit:
                    entry = {"row": row_id, "match": _clip(m.group(0))}
                    if m.re.groups:
                        entry["groups"] = [_clip(g) for g in m.groups()]
                    if m.re.groupindex:
                        entry["named"] = {k: _clip(v) for k, v in m.groupdict().items()}
                    matches.append(entry)
            rows_with_match += found
        return {
            "matches": matches,
            "match_count": total,
            "rows_with_match": rows_with_match,
            "rows_scanned": rows_scanned,
            "truncated": timed_out or total > len(matches),
        }
