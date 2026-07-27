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

from typing import Protocol, runtime_checkable


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str

    def schema(self) -> dict:
        """Return the Bedrock/Anthropic tool_use schema for this tool."""
        ...

    def setup(self, chunk_path: str) -> None:
        """Optional per-chunk initialization (e.g. load data into sqlite)."""
        ...

    def run(self, args: dict) -> dict:
        """Execute the tool call and return a tool_result-compatible dict."""
        ...
