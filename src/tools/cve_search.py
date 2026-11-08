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

import json
import logging
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from typing import Optional

_NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
_TIMEOUT_SECONDS = 10
_MAX_RESPONSE_BYTES = 2_000_000
_DEFAULT_RESULTS = 5
_MAX_RESULTS = 10
_MAX_KEYWORD_CHARS = 100
_MAX_DESCRIPTION_CHARS = 600
_MAX_REFERENCES = 3
_CACHE_SIZE = 256
_CVE_ID = re.compile(r"^CVE-\d{4}-\d{4,}$")
_SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
# Newest CVSS version first.
_CVSS_KEYS = ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2")

_cache: "OrderedDict[str, dict]" = OrderedDict()
_cache_lock = threading.Lock()


def _http_get_json(params: dict) -> dict:
    """GET the NVD API and return the parsed JSON. Raises RuntimeError on failure."""
    headers = {"User-Agent": "data2report-cve-search"}
    api_key = os.environ.get("NVD_API_KEY")
    if api_key:
        headers["apiKey"] = api_key
    request = urllib.request.Request(
        f"{_NVD_URL}?{urllib.parse.urlencode(params)}", headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return json.loads(response.read(_MAX_RESPONSE_BYTES))
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise RuntimeError(
                "NVD rate limit reached; retry later (set NVD_API_KEY for a higher limit)"
            )
        if e.code == 404:
            raise RuntimeError("NVD returned 404 for this query")
        raise RuntimeError(f"NVD request failed with HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"could not reach NVD: {getattr(e, 'reason', e)}")
    except ValueError:
        raise RuntimeError("NVD returned an invalid response")


def _cached_get(params: dict) -> dict:
    key = json.dumps(params, sort_keys=True)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    data = _http_get_json(params)
    with _cache_lock:
        _cache[key] = data
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return data


def _cvss(metrics: dict) -> Optional[dict]:
    for key in _CVSS_KEYS:
        entries = metrics.get(key) or []
        if not entries:
            continue
        # Prefer the primary (NVD) score over secondary sources.
        entry = next((e for e in entries if e.get("type") == "Primary"), entries[0])
        data = entry.get("cvssData", {})
        return {
            "version": data.get("version"),
            "score": data.get("baseScore"),
            "severity": data.get("baseSeverity") or entry.get("baseSeverity"),
            "vector": data.get("vectorString"),
        }
    return None


def _summarize(cve: dict) -> dict:
    description = next(
        (d.get("value", "") for d in cve.get("descriptions", []) if d.get("lang") == "en"),
        "",
    )
    if len(description) > _MAX_DESCRIPTION_CHARS:
        description = description[:_MAX_DESCRIPTION_CHARS] + "…"
    cwes = sorted({
        d["value"]
        for w in cve.get("weaknesses", [])
        for d in w.get("description", [])
        if d.get("lang") == "en" and d.get("value", "").startswith("CWE-")
    })
    return {
        "id": cve.get("id"),
        "published": cve.get("published"),
        "last_modified": cve.get("lastModified"),
        "status": cve.get("vulnStatus"),
        "cvss": _cvss(cve.get("metrics", {})),
        "description": description,
        "cwes": cwes,
        "in_cisa_kev": bool(cve.get("cisaExploitAdd")),
        "references": [r["url"] for r in cve.get("references", []) if r.get("url")][:_MAX_REFERENCES],
    }


class CveSearchTool:
    name = "cve_search"
    description = (
        "Look up vulnerabilities in the NIST National Vulnerability Database (NVD). "
        "Pass `cve_id` (for example CVE-2021-44228) for one CVE, or `keyword` to search "
        "descriptions (for example 'apache struts' or 'log4j remote code execution'), "
        "optionally narrowed with `severity`. Returns the CVSS score and severity, "
        "description, CWE weaknesses, whether the CVE is in CISA's Known Exploited "
        "Vulnerabilities catalog, publication dates and a few references. "
        "This sends the query to the internet (services.nvd.nist.gov); never include "
        "sensitive data from the report in it."
    )
    ui_description = (
        "Lets the LLM look up CVEs in the NVD: scores, descriptions, weaknesses, and "
        "whether a vulnerability is known to be exploited. Sends queries to the internet."
    )

    def setup(self, chunk_path: str) -> None:
        pass  # stateless

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "cve_id": {
                        "type": "string",
                        "description": "A CVE identifier such as CVE-2021-44228. Use this or `keyword`.",
                    },
                    "keyword": {
                        "type": "string",
                        "description": "Words to search for in CVE descriptions. Use this or `cve_id`.",
                    },
                    "severity": {
                        "type": "string",
                        "enum": list(_SEVERITIES),
                        "description": "Only with `keyword`: restrict to this CVSS v3 severity.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": f"Keyword search only (default {_DEFAULT_RESULTS}, cap {_MAX_RESULTS}).",
                    },
                },
            },
        }

    def run(self, args: dict) -> dict:
        cve_id, keyword = args.get("cve_id"), args.get("keyword")
        if bool(cve_id) == bool(keyword):
            return {"error": "provide exactly one of `cve_id` or `keyword`"}

        if cve_id:
            cve_id = str(cve_id).strip().upper()
            if not _CVE_ID.match(cve_id):
                return {"error": "cve_id must look like CVE-2021-44228"}
            params = {"cveId": cve_id}
        else:
            keyword = str(keyword).strip()
            if not keyword or len(keyword) > _MAX_KEYWORD_CHARS:
                return {"error": f"keyword must be 1-{_MAX_KEYWORD_CHARS} characters"}
            try:
                limit = int(args.get("max_results") or _DEFAULT_RESULTS)
            except (TypeError, ValueError):
                return {"error": "max_results must be an integer"}
            params = {
                "keywordSearch": keyword,
                "resultsPerPage": max(1, min(limit, _MAX_RESULTS)),
            }
            severity = args.get("severity")
            if severity:
                severity = str(severity).upper()
                if severity not in _SEVERITIES:
                    return {"error": f"severity must be one of {list(_SEVERITIES)}"}
                params["cvssV3Severity"] = severity

        try:
            data = _cached_get(params)
        except RuntimeError as e:
            logging.warning(f"cve_search failed: {e}")
            return {"error": str(e)}

        results = [_summarize(v.get("cve", {})) for v in data.get("vulnerabilities", [])]
        total = data.get("totalResults", len(results))
        if cve_id and not results:
            return {"error": f"{cve_id} not found in NVD"}
        return {"results": results, "total_results": total, "truncated": total > len(results)}
