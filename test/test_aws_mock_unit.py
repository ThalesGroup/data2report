import gzip
import os
from tempfile import NamedTemporaryFile
from unittest.mock import patch

import pytest
from boto3.session import Session
from moto import mock_aws

from conftest import get_config
from data2report import run_report
from s3_utils import (
    object_exists,
    get_reports_bucket,
    upload_file,
    upload_content,
    clear_folder,
    list_folder,
    download_object,
)


@pytest.fixture()
def reports_bucket(monkeypatch):
    monkeypatch.setenv("REPORTS_BUCKET", "my-bucket")
    yield get_reports_bucket()
    monkeypatch.delenv("REPORTS_BUCKET", raising=False)


class TestS3Utils:
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


@mock_aws
def test_report_with_s3(reports_bucket, reports_folder, csv_file_with_1k_lines):
    session = Session()
    s3_client = session.client("s3")
    s3_client.create_bucket(Bucket=get_reports_bucket())
    key = "input-folder/input-key.csv.gz"
    upload_file(reports_bucket, csv_file_with_1k_lines, key, session)

    mocked_response = {
        "usage": {"input_tokens": 10, "output_tokens": 20},
        "content": "Report",
    }

    with patch("report_processing.invoke_llm", return_value=mocked_response):
        result = run_report(
            f"s3://{reports_bucket}/{key}",
            configuration=get_config("test_report"),
        )
        assert os.path.exists(os.path.join(result["output_folder"], "final_report.gz"))
        s3_uri = result["s3_uri"]
        bucket, object_key = s3_uri[5:].split("/", 1)
        assert object_exists(bucket, object_key, session)
        with NamedTemporaryFile() as tmp:
            download_object(bucket, object_key, tmp.name, session)
            with gzip.open(tmp.name, "rt") as f:
                s3_content = f.read()
        with gzip.open(
            os.path.join(result["output_folder"], "final_report.gz"), "rt"
        ) as f:
            local_content = f.read()
        assert s3_content == local_content
