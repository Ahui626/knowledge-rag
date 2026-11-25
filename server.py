"""FastAPI 服务：混合检索 / RAG 问答 / 知识图谱。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import embedding
import llm
from kg import KnowledgeGraph
from milvus_store import MilvusStore
from rag import answer as rag_answer

BASE_DIR = Path(__file__).parent
store: MilvusStore | None = None
kg: KnowledgeGraph | None = None
startup_errors: list[str] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    global store, kg
    startup_errors.clear()
    try:
        store = MilvusStore(create=False)
    except Exception as e:  # 数据库没启动时不让服务挂掉
        startup_errors.append(f"Milvus: {e}")
    try:
        kg = KnowledgeGraph()
        kg.driver.verify_connectivity()
    except Exception as e:
        startup_errors.append(f"Neo4j: {e}")
    yield
    if kg:
        kg.close()


app = FastAPI(title="留学政策知识库 · 混合检索 + 知识图谱", lifespan=lifespan)


class QueryReq(BaseModel):
    query: str
    top_k: int | None = None


def _require():
    if store is None:
        raise HTTPException(503, "Milvus 未就绪，请先启动容器并执行 ingest.py")
    if not config.EMBEDDING_API_KEY:
        raise HTTPException(503, "未配置 EMBEDDING_API_KEY")


def _retrieve(query: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    vector = embedding.embed_text(query)
    hybrid = store.hybrid_search(query, vector)
    dense = store.dense_search(vector, limit=5)
    sparse = store.sparse_search(query, limit=5)
    triples = kg.triples_for_chunks([r["chunk_id"] for r in hybrid]) if kg else []
    return hybrid, dense, sparse, triples


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/health")
def health():
    return {
        "ok": store is not None,
        "milvus": store.count() if store else None,
        "neo4j": kg.stats() if kg else None,
        "llm": llm.available(),
        "embedding": bool(config.EMBEDDING_API_KEY),
        "errors": startup_errors,
    }


@app.get("/api/stats")
def stats():
    return {
        "chunks": store.count() if store else 0,
        "graph": kg.stats() if kg else {"nodes": 0, "relations": 0, "entities": 0},
        "model": config.EMBEDDING_MODEL,
        "llm_model": config.LLM_MODEL if llm.available() else None,
    }


@app.post("/api/search")
def search(req: QueryReq):
    query = req.query.strip()
    if not query:
        raise HTTPException(400, "query 不能为空")
    _require()
    hybrid, dense, sparse, triples = _retrieve(query)
    if req.top_k:
        hybrid = hybrid[: req.top_k]
    dense_ids = {r["chunk_id"] for r in dense}
    sparse_ids = {r["chunk_id"] for r in sparse}
    for r in hybrid:
        r["hit_dense"] = r["chunk_id"] in dense_ids
        r["hit_sparse"] = r["chunk_id"] in sparse_ids
    return {
        "query": query,
        "results": hybrid,
        "channels": {
            "dense": [{"chunk_id": r["chunk_id"], "score": r["score"], "title": r["doc_title"]} for r in dense],
            "sparse": [{"chunk_id": r["chunk_id"], "score": r["score"], "title": r["doc_title"]} for r in sparse],
        },
        "triples": triples,
    }


@app.post("/api/chat")
def chat(req: QueryReq):
    query = req.query.strip()
    if not query:
        raise HTTPException(400, "query 不能为空")
    _require()
    hybrid, dense, sparse, triples = _retrieve(query)
    text = rag_answer(query, hybrid, triples)
    citations = [
        {
            "n": i,
            "doc_title": r["doc_title"],
            "chunk_id": r["chunk_id"],
            "text": r["text"],
            "score": round(float(r["score"]), 6),
        }
        for i, r in enumerate(hybrid, 1)
    ]
    return {
        "query": query,
        "answer": text,
        "citations": citations,
        "triples": triples,
        "llm_enabled": llm.available(),
    }


@app.get("/api/graph/overview")
def graph_overview():
    if kg is None:
        raise HTTPException(503, "Neo4j 未就绪")
    return kg.overview()


@app.get("/api/graph/search")
def graph_search(q: str):
    if kg is None:
        raise HTTPException(503, "Neo4j 未就绪")
    return kg.subgraph(q.strip())


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
