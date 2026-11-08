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
from collections import Counter
from typing import Optional

from tools.query_data import load_chunk_into_sqlite

_TABLE_NAME = "chunk"
_MAX_CELL_CHARS = 1000
_DEFAULT_TEMPLATES = 20
_MAX_TEMPLATES = 50
_MAX_TEXT_CHARS = 300
_SCAN_TIMEOUT_SECONDS = 3

# Applied in order: specific shapes first so the generic <NUM> rule runs last.
_MASKS = [
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<UUID>"),
    (re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"), "<EMAIL>"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?\b"), "<TS>"),
    (re.compile(r"\b\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?\b"), "<TIME>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "<IP>"),
    (re.compile(r"\b0x[0-9a-fA-F]+\b|\b[0-9a-fA-F]{32,}\b"), "<HEX>"),
    (re.compile(r"\b(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{12,}\b"), "<ID>"),
    (re.compile(r"\b\d+(?:\.\d+)?\b"), "<NUM>"),
]
_WHITESPACE = re.compile(r"\s+")


def to_template(text: str) -> str:
    """Replace variable parts (ids, numbers, timestamps, ...) with placeholders."""
    text = text[:_MAX_CELL_CHARS]
    for pattern, placeholder in _MASKS:
        text = pattern.sub(placeholder, text)
    return _WHITESPACE.sub(" ", text).strip()


def _clip(value: str) -> str:
    return value if len(value) <= _MAX_TEXT_CHARS else value[:_MAX_TEXT_CHARS] + "…"


class TemplateClusterTool:
    name = "template_cluster"
    description = (
        "Group the values of a column of the current data chunk (typically log lines or "
        "messages) into templates by replacing variable parts - numbers, IPs, UUIDs, "
        "timestamps, emails, hex strings and long ids - with placeholders such as <NUM> "
        "and <IP>. Returns the most frequent templates with their counts, percentages "
        "and one example row each. Use it to summarize repetitive logs and to spot rare "
        "message types without reading every row."
    )
    ui_description = (
        "Lets the LLM group repetitive log lines or messages into templates and count "
        "them, to summarize noisy data and spot rare events."
    )

    def __init__(self):
        self._chunk_path: Optional[str] = None
        self._conn = None

    def setup(self, chunk_path: str) -> None:
        self._chunk_path = chunk_path
        self._conn = None  # loaded lazily on first use

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "column": {
                        "type": "string",
                        "description": "Column of the 'chunk' table to cluster.",
                    },
                    "max_templates": {
                        "type": "integer",
                        "description": (
                            f"Number of templates to return, most frequent first "
                            f"(default {_DEFAULT_TEMPLATES}, cap {_MAX_TEMPLATES})."
                        ),
                    },
                    "ascending": {
                        "type": "boolean",
                        "description": "Return the rarest templates first instead. Default false.",
                    },
                },
                "required": ["column"],
            },
        }

    def run(self, args: dict) -> dict:
        column = args.get("column")
        if not isinstance(column, str) or not column:
            return {"error": "column is required"}
        try:
            limit = int(args.get("max_templates") or _DEFAULT_TEMPLATES)
        except (TypeError, ValueError):
            return {"error": "max_templates must be an integer"}
        limit = max(1, min(limit, _MAX_TEMPLATES))
        if not self._chunk_path:
            return {"error": "no data chunk available"}
        if self._conn is None:
            self._conn = load_chunk_into_sqlite(self._chunk_path)
        columns = [r[1] for r in self._conn.execute(f'PRAGMA table_info("{_TABLE_NAME}")')]
        if column not in columns:
            return {"error": f"unknown column '{column}'. Columns: {columns}"}

        deadline = time.monotonic() + _SCAN_TIMEOUT_SECONDS
        counts: Counter = Counter()
        examples: dict = {}
        rows_scanned = empty = 0
        timed_out = False
        for row_id, value in self._conn.execute(f'SELECT rowid, "{column}" FROM "{_TABLE_NAME}"'):
            if time.monotonic() > deadline:
                timed_out = True
                break
            rows_scanned += 1
            text = str(value or "").strip()
            if not text:
                empty += 1
                continue
            template = to_template(text)
            counts[template] += 1
            examples.setdefault(template, (row_id, text))

        clustered = rows_scanned - empty
        ordered = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]) if args.get("ascending") else (-kv[1], kv[0]))
        templates = [
            {
                "template": _clip(t),
                "count": n,
                "percent": round(100 * n / clustered, 1),
                "example": _clip(examples[t][1]),
                "example_row": examples[t][0],
            }
            for t, n in ordered[:limit]
        ]
        return {
            "templates": templates,
            "distinct_templates": len(counts),
            "rows_scanned": rows_scanned,
            "empty_rows": empty,
            "truncated": timed_out or len(counts) > limit,
        }
