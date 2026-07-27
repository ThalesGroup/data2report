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

import json
import logging
import os

import requests
from boto3.session import Session
from botocore.config import Config

_MAX_TOOL_ITERATIONS = 6


def invoke_llm(
    system_prompt: str,
    user_prompt: str,
    model_id: str,
    max_tokens: int,
    temperature: float,
    session: Session = None,
    tools: list = None,
    chunk_path: str = None,
) -> dict:
    logging.info(f"Going to invoke LLM. Model ID: {model_id}")

    initialized_tools = _setup_tools(tools, chunk_path)

    if initialized_tools and "claude" in model_id:
        return _invoke_with_tool_loop(
            system_prompt, user_prompt, model_id, max_tokens, temperature,
            initialized_tools, session,
        )

    prompt = _format_model_body(
        system_prompt, user_prompt, model_id, max_tokens, temperature
    )
    if "gemini" in model_id:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set in environment")
        response_json = _invoke_gemini_model(prompt, model_id, api_key)
    else:
        response_json = _invoke_bedrock_model(prompt, model_id, _get_session(session))
    response_text = _get_response_content(response_json, model_id)
    usage = _get_response_usage(response_json, model_id)
    logging.info(f"LLM usage: {usage}. Response length: {len(response_text)}")
    return {"content": response_text, "usage": usage}


def _setup_tools(tool_names: list, chunk_path: str) -> list:
    """Instantiate and setup tool objects from a list of names."""
    if not tool_names:
        return []
    from tools.registry import get_tool
    initialized = []
    for name in tool_names:
        tool = get_tool(name)
        if chunk_path:
            tool.setup(chunk_path)
        initialized.append(tool)
    return initialized


def _invoke_with_tool_loop(
    system_prompt: str,
    user_prompt: str,
    model_id: str,
    max_tokens: int,
    temperature: float,
    tools: list,
    session: Session,
) -> dict:
    """Agentic loop for Bedrock Claude with tool use and prompt caching."""
    bedrock = _get_bedrock_client(model_id, _get_session(session))
    tool_schemas = [t.schema() for t in tools]
    tool_map = {t.name: t for t in tools}

    # Build initial request — mark prefix cacheable after chunk data
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": user_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }
    ]

    total_usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    tool_call_counts = {}  # { tool_name: count }
    final_text = ""

    for iteration in range(_MAX_TOOL_ITERATIONS):
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "system": [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": messages,
            "tools": tool_schemas,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        response = bedrock.invoke_model(
            body=json.dumps(body),
            modelId=_resolve_model_id(model_id, _get_session(session)),
        )
        response_json = json.loads(response.get("body").read())

        # Accumulate usage
        usage = response_json.get("usage", {})
        total_usage["input_tokens"] += usage.get("input_tokens", 0)
        total_usage["output_tokens"] += usage.get("output_tokens", 0)
        total_usage["cache_creation_input_tokens"] += usage.get(
            "cache_creation_input_tokens", 0
        )
        total_usage["cache_read_input_tokens"] += usage.get(
            "cache_read_input_tokens", 0
        )

        stop_reason = response_json.get("stop_reason")
        content_blocks = response_json.get("content", [])

        # Collect any text in this turn
        for block in content_blocks:
            if block.get("type") == "text":
                final_text += block["text"]

        if stop_reason != "tool_use":
            break

        # Execute tool calls and build tool_result turn
        tool_results = []
        for block in content_blocks:
            if block.get("type") != "tool_use":
                continue
            tool_name = block["name"]
            tool_input = block.get("input", {})
            tool_use_id = block["id"]

            logging.info(f"Tool call [{iteration + 1}]: {tool_name}({tool_input})")
            tool_call_counts[tool_name] = tool_call_counts.get(tool_name, 0) + 1

            tool = tool_map.get(tool_name)
            if tool is None:
                result_content = json.dumps({"error": f"Unknown tool: {tool_name}"})
            else:
                try:
                    result = tool.run(tool_input)
                    result_content = json.dumps(result)
                except Exception as e:
                    logging.warning(f"Tool '{tool_name}' raised: {e}")
                    result_content = json.dumps({"error": str(e)})

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result_content,
                }
            )

        # Append assistant turn + tool results to message history
        messages.append({"role": "assistant", "content": content_blocks})
        messages.append({"role": "user", "content": tool_results})
    else:
        logging.warning(
            f"Tool loop hit max iterations ({_MAX_TOOL_ITERATIONS}) without end_turn"
        )

    _log_cache_metrics(total_usage)
    logging.info(f"LLM tool-loop usage: {total_usage}. Tool calls: {tool_call_counts}. Response length: {len(final_text)}")
    return {
        "content": final_text,
        "usage": {
            "input_tokens": total_usage["input_tokens"],
            "output_tokens": total_usage["output_tokens"],
        },
        "tool_calls": tool_call_counts,
    }


def _log_cache_metrics(usage: dict) -> None:
    creation = usage.get("cache_creation_input_tokens", 0)
    read = usage.get("cache_read_input_tokens", 0)
    miss = usage.get("input_tokens", 0)
    logging.info(f"Prompt cache: {creation} written / {read} read / {miss} uncached")


def _get_session(session: Session) -> Session:
    return session if session is not None else Session()


def _get_bedrock_client(model_id: str, session: Session):
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    return session.client(
        service_name="bedrock-runtime",
        region_name=region,
        config=Config(read_timeout=300),
    )


def _resolve_model_id(model_id: str, session: Session) -> str:
    if model_id.startswith("inference-profile/"):
        region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        account_id = session.client("sts").get_caller_identity()["Account"]
        return f"arn:aws:bedrock:{region}:{account_id}:{model_id}"
    return model_id


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
