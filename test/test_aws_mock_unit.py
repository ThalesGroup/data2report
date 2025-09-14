import pytest
from boto3.session import Session
from moto import mock_aws

from s3_utils import object_exists, get_reports_bucket


@pytest.fixture()
def reports_bucket(monkeypatch):
    monkeypatch.setenv("REPORTS_BUCKET", "my-bucket")
    yield get_reports_bucket()
    monkeypatch.delenv("REPORTS_BUCKET", raising=False)


@mock_aws
def test_object_exists(reports_bucket):
    session = Session()
    s3_client = session.client("s3")
    s3_client.create_bucket(Bucket=get_reports_bucket())
    assert not object_exists(reports_bucket, "my-key", session)
    s3_client = session.client("s3")
    s3_client.put_object(Bucket=reports_bucket, Key="my-key", Body="data")
    assert object_exists(reports_bucket, "my-key", session)
