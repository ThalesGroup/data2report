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

from tools.chain_decoder import ChainDecoderTool
from tools.query_data import QueryDataTool

# Maps tool name → class. Add new primitives here.
REGISTRY = {
    QueryDataTool.name: QueryDataTool,
    ChainDecoderTool.name: ChainDecoderTool,
}


def list_tools() -> list[dict]:
    """Return [{name, description}] for every registered tool."""
    return [
        {"name": cls.name, "description": cls.description}
        for cls in REGISTRY.values()
    ]


def get_tool(name: str):
    """Instantiate and return a tool by name, or raise ValueError if unknown."""
    cls = REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown tool: '{name}'. Available: {list(REGISTRY)}")
    return cls()
