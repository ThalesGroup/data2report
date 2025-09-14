from moto import mock_aws

from boto3.session import Session
from s3_utils import object_exists


@mock_aws
def test_object_exists():
    session = Session()
    s3_client = session.client("s3")
    s3_client.create_bucket(Bucket="my-bucket")
    assert not object_exists("my-bucket", "my-key", session)
    s3_client = session.client("s3")
    s3_client.put_object(Bucket="my-bucket", Key="my-key", Body="data")
    assert object_exists("my-bucket", "my-key", session)
