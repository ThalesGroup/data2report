from tempfile import NamedTemporaryFile

import pytest
from boto3.session import Session
from moto import mock_aws

from s3_utils import (
    object_exists,
    get_reports_bucket,
    upload_file,
    upload_content,
    clear_folder,
    list_folder,
    download_object,
)


class TestS3Utils:

    @pytest.fixture()
    def reports_bucket(self, monkeypatch):
        monkeypatch.setenv("REPORTS_BUCKET", "my-bucket")
        yield get_reports_bucket()
        monkeypatch.delenv("REPORTS_BUCKET", raising=False)

    @mock_aws
    def test_s3_operations(self, empty_file, reports_bucket):
        session = Session()
        s3_client = session.client("s3")
        s3_client.create_bucket(Bucket=get_reports_bucket())
        upload_file(reports_bucket, empty_file, "my-folder/my-key1", session)
        assert object_exists(reports_bucket, "my-folder/my-key1", session)
        assert list_folder(reports_bucket, "my-folder", session) == [
            "my-folder/my-key1"
        ]
        with NamedTemporaryFile() as tmp:
            download_object(reports_bucket, "my-folder/my-key1", tmp.name, session)
            with open(tmp.name, "r") as f:
                assert f.read() == ""
        assert not object_exists(reports_bucket, "my-folder/my-key2", session)
        upload_content(reports_bucket, "my-folder/my-key2", "data", session)
        assert object_exists(reports_bucket, "my-folder/my-key2", session)
        assert list_folder(reports_bucket, "my-folder", session) == [
            "my-folder/my-key1",
            "my-folder/my-key2",
        ]
        clear_folder(reports_bucket, "my-folder", session)
        assert list_folder(reports_bucket, "my-folder", session) == []
        assert not object_exists(reports_bucket, "my-folder/my-key", session)
        s3_client.delete_bucket(Bucket=get_reports_bucket())
