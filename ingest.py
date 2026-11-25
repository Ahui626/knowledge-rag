"""
入库流水线：
  python ingest.py            # 全量重建（解析 -> 分块 -> 向量化 -> Milvus -> Neo4j）
  python ingest.py --parse    # 强制重新跑 MinerU
  python ingest.py --skip-kg  # 只建向量库
  python ingest.py --no-llm   # 图谱用规则抽取，不调用大模型
"""
from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
import embedding
import extractor
import llm
from chunker import chunk_documents
from kg import KnowledgeGraph
from milvus_store import MilvusStore
from parser import parse_all


def embed_all(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    group = 50
    for i in range(0, len(texts), group):
        part = texts[i:i + group]
        out.extend(embedding.embed_texts(part))
        print(f"  [向量化] {min(i + group, len(texts))}/{len(texts)}")
    return out


def build_vector_store(chunks, vectors, rebuild: bool):
    store = MilvusStore(create=True)
    if rebuild:
        print("[Milvus] 删除旧 collection")
        store.drop()
        store = MilvusStore(create=True)
    print(f"[Milvus] 插入 {len(chunks)} 个 chunk")
    store.add_chunks(chunks, vectors)
    store.flush()
    print(f"[Milvus] 当前记录数: {store.count()}")
    return store


def build_graph(docs, chunks, use_llm: bool, rebuild: bool):
    kg = KnowledgeGraph()
    kg.init_schema()
    if rebuild:
        print("[Neo4j] 清空旧图谱")
        kg.reset()

    for doc in docs:
        kg.add_document(doc)
        kg.add_chunks(doc["doc_id"], [c for c in chunks if c["doc_id"] == doc["doc_id"]])
    print(f"[Neo4j] 已写入 {len(docs)} 篇文档、{len(chunks)} 个段落")

    targets = [c for c in chunks if c["doc_type"] != "标准规范"]
    print(f"[Neo4j] 开始抽取实体关系（{len(targets)} 段，{'LLM' if use_llm else '规则'}模式）")

    def work(c):
        try:
            return c, extractor.extract(c["text"], use_llm=use_llm)
        except Exception as e:
            print(f"  [抽取] 失败，改用规则: {c['chunk_id']} ({e})")
            return c, extractor.extract(c["text"], use_llm=False)

    done = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(work, c) for c in targets]
        for fut in as_completed(futures):
            chunk, data = fut.result()
            kg.add_extractions(chunk["chunk_id"], data)
            done += 1
            if done % 10 == 0 or done == len(targets):
                print(f"  [抽取] {done}/{len(targets)}")

    print(f"[Neo4j] 图谱统计: {kg.stats()}")
    kg.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parse", action="store_true", help="强制重新解析文档")
    ap.add_argument("--skip-kg", action="store_true", help="跳过知识图谱")
    ap.add_argument("--no-llm", action="store_true", help="图谱只用规则抽取")
    args = ap.parse_args()

    if not config.EMBEDDING_API_KEY:
        raise SystemExit("请先在 .env 中填写 EMBEDDING_API_KEY（text-embedding-v3）")

    t0 = time.time()
    docs = parse_all(force=args.parse)
    chunks = chunk_documents(docs)
    print(f"[分块] {len(docs)} 篇文档 -> {len(chunks)} 个 chunk")
    for d in docs:
        n = len([c for c in chunks if c["doc_id"] == d["doc_id"]])
        print(f"  - {d['title'][:40]} ({d['doc_type']}): {n} 块")

    vectors = embed_all([c["text"] for c in chunks])
    build_vector_store(chunks, vectors, rebuild=True)

    if not args.skip_kg:
        use_llm = llm.available() and not args.no_llm
        build_graph(docs, chunks, use_llm=use_llm, rebuild=True)

    print(f"[完成] 耗时 {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
