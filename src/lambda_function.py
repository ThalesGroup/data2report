import base64
import json
import logging
from typing import Dict, Any, Optional

from boto3.session import Session

from conf_utils import save_report, get_report_config, delete_report
from data2report import run_report


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
    if "report_id" not in event:
        return {"error": "report_id not sent"}
    input_key = _get_input_key(event)
    if input_key is None:
        return {"error": "input_key not sent and event is not S3 put"}
    force = event.get("force", False)
    max_records = event.get("max_records")
    run_id = event.get("run_id")
    return run_report(
        input_key,
        event["report_id"],
        run_id=run_id,
        force=force,
        max_records=max_records,
    )


def _get_input_key(event: dict) -> Optional[str]:
    if "input_key" in event:
        return event["input_key"]
    elif _is_s3_put_event(event):
        r = event["Records"][0]
        return f"s3://{r['s3']['bucket']['name']}/{r['s3']['object']['key']}"
    else:
        return None


def _is_s3_put_event(event) -> bool:
    for record in event.get("Records", []):
        if record.get("eventSource") == "aws:s3":
            event_name = record.get("eventName", "")
            if event_name.startswith("ObjectCreated:Put"):
                return True
    return False
