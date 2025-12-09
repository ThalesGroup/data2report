import os

import pytest

from llm_utils import invoke_llm


def _get_examples_folder():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples")


@pytest.fixture(autouse=True)
def set_logging():
    pass


@pytest.fixture()
def set_gemini_api_key():
    env_path = os.path.join(os.path.dirname(__file__), "../config/google.env.list")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.strip().startswith("GEMINI_API_KEY="):
                    key = line.strip().split("=", 1)[1]
                    os.environ["GEMINI_API_KEY"] = key


@pytest.mark.parametrize("model_id", ["gemini-2.5-flash-lite", "gemini-2.5-flash"])
def test_connect_to_gemini(model_id: str, set_gemini_api_key):
    question = "What is the capital of Japan?"
    answer = invoke_llm(
        "you are a helpful assistant who answer questions",
        question,
        model_id=model_id,
        temperature=0.5,
        max_tokens=100,
    )
    assert "Tokyo" in answer["content"]
