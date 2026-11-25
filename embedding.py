"""
OpenAI 兼容接口调用 text-embedding-v3 生成向量。
不依赖本地模型，由你在 .env 提供 KEY。
"""
from typing import List

import time
from openai import OpenAI
from config import (
    EMBEDDING_API_KEY,
    EMBEDDING_BASE_URL,
    EMBEDDING_MODEL,
    EMBEDDING_DIM,
    EMBEDDING_BATCH_SIZE,
)

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if not EMBEDDING_API_KEY:
        raise RuntimeError("EMBEDDING_API_KEY 未配置，请在 .env 中填写")
    if _client is None:
        _client = OpenAI(api_key=EMBEDDING_API_KEY, base_url=EMBEDDING_BASE_URL, timeout=60)
    return _client


def embed_texts(texts: List[str]) -> List[List[float]]:
    """批量向量化，保持输入顺序。"""
    client = get_client()
    results: List[List[float]] = []
    for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[i:i + EMBEDDING_BATCH_SIZE]
        # 空字符串会被接口拒绝，统一替换成空格
        batch = [t.replace("\n", " ").strip() or " " for t in batch]
        for attempt in range(3):
            try:
                resp = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(1.5 * (attempt + 1))
        results.extend([x.embedding for x in resp.data])
    return results


def embed_text(text: str) -> List[float]:
    return embed_texts([text])[0]


if __name__ == "__main__":
    print(f"Testing embedding model: {EMBEDDING_MODEL}")
    out = embed_texts(["德国留学公立大学学费政策", "新加坡本硕申请时间线"])
    print(f"Returned {len(out)} embeddings, dim {len(out[0])} (expected {EMBEDDING_DIM})")
