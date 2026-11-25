"""RAG 问答：混合检索结果 + 图谱关系 -> 带引用的回答。"""
from __future__ import annotations

from typing import Any

import llm

SYSTEM = """你是一个严谨的资料问答助手。规则：
1. 只使用提供的【资料】和【知识图谱关系】回答，不要引入外部知识。
2. 每个关键结论后面用 [编号] 标注来源，编号对应资料编号。
3. 如果资料不足以回答，直接说明"资料中未找到"，不要猜测。
4. 回答用中文，条理清晰，先给结论再给依据。
5. 金额、分数、时间等数字必须与资料一致。"""


def build_context(results: list[dict[str, Any]], triples: list[dict[str, Any]]) -> str:
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] 《{r['doc_title']}》\n{r['text']}")
    ctx = "\n\n【资料】\n" + "\n\n".join(lines) if lines else "（无）"
    if triples:
        rels = "\n".join(
            f"- {t['head']}（{t['head_type']}） -[{t['relation']}]-> {t['tail']}（{t['tail_type']}）"
            for t in triples
        )
        ctx += "\n\n【知识图谱关系】\n" + rels
    return ctx


def answer(query: str, results: list[dict[str, Any]], triples: list[dict[str, Any]]) -> str | None:
    if not llm.available():
        return None
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"问题：{query}\n{build_context(results, triples)}"},
    ]
    return llm.chat(messages, temperature=0.1, max_tokens=1000)
