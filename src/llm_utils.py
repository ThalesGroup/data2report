import json
import logging
import os

from boto3.session import Session
from botocore.config import Config


def invoke_llm(
    system_prompt: str, user_prompt: str, model_id: str, session: Session
) -> dict:
    logging.info(f"Going to invoke LLM. Model ID: {model_id}")
    prompt = _format_model_body(system_prompt, user_prompt, model_id)
    response_json = _invoke_bedrock_model(prompt, model_id, session)
    response_text = _get_response_content(response_json, model_id)
    usage = _get_response_usage(response_json, model_id)
    logging.info(f"Got response from LLM. Response length: {len(response_text)}")
    return {"content": response_text, "usage": usage}


def _invoke_bedrock_model(prompt_body: dict, model_id: str, session: Session) -> dict:
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    bedrock_client = session.client(
        service_name="bedrock-runtime",
        region_name=region,
        config=Config(read_timeout=300),
    )
    response = bedrock_client.invoke_model(
        body=json.dumps(prompt_body),
        modelId=model_id,
    )
    return json.loads(response.get("body").read())


def _format_model_body(system_prompt: str, user_prompt: str, model_id: str) -> dict:
    if "claude" in model_id:
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": user_prompt,
                }
            ],
            "max_tokens": 2000,
            "temperature": 0.0,
        }
    elif "jamba" in model_id:
        body = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "n": 1,
        }
    elif "titan" in model_id:
        body = {"inputText": f"{system_prompt}\n\n{user_prompt}"}
    else:
        raise ValueError(f"Unknown model_id: {model_id}")
    return body


def _get_response_content(response_json: dict, model_id: str) -> str:
    if "claude" in model_id:
        return response_json["content"][0]["text"]
    elif "jamba" in model_id:
        return response_json["choices"][0]["message"]["content"]
    elif "titan" in model_id:
        return response_json["results"][0]["outputText"]
    else:
        raise ValueError(f"Unknown model_id: {model_id}")


def _get_response_usage(response_json: dict, model_id: str) -> dict:
    if "claude" in model_id:
        return {
            "input_tokens": response_json["usage"]["input_tokens"],
            "output_tokens": response_json["usage"]["output_tokens"],
        }
    elif "jamba" in model_id:
        return {
            "input_tokens": response_json["usage"]["prompt_tokens"],
            "output_tokens": response_json["usage"]["completion_tokens"],
        }
    elif "titan" in model_id:
        return {
            "input_tokens": response_json["inputTextTokenCount"],
            "output_tokens": response_json["results"][0]["tokenCount"],
        }
    else:
        raise ValueError(f"Unknown model_id: {model_id}")
