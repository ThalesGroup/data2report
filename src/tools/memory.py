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

import logging
import sqlite3
from typing import Optional


_VALID_TYPES = {"TEXT", "INTEGER", "REAL", "BLOB"}
_JSON_TYPE_MAP = {"TEXT": "string", "INTEGER": "integer", "REAL": "number", "BLOB": "string"}

DEFAULT_SCHEMA = [
    {"name": "entity", "type": "TEXT", "primary_key": True},
    {"name": "label", "type": "TEXT"},
    {"name": "count", "type": "INTEGER"},
]


class MemoryTool:
    name = "memory"
    description = "Write a row to the structured output table."

    def __init__(self, schema: list, mode: str):
        self._schema = schema
        self._mode = mode  # "incremental" or "parallel"
        self._conn: Optional[sqlite3.Connection] = None
        self._pk_col = next(
            (c["name"] for c in schema if c.get("primary_key")), schema[0]["name"]
        )
        self._col_names = [c["name"] for c in schema]

    def initialize(self):
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        col_defs = []
        for col in self._schema:
            col_def = f'"{col["name"]}" {col["type"]}'
            if col.get("primary_key"):
                col_def += " PRIMARY KEY"
            col_defs.append(col_def)
        self._conn.execute(f'CREATE TABLE output ({", ".join(col_defs)})')
        self._conn.commit()

    def setup(self, chunk_path: str) -> None:
        pass  # shared across chunks, not per-chunk

    def schema(self) -> dict:
        def _col_label(c):
            parts = [c["type"]]
            if c.get("primary_key"):
                parts.append("primary key")
            if c.get("description"):
                parts.append(c["description"])
            return f'{c["name"]} ({", ".join(parts)})'

        col_descriptions = ", ".join(_col_label(c) for c in self._schema)
        mode_desc = (
            "upserts allowed" if self._mode == "incremental" else "insert-only, no duplicate primary keys"
        )
        properties = {
            c["name"]: {
                "type": _JSON_TYPE_MAP.get(c["type"], "string"),
                **({"description": c["description"]} if c.get("description") else {}),
            }
            for c in self._schema
        }
        return {
            "name": self.name,
            "description": (
                f"Write a row to the structured output table. "
                f"Columns: {col_descriptions}. Mode: {self._mode} — {mode_desc}."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "row": {
                        "type": "object",
                        "properties": properties,
                        "required": [self._pk_col],
                    }
                },
                "required": ["row"],
            },
        }

    def run(self, args: dict) -> dict:
        row = args.get("row")
        if not isinstance(row, dict):
            return {"error": "args.row must be an object"}

        unknown = set(row.keys()) - set(self._col_names)
        if unknown:
            return {
                "error": f"Unknown columns: {', '.join(sorted(unknown))}. "
                         f"Valid: {', '.join(self._col_names)}"
            }

        if row.get(self._pk_col) is None:
            return {"error": f"Primary key '{self._pk_col}' is required and must not be null"}

        coerced = {}
        for col in self._schema:
            col_name = col["name"]
            val = row.get(col_name)
            if val is None:
                coerced[col_name] = None
                continue
            col_type = col["type"]
            if col_type == "INTEGER":
                try:
                    coerced[col_name] = int(val)
                except (TypeError, ValueError):
                    return {"error": f"Column '{col_name}' expects INTEGER, got: {val!r}"}
            elif col_type == "REAL":
                try:
                    coerced[col_name] = float(val)
                except (TypeError, ValueError):
                    return {"error": f"Column '{col_name}' expects REAL, got: {val!r}"}
            else:
                coerced[col_name] = val

        placeholders = ", ".join("?" for _ in self._col_names)
        col_list = ", ".join(f'"{c}"' for c in self._col_names)
        values = [coerced.get(c) for c in self._col_names]

        sql = (
            f'INSERT OR REPLACE INTO output ({col_list}) VALUES ({placeholders})'
            if self._mode == "incremental"
            else f'INSERT OR FAIL INTO output ({col_list}) VALUES ({placeholders})'
        )
        try:
            self._conn.execute(sql, values)
            self._conn.commit()
            return {"ok": True}
        except sqlite3.IntegrityError:
            pk_val = coerced.get(self._pk_col)
            return {"error": f"duplicate key: {pk_val}"}
        except sqlite3.Error as e:
            return {"error": str(e)}

    def dump(self) -> list:
        if self._conn is None:
            return []
        cursor = self._conn.execute("SELECT * FROM output")
        col_names = [d[0] for d in cursor.description]
        return [dict(zip(col_names, row)) for row in cursor.fetchall()]
