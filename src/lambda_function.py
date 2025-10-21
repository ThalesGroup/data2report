import base64
import json
import logging
import os
import urllib.parse
from typing import Dict, Any, Optional

from boto3.session import Session

from conf_utils import save_report, get_report_config, delete_report
from data2report import run_report

_PREFIX_TO_REPORT_ENV_VAR = "PREFIX_TO_REPORT"


# noinspection PyUnusedLocal
def lambda_handler(event, context):
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger("botocore.credentials").addFilter(
        lambda record: "Found credentials in environment variables"
        not in record.getMessage()
    )
    logging.info("Code version: $VERSION$")
    try:
        result = handle_event(event)
        logging.info(result)
        return result
    except Exception as e:
        logging.exception(f"Error running lambda_handler: {str(e)}")
        return {"error": str(e)}


def handle_event(event) -> Dict[str, Any]:
    logging.info(f"Event: {event}")
    if _is_s3_object_created_event(event):
        logging.info("Detected S3 ObjectCreated event")
        operation = "run_report"
    else:
        if "operation" not in event:
            raise Exception("Operation not sent")
        operation = event["operation"]
    if operation == "run_report":
        return _run_report(event)
    elif operation == "upload_report":
        conf_data = base64.b64decode(event["data"]).decode()
        json_data = json.loads(conf_data)
        return save_report(json_data, session=Session())
    elif operation == "get_report":
        if "report_id" not in event:
            return {"error": "report_id not sent"}
        report = get_report_config(event["report_id"], session=Session())
        return report
    elif operation == "delete_report":
        if "report_id" not in event:
            return {"error": "report_id not sent"}
        report_id = event["report_id"]
        return delete_report(report_id, session=Session())
    else:
        return {"error": f"Unknown operation: {operation}"}


def _run_report(event):
    if _is_s3_object_created_event(event):
        report_id = None
        logging.info("Handling S3 ObjectCreated event for run_report")
        if _PREFIX_TO_REPORT_ENV_VAR not in os.environ:
            return {
                "error": f"{_PREFIX_TO_REPORT_ENV_VAR} environment variable not set"
            }
        prefix_to_report = json.loads(os.environ[_PREFIX_TO_REPORT_ENV_VAR])
        s3_record = event["Records"][0]
        s3_key = urllib.parse.unquote_plus(s3_record["s3"]["object"]["key"])
        for prefix in prefix_to_report:
            if s3_key.startswith(prefix):
                report_id = prefix_to_report[prefix]
                logging.info(f"Matched prefix '{prefix}' to report_id '{report_id}'")
                break
        if not report_id:
            return {"error": f"No matching prefix found for S3 key: {s3_key}"}
    elif "report_id" not in event:
        return {"error": "report_id not sent"}
    else:
        report_id = event["report_id"]
    input_key = _get_input_key(event)
    if input_key is None:
        return {"error": "input_key not sent and event is not S3 put"}
    force = event.get("force", False)
    max_records = event.get("max_records")
    run_id = event.get("run_id")
    return run_report(
        input_key,
        report_id,
        run_id=run_id,
        force=force,
        max_records=max_records,
    )


def _get_input_key(event: dict) -> Optional[str]:
    if "input_key" in event:
        return event["input_key"]
    elif _is_s3_object_created_event(event):
        r = event["Records"][0]
        key = urllib.parse.unquote_plus(r["s3"]["object"]["key"])
        return f"s3://{r["s3"]["bucket"]["name"]}/{key}"
    else:
        return None


def _is_s3_object_created_event(event) -> bool:
    for record in event.get("Records", []):
        if record.get("eventSource") == "aws:s3":
            event_name = record.get("eventName", "")
            if event_name.startswith("ObjectCreated:"):
                return True
    return False
