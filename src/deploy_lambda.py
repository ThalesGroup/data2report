# Copyright 2026 Thales
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import http.client
import json
import logging
import os
import tempfile
from time import sleep
from typing import List

import boto3
from botocore.exceptions import ClientError

from utils import init_env_from_file

_REQUIRED_ENV_VARS = ["REPORTS_BUCKET"]
_OPTIONAL_ENV_VARS = ["DATA2REPORT_PREFIX"]
_DEFAULT_FUNCTION_NAME = "data2report"

_GITHUB_REPO_OWNER = "ThalesGroup"
_GITHUB_REPO_NAME = "data2report"


def _get_lambda_arn() -> str:
    sts_client = boto3.client("sts")
    region = os.environ["AWS_DEFAULT_REGION"]
    account_id = sts_client.get_caller_identity()["Account"]
    return f"arn:aws:lambda:{region}:{account_id}:function:{_get_function_name()}"


def deploy(version: str, update_config: bool = False, update_code: bool = True):
    env_vars = {v: os.environ[v] for v in _REQUIRED_ENV_VARS}
    client = boto3.client("lambda")
    for env_var_name in _REQUIRED_ENV_VARS:
        if env_var_name not in env_vars:
            raise Exception(f"Missing env var: {env_var_name}")
    for env_var_name in _OPTIONAL_ENV_VARS:
        if env_var_name in os.environ:
            env_vars[env_var_name] = os.environ[env_var_name]
    env_data = {"Variables": env_vars}
    lambda_timeout = 600
    description = "aws:states:opt-out"
    if not _function_exists():
        print("Function does not exist. Creating it")
        dep_package = _get_package(version)
        with open(dep_package, "rb") as file:
            client.create_function(
                FunctionName=_get_function_name(),
                Runtime="python3.13",
                Role=os.environ["LAMBDA_ROLE"],
                Description=description,
                Environment=env_data,
                Timeout=lambda_timeout,
                Code={"ZipFile": file.read()},
                Handler="lambda_function.lambda_handler",
                Publish=True,
                Architectures=["arm64"],
            )
        return
    if update_config:
        print("Function exists. Updating config")
        response = client.get_function_configuration(FunctionName=_get_function_name())
        old_env = response.get("Environment", {}).get("Variables", {})
        for e in old_env:
            if e not in env_vars:
                env_vars[e] = old_env[e]
        client.update_function_configuration(
            FunctionName=_get_function_name(),
            Description=description,
            Environment=env_data,
            Timeout=lambda_timeout,
        )
    if update_code:
        dep_pacakge = _get_package(version)
        print("Function exists. Updating code")
        if update_config:
            sleep(5)  # avoid resource update conflict
        with open(dep_pacakge, "rb") as file:
            client.update_function_code(
                FunctionName=_get_function_name(),
                ZipFile=file.read(),
                Publish=True,
            )


def uninstall_function():
    lambda_client = boto3.client("lambda")
    lambda_client.delete_function(FunctionName=_get_function_name())


def _function_exists():
    client = boto3.client("lambda")
    try:
        client.get_function(FunctionName=_get_function_name())
        return True
    except ClientError as error:
        if error.response["Error"]["Code"] == "ResourceNotFoundException":
            return False
        else:
            raise error


def _get_function_name() -> str:
    return os.environ.get("FUNCTION_NAME", _DEFAULT_FUNCTION_NAME)


def _get_package(pacakge_version: str) -> str:
    if pacakge_version == "sources":
        from pack_sources import zip_sources

        return zip_sources()
    elif pacakge_version == "latest":
        return _download_sources("latest")
    else:
        versions = _get_versions()
        if pacakge_version not in versions:
            raise ValueError(f"Unknown version: {pacakge_version}")
        return _download_sources(pacakge_version)


def _github_api_request(url: str = None) -> dict:
    conn = None
    try:
        conn = http.client.HTTPSConnection("api.github.com")
        headers = {
            "User-Agent": "Python http.client",
            "Accept": "application/vnd.github.v3+json",
        }
        if "GITHUB_TOKEN" in os.environ:
            headers["Authorization"] = f"token {os.environ['GITHUB_TOKEN']}"
        final_url = f"/repos/{_GITHUB_REPO_OWNER}/{_GITHUB_REPO_NAME}"
        logging.info("Going to download from github repo: %s", final_url)
        if url:
            final_url += f"/{url}"
        conn.request("GET", final_url, headers=headers)
        response = conn.getresponse()
        if response.status == 404:
            raise ValueError("Repository not found or you do not have access.")
        elif response.status == 403:
            if response.getheader("X-RateLimit-Remaining") == "0":
                raise ValueError("API rate limit exceeded.")
            else:
                raise ValueError(
                    "Access forbidden. Check your token permissions or repository access."
                )
        elif response.status != 200:
            raise ValueError(f"Unknown error: {response.read().decode()}")
        else:
            return json.loads(response.read().decode())
    finally:
        if conn:
            conn.close()


def _get_versions() -> List[str]:
    releases = _github_api_request("releases")
    return [r["tag_name"] for r in releases]


def _download_sources(version: str):
    if version == "latest":
        release = _github_api_request(f"releases/latest")
    else:
        release = _github_api_request(f"releases/tags/{version}")
    asset = release["assets"][0]
    logging.info(
        "Tag Name: %s. Published at: %s", release["tag_name"], release["published_at"]
    )
    conn = None
    try:
        conn = http.client.HTTPSConnection("api.github.com")
        headers = {
            "User-Agent": "Python http.client",
            "Accept": "application/octet-stream",
        }
        if "GITHUB_TOKEN" in os.environ:
            headers["Authorization"] = f"token {os.environ['GITHUB_TOKEN']}"
        conn.request(
            "GET",
            f"/repos/{_GITHUB_REPO_OWNER}/{_GITHUB_REPO_NAME}/releases/assets/{asset['id']}",
            headers=headers,
        )
        response = conn.getresponse()
        if response.status == 302:
            download_url = response.getheader("Location")
            conn.close()
            conn = http.client.HTTPSConnection(download_url.split("/")[2])
            conn.request(
                "GET",
                download_url.split(download_url.split("/")[2])[1],
                headers=headers,
            )
            response = conn.getresponse()
            file_name = os.path.join(tempfile.gettempdir(), asset["name"])
            with open(file_name, "wb") as file:
                file.write(response.read())
            return file_name
        else:
            raise ValueError(f"Failed to download asset: {response.status}")
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_env_from_file()
    operation = os.environ["OPERATION"]
    if operation == "uninstall":
        uninstall_function()
    elif operation == "install":
        deploy(
            os.environ.get("VERSION", "sources"),
            update_config=os.environ.get("UPDATE_CONFIG", "true").lower() == "true",
            update_code=os.environ.get("UPDATE_CODE", "true").lower() == "true",
        )
    else:
        raise ValueError(f"Unknown operation: {operation}")
