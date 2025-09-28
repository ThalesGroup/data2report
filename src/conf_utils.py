import json
import os
from typing import Optional, List

from boto3.session import Session

from s3_utils import (
    download_object,
    get_reports_bucket,
    get_data2reports_prefix,
    upload_file,
)
from utils import get_reports_folder, is_s3_configured


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


def get_config_s3_key(report_id: str) -> str:
    result = f"{get_data2reports_prefix()}/configuration/{report_id}.json"
    return result.replace("//", "/").lstrip("/")


def get_report_config(report_id: str, session: Session = None) -> dict:
    configuration_file = get_config_file(report_id)
    if is_s3_configured():
        session = Session()
        with open(configuration_file, mode="w") as f:
            download_object(
                get_reports_bucket(),
                get_config_s3_key(report_id),
                f.name,
                session,
            )
    if not os.path.exists(configuration_file) or not os.path.isfile(configuration_file):
        raise FileNotFoundError(
            f"Report configuration file '{configuration_file}' not found"
        )
    with open(configuration_file, "r") as f:
        configuration = json.load(f)
    return configuration


def save_report(configuration: dict, session: Session = None) -> dict:
    if "id" not in configuration or not configuration["id"]:
        raise ValueError("Configuration must have a valid 'id' field")
    conf_folder = get_conf_folder()
    if not os.path.exists(conf_folder):
        os.makedirs(conf_folder)
    conf_file = get_config_file(configuration["id"])
    with open(conf_file, "w") as f:
        json.dump(configuration, f, indent=2)
    if is_s3_configured():
        upload_key = get_config_s3_key(configuration["id"])
        upload_file(get_reports_bucket(), conf_file, upload_key, session)
    else:
        upload_key = None
    return {
        "report_id": configuration["id"],
        "configuration_file": conf_file,
        "s3_key": upload_key,
    }


def delete_report(report_id: str, session: Session = None) -> dict:
    conf_file = get_config_file(report_id)
    if os.path.exists(conf_file) and os.path.isfile(conf_file):
        os.remove(conf_file)
    if is_s3_configured():
        s3_client = session.client("s3")
        s3_key = get_config_s3_key(report_id)
        s3_client.delete_object(Bucket=get_reports_bucket(), Key=s3_key)
    else:
        s3_key = None
    return {"report_id": report_id, "configuration_file": conf_file, "s3_key": s3_key}


def list_reports() -> List[str]:
    conf_folder = get_conf_folder()
    if not os.path.exists(conf_folder):
        return []
    return [
        f[:-5]
        for f in os.listdir(conf_folder)
        if f.endswith(".json") and os.path.isfile(os.path.join(conf_folder, f))
    ]
