"""
文本分块：按标题层级切分，块内保留"文档 / 章节"上下文，块间轻微重叠。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CHUNK_SIZE = 650
OVERLAP = 80
CHUNKS_PATH = Path("data/chunks.jsonl")


def _split_long(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text]
    parts = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            for sep in ["。", "；", "！", "？", "\n"]:
                idx = window.rfind(sep)
                if idx > size // 2:
                    end = start + idx + 1
                    break
        parts.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [p for p in parts if p]


def chunk_documents(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for doc in docs:
        title = doc["title"]
        section = ""
        buf: list[str] = []

        def flush() -> None:
            nonlocal buf
            body = "\n".join(buf).strip()
            if not body:
                buf = []
                return
            header = f"《{title}》"
            if section:
                header += f" · {section}"
            for piece in _split_long(body, CHUNK_SIZE, OVERLAP):
                idx = len([c for c in chunks if c["doc_id"] == doc["doc_id"]])
                chunks.append({
                    "chunk_id": f"{doc['doc_id']}::{idx:03d}",
                    "chunk_index": idx,
                    "doc_id": doc["doc_id"],
                    "doc_title": title,
                    "doc_type": doc.get("doc_type", ""),
                    "section": section,
                    "text": f"{header}\n{piece}",
                })
            buf = []

        for block in doc["blocks"]:
            if block["type"] == "title":
                flush()
                section = block["text"]
                continue
            buf.append(block["text"])
            if sum(len(x) for x in buf) >= CHUNK_SIZE:
                flush()
        flush()

    CHUNKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CHUNKS_PATH.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    return chunks


def load_chunks() -> list[dict[str, Any]]:
    return [json.loads(line) for line in CHUNKS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
