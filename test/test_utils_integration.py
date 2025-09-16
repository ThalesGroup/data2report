import pytest
from boto3.session import Session

from s3_utils import object_exists
from utils import init_env_from_file
from llm_utils import invoke_llm

_TEST_BUCKET_NAME = "data2report"


@pytest.fixture(autouse=True, scope="module")
def set_aws_api_key():
    init_env_from_file()


@pytest.mark.parametrize(
    "model_id",
    [
        "anthropic.claude-3-haiku-20240307-v1:0",
        "anthropic.claude-3-5-sonnet-20240620-v1:0",
        "ai21.jamba-1-5-mini-v1:0",
        "amazon.titan-text-lite-v1",
        "amazon.nova-lite-v1:0",
        "amazon.nova-micro-v1:0",
    ],
)
def test_connect_to_bedrock(model_id: str):
    session = Session()
    question = "What is the capital of Japan?"
    response = invoke_llm(
        "you are a helpful assistant who answer questions",
        question,
        model_id=model_id,
        max_tokens=100,
        temperature=0.0,
        session=session,
    )
    assert response["usage"]["input_tokens"] >= 5
    assert response["usage"]["output_tokens"] >= 1
    assert "Tokyo" in response["content"], response


def test_object_exists():
    session = Session()
    assert not object_exists(_TEST_BUCKET_NAME, "key-which-does-not-exist", session)

    assert not object_exists(
        "bucket-which-does-not-exist", "key-which-does-not-exist", session
    )
