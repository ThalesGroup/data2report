import logging
import os
from typing import List

from boto3.session import Session
from botocore.exceptions import ClientError


def get_reports_bucket() -> str:
    return os.environ["REPORTS_BUCKET"]


def object_exists(bucket: str, key: str, session: Session) -> bool:
    s3_client = session.client("s3")
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        else:
            raise e


def upload_content(bucket: str, object_path: str, content: str, session: Session):
    s3_resource = session.resource("s3")
    try:
        logging.info(f"Writing file to S3. Key: {object_path}")
        obj = s3_resource.Object(bucket, object_path)
        obj.put(Body=content, ACL="bucket-owner-full-control")
    except Exception as e:
        logging.error(f"❌ Error uploading content: {e}")
        raise


def upload_file(bucket: str, file_name: str, object_path: str, session: Session):
    s3_client = session.client("s3")
    try:
        logging.info(f"Uploading file to S3. Key: {object_path}")
        s3_client.upload_file(file_name, bucket, object_path)
    except Exception as e:
        logging.error(f"❌ Error uploading file: {e}")
        raise


def list_folder(bucket: str, folder: str, session: Session) -> List[str]:
    s3_client = session.client("s3")
    result = s3_client.list_objects(Bucket=bucket, Prefix=folder)
    contents = result.get("Contents")
    if contents:
        return [key["Key"] for key in contents]
    else:
        return []


def clear_folder(bucket: str, s3_folder: str, session: Session) -> int:
    if not s3_folder.endswith("/"):
        s3_folder += "/"  # make sure to delete only the context of a folder
    s3 = session.resource("s3")
    bucket = s3.Bucket(bucket)
    res = bucket.objects.filter(Prefix=s3_folder).delete()
    if len(res) == 0:
        return 0
    elif "Errors" in res[0]:
        raise Exception(
            f"Errors found: {len(res[0]['Errors'])}, First error: {res[0]['Errors'][0]}"
        )
    elif "Deleted" not in res[0]:
        return 0
    else:
        return len(res[0]["Deleted"])


def download_object(bucket: str, key: str, local_path: str, session: Session):
    s3 = session.client("s3")
    try:
        s3.download_file(bucket, key, local_path)
        logging.info(f"Downloaded {key} from bucket {bucket} to {local_path}")
    except ClientError as e:
        logging.error(f"❌ Failed to download {key} from bucket {bucket}: {e}")
        raise
    except Exception as e:
        logging.error(f"❌ Error downloading file: {e}")
        raise
