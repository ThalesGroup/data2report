import base64
import gzip
import json
import os
from tempfile import NamedTemporaryFile
from unittest.mock import patch

import pytest
from boto3.session import Session
from moto import mock_aws

from conf_utils import save_report, delete_report
from conftest import get_config, mock_llm
from data2report import run_report
from lambda_function import handle_event
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


@mock_aws
def test_upload_report(reports_bucket):
    session = Session()
    s3_client = session.client("s3")
    s3_client.create_bucket(Bucket=get_reports_bucket())
    conf = get_config("test_report")
    result = save_report(conf, session)
    assert result["s3_key"] == "configuration/test_report.json"
    delete_report(conf["id"], session)
    s3_client.delete_bucket(Bucket=get_reports_bucket())


@mock_aws
def test_lambda_operations(
    reports_bucket, reports_folder, monkeypatch, csv_file_with_1k_lines
):
    session = Session()
    monkeypatch.setenv("DATA2REPORTS_PREFIX", "data2report")
    s3_client = session.client("s3")
    s3_client.create_bucket(Bucket=get_reports_bucket())
    conf = get_config("test_report")
    b64_conf = base64.b64encode(json.dumps(conf).encode("utf-8"))
    result = handle_event({"operation": "upload_report", "data": b64_conf})
    assert result["s3_key"] == "data2report/configuration/test_report.json"
    input_key = "tmp/input/input.csv.gz"
    upload_file(get_reports_bucket(), csv_file_with_1k_lines, input_key, session)
    full_key = f"s3://{get_reports_bucket()}/{input_key}"
    with mock_llm():
        result = handle_event(
            {"operation": "run_report", "report_id": conf["id"], "input_key": full_key}
        )
        assert (
            result["s3_uri"]
            == "s3://my-bucket/data2report/reports/report=test_report/run=2025-09-28/final_report.gz"
        )
        result = handle_event(
            {"operation": "run_report", "report_id": conf["id"], "input_key": full_key}
        )
        assert (
            result["s3_uri"]
            == "s3://my-bucket/data2report/reports/report=test_report/run=2025-09-28/final_report.gz"
        )
    result = handle_event({"operation": "delete_report", "report_id": conf["id"]})
    assert result["s3_key"] == "data2report/configuration/test_report.json"
    assert clear_folder(get_reports_bucket(), "tmp/", session) == 1
    assert clear_folder(get_reports_bucket(), "data2report/reports/", session) == 1
    s3_client.delete_bucket(Bucket=get_reports_bucket())
