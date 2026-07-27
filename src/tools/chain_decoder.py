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

import base64
import binascii
import gzip
import re
import urllib.parse

_MAX_DEPTH = 5
_MAX_BYTES = 4096
_PRINTABLE_THRESHOLD = 0.8

_DECODERS = ["url", "base64", "hex", "gzip", "utf8", "js_escape"]


class ChainDecoderTool:
    name = "chain_decoder"
    description = (
        "Decode an obfuscated string by trying URL, base64, hex, gzip, and JS-escape "
        "decoders in a greedy chain until the output stabilizes. "
        "Useful for decoding payloads, commands, or shellcode found in attack logs."
    )

    def setup(self, chunk_path: str) -> None:
        pass  # stateless — no per-chunk init needed

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "value": {
                        "type": "string",
                        "description": "The encoded or obfuscated string to decode.",
                    }
                },
                "required": ["value"],
            },
        }

    def run(self, args: dict) -> dict:
        value = args.get("value", "")
        decoded, chain, truncated = _decode_chain(value)
        return {"decoded": decoded, "chain": chain, "truncated": truncated}


def _decode_chain(value: str) -> tuple[str, list[str], bool]:
    chain = []
    current = value
    for _ in range(_MAX_DEPTH):
        advanced = False
        for decoder_name in _DECODERS:
            result = _try_decode(decoder_name, current)
            if result is not None and result != current:
                chain.append(decoder_name)
                current = result
                advanced = True
                break
        if not advanced:
            break

    truncated = False
    if len(current.encode("utf-8", errors="replace")) > _MAX_BYTES:
        current = current.encode("utf-8", errors="replace")[:_MAX_BYTES].decode(
            "utf-8", errors="replace"
        )
        truncated = True

    return current, chain, truncated


def _try_decode(name: str, value: str) -> str | None:
    try:
        if name == "url":
            decoded = urllib.parse.unquote(value)
            if decoded != value and _is_printable(decoded):
                return decoded

        elif name == "base64":
            # tolerate missing padding
            padded = value + "=" * (-len(value) % 4)
            raw = base64.b64decode(padded, validate=False)
            text = raw.decode("utf-8", errors="replace")
            if _is_printable(text):
                return text

        elif name == "hex":
            # match \xNN or plain NNNN... hex strings
            stripped = re.sub(r"\\x", "", value)
            stripped = stripped.replace("0x", "").replace(" ", "")
            if len(stripped) % 2 == 0 and re.fullmatch(r"[0-9a-fA-F]+", stripped):
                raw = bytes.fromhex(stripped)
                text = raw.decode("utf-8", errors="replace")
                if _is_printable(text):
                    return text

        elif name == "gzip":
            raw = base64.b64decode(value + "=" * (-len(value) % 4), validate=False)
            text = gzip.decompress(raw).decode("utf-8", errors="replace")
            if _is_printable(text):
                return text

        elif name == "utf8":
            # handle \uXXXX unicode escapes
            decoded = value.encode("utf-8").decode("unicode_escape", errors="replace")
            if decoded != value and _is_printable(decoded):
                return decoded

        elif name == "js_escape":
            # handle \xNN JS escapes
            decoded = re.sub(
                r"\\x([0-9a-fA-F]{2})",
                lambda m: chr(int(m.group(1), 16)),
                value,
            )
            if decoded != value and _is_printable(decoded):
                return decoded

    except (binascii.Error, UnicodeDecodeError, OSError, ValueError):
        pass

    return None


def _is_printable(text: str) -> bool:
    if not text:
        return False
    printable = sum(1 for c in text if c.isprintable() or c in "\n\r\t")
    return printable / len(text) >= _PRINTABLE_THRESHOLD
