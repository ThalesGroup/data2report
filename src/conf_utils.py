import json
import os
from typing import Optional, List

from utils import get_reports_folder


def validate_configuration(configuration: dict, report_id: Optional[str]) -> List[str]:
    errors = []
    if "id" not in configuration or not configuration["id"]:
        errors.append("Missing report id")
    elif report_id and configuration["id"] != report_id:
        errors.append(
            "Report id in configuration does not match the provided report_id"
        )
    if "llm" not in configuration:
        errors.append("Missing 'llm' section in configuration")
    else:
        llm = configuration["llm"]
        if not llm.get("model_id"):
            errors.append("llm.model_id is required")
        temp = llm.get("temperature")
        if temp is None or not (0 <= temp <= 1):
            errors.append("llm.temperature must be between 0 and 1")
        max_tok = llm.get("max_tokens")
        if not isinstance(max_tok, int) or max_tok <= 0:
            errors.append("llm.max_tokens must be a positive integer")
    if "report" not in configuration:
        errors.append("Missing 'report' section in configuration")
    else:
        rpt = configuration["report"]
        chunk = rpt.get("chunk_size")
        if not isinstance(chunk, int) or chunk <= 0:
            errors.append("report.chunk_size must be a positive integer")

        incr = rpt.get("incremental")
        workers = rpt.get("max_workers")
        if incr is True and workers != 1:
            errors.append("For incremental mode, report.max_workers must be 1")
        if incr is False and (not isinstance(workers, int) or workers < 1):
            errors.append("report.max_workers must be >=1")
    return errors


def get_conf_folder() -> str:
    return os.path.join(get_reports_folder(), "configuration")


def get_config_file(report_id: str) -> str:
    return os.path.join(get_conf_folder(), f"{report_id}.json")


def get_report_config(report_id: str) -> dict:
    configuration_file = get_config_file(report_id)
    if not os.path.exists(configuration_file) or not os.path.isfile(configuration_file):
        raise FileNotFoundError(
            f"Report configuration file '{configuration_file}' not found"
        )
    with open(configuration_file, "r") as f:
        configuration = json.load(f)
    return configuration


def save_report(configuration: dict) -> None:
    if "id" not in configuration or not configuration["id"]:
        raise ValueError("Configuration must have a valid 'id' field")
    conf_folder = get_conf_folder()
    if not os.path.exists(conf_folder):
        os.makedirs(conf_folder)
    conf_file = get_config_file(configuration["id"])
    with open(conf_file, "w") as f:
        json.dump(configuration, f, indent=2)


def list_reports() -> List[str]:
    conf_folder = get_conf_folder()
    if not os.path.exists(conf_folder):
        return []
    return [
        f[:-5]
        for f in os.listdir(conf_folder)
        if f.endswith(".json") and os.path.isfile(os.path.join(conf_folder, f))
    ]
