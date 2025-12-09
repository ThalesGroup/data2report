import json
import logging
import os

import requests
from boto3.session import Session
from botocore.config import Config


def invoke_llm(
    system_prompt: str,
    user_prompt: str,
    model_id: str,
    max_tokens: int,
    temperature: float,
    session: Session = None,
) -> dict:
    logging.info(f"Going to invoke LLM. Model ID: {model_id}")
    prompt = _format_model_body(
        system_prompt, user_prompt, model_id, max_tokens, temperature
    )
    if "gemini" in model_id:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set in environment")
        response_json = _invoke_gemini_model(prompt, model_id, api_key)
    else:
        if session is None:
            session = Session()
        response_json = _invoke_bedrock_model(prompt, model_id, session)
    response_text = _get_response_content(response_json, model_id)
    usage = _get_response_usage(response_json, model_id)
    logging.info(f"LLM usage: {usage}. Response length: {len(response_text)}")
    return {"content": response_text, "usage": usage}


def _invoke_gemini_model(prompt_body: dict, model_id: str, api_key: str) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    response = requests.post(url, headers=headers, data=json.dumps(prompt_body))
    response.raise_for_status()
    return response.json()


def _invoke_bedrock_model(prompt_body: dict, model_id: str, session: Session) -> dict:
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    if model_id.startswith("inference-profile/"):
        sts_client = session.client("sts")
        account_id = sts_client.get_caller_identity()["Account"]
        model_id = f"arn:aws:bedrock:{region}:{account_id}:{model_id}"
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


def _format_model_body(
    system_prompt: str,
    user_prompt: str,
    model_id: str,
    max_tokens: int,
    temperature: float,
) -> dict:
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
            "max_tokens": max_tokens,
            "temperature": temperature,
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
        body = {
            "inputText": f"{system_prompt}\n\n{user_prompt}",
            "textGenerationConfig": {
                "maxTokenCount": max_tokens,
                "temperature": temperature,
            },
        }
    elif "nova" in model_id:
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": user_prompt}],
                },
                {
                    "role": "assistant",
                    "content": [{"text": system_prompt}],
                },
            ],
            "inferenceConfig": {
                "maxTokens": max_tokens,
                "temperature": temperature,
            },
        }
    elif "gemini" in model_id:
        return {
            "contents": [
                {"role": "user", "parts": [{"text": f"{system_prompt}\n{user_prompt}"}]}
            ],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
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
    elif "nova" in model_id:
        return response_json["output"]["message"]["content"][0]["text"]
    elif "gemini" in model_id:
        return response_json["candidates"][0]["content"]["parts"][0]["text"]
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
    elif "nova" in model_id:
        return {
            "input_tokens": response_json["usage"]["inputTokens"],
            "output_tokens": response_json["usage"]["outputTokens"],
        }
    elif "gemini" in model_id:
        usage = response_json.get("usageMetadata", {})
        return {
            "input_tokens": usage.get("promptTokenCount", 0),
            "output_tokens": usage.get("candidatesTokenCount", 0),
        }
    else:
        raise ValueError(f"Unknown model_id: {model_id}")
