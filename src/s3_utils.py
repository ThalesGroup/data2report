import boto3
from botocore.exceptions import ClientError


def object_exists(bucket: str, key: str, session: boto3.session.Session) -> bool:
    s3_client = session.client("s3")
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        else:
            raise e
