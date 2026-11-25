"""OpenAI 兼容的大模型客户端（用于图谱抽取和问答）。"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from openai import OpenAI
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

_client: OpenAI | None = None


def available() -> bool:
    return bool(LLM_API_KEY)


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=LLM_API_KEY or "EMPTY", base_url=LLM_BASE_URL, timeout=90)
    return _client


def chat(messages: list[dict[str, str]], temperature: float = 0.1, max_tokens: int = 1200) -> str:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            resp = get_client().chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:  # 网络抖动 / 限流，退避重试
            last_error = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"LLM 调用失败: {last_error}")


def chat_json(messages: list[dict[str, str]], max_tokens: int = 1200) -> dict[str, Any]:
    """要求模型输出 JSON，并容忍 ```json 包裹或前后多余文字。"""
    text = chat(messages, temperature=0.0, max_tokens=max_tokens)
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
