"""Neo4j 知识图谱：文档 / 段落 / 实体 / 关系。"""
from __future__ import annotations

from typing import Any

from neo4j import GraphDatabase
from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

ALLOWED_RELATIONS = {
    "LOCATED_IN", "OFFERS", "REQUIRES", "CHARGES", "PROVIDES",
    "PART_OF", "APPLIES_TO", "ELIGIBLE_FOR", "RELATED_TO",
}


class KnowledgeGraph:
    def __init__(self):
        self.driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    def close(self):
        self.driver.close()

    def init_schema(self):
        stmts = [
            "CREATE CONSTRAINT doc_id IF NOT EXISTS FOR (d:Document) REQUIRE d.doc_id IS UNIQUE",
            "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE",
            "CREATE CONSTRAINT entity_key IF NOT EXISTS FOR (e:Entity) REQUIRE e.key IS UNIQUE",
        ]
        with self.driver.session() as s:
            for stmt in stmts:
                s.run(stmt)

    def reset(self):
        with self.driver.session() as s:
            s.run("MATCH (n) WHERE n:Document OR n:Chunk OR n:Entity DETACH DELETE n")

    def add_document(self, doc: dict[str, Any]):
        with self.driver.session() as s:
            s.run(
                """
                MERGE (d:Document {doc_id: $doc_id})
                SET d.title = $title, d.source = $source, d.doc_type = $doc_type
                """,
                doc_id=doc["doc_id"], title=doc["title"],
                source=doc["source"], doc_type=doc.get("doc_type", ""),
            )

    def add_chunks(self, doc_id: str, chunks: list[dict[str, Any]]):
        rows = [{
            "chunk_id": c["chunk_id"],
            "index": c["chunk_index"],
            "section": c.get("section", ""),
            "preview": c["text"][:300],
        } for c in chunks]
        with self.driver.session() as s:
            s.run(
                """
                MATCH (d:Document {doc_id: $doc_id})
                UNWIND $rows AS row
                MERGE (c:Chunk {chunk_id: row.chunk_id})
                SET c.doc_id = $doc_id, c.index = row.index,
                    c.section = row.section, c.preview = row.preview
                MERGE (d)-[:HAS_CHUNK]->(c)
                """,
                doc_id=doc_id, rows=rows,
            )

    def add_extractions(self, chunk_id: str, data: dict[str, list[dict[str, str]]]):
        entities = data.get("entities", [])
        if not entities:
            return
        rows = [{
            "key": f"{e['name']}::{e['type']}",
            "name": e["name"],
            "type": e["type"],
        } for e in entities]
        with self.driver.session() as s:
            s.run(
                """
                MATCH (c:Chunk {chunk_id: $chunk_id})
                UNWIND $rows AS row
                MERGE (e:Entity {key: row.key})
                SET e.name = row.name, e.type = row.type
                MERGE (c)-[:MENTIONS]->(e)
                """,
                chunk_id=chunk_id, rows=rows,
            )
            name_to_key = {e["name"]: f"{e['name']}::{e['type']}" for e in entities}
            for r in data.get("relations", []):
                rel = r.get("relation", "")
                if rel not in ALLOWED_RELATIONS:
                    continue
                hk = name_to_key.get(r.get("head"))
                tk = name_to_key.get(r.get("tail"))
                if not hk or not tk:
                    continue
                s.run(
                    f"""
                    MATCH (a:Entity {{key: $hk}}), (b:Entity {{key: $tk}})
                    MERGE (a)-[:{rel}]->(b)
                    """,
                    hk=hk, tk=tk,
                )

    def triples_for_chunks(self, chunk_ids: list[str], limit: int = 30) -> list[dict[str, str]]:
        if not chunk_ids:
            return []
        with self.driver.session() as s:
            res = s.run(
                """
                MATCH (c:Chunk)-[:MENTIONS]->(e:Entity)
                WHERE c.chunk_id IN $ids
                WITH DISTINCT e LIMIT 20
                MATCH (e)-[r]-(e2:Entity)
                RETURN DISTINCT e.name AS head, e.type AS head_type,
                       type(r) AS relation, e2.name AS tail, e2.type AS tail_type
                LIMIT $limit
                """,
                ids=chunk_ids, limit=limit,
            )
            return [dict(x) for x in res]

    def subgraph(self, keyword: str, limit: int = 40) -> dict[str, Any]:
        with self.driver.session() as s:
            res = s.run(
                """
                MATCH (e:Entity)
                WHERE toLower(e.name) CONTAINS toLower($q)
                WITH e LIMIT 5
                MATCH (e)-[r]-(e2:Entity)
                RETURN DISTINCT e.name AS head, e.type AS head_type,
                       type(r) AS relation, e2.name AS tail, e2.type AS tail_type
                LIMIT $limit
                """,
                q=keyword, limit=limit,
            )
            return self._to_graph([dict(x) for x in res])

    def overview(self, limit: int = 60) -> dict[str, Any]:
        with self.driver.session() as s:
            res = s.run(
                """
                MATCH (e:Entity)-[r]->(e2:Entity)
                RETURN e.name AS head, e.type AS head_type,
                       type(r) AS relation, e2.name AS tail, e2.type AS tail_type
                LIMIT $limit
                """,
                limit=limit,
            )
            return self._to_graph([dict(x) for x in res])

    @staticmethod
    def _to_graph(triples: list[dict[str, Any]]) -> dict[str, Any]:
        nodes: dict[str, dict[str, str]] = {}
        links = []
        for t in triples:
            hk = f"{t['head']}::{t['head_type']}"
            tk = f"{t['tail']}::{t['tail_type']}"
            nodes[hk] = {"id": hk, "name": t["head"], "type": t["head_type"]}
            nodes[tk] = {"id": tk, "name": t["tail"], "type": t["tail_type"]}
            links.append({"source": hk, "target": tk, "relation": t["relation"]})
        return {"nodes": list(nodes.values()), "links": links}

    def stats(self) -> dict[str, int]:
        with self.driver.session() as s:
            node_count = s.run("MATCH (n) WHERE n:Document OR n:Chunk OR n:Entity RETURN count(n) AS c").single()["c"]
            rel_count = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            ents = s.run("MATCH (e:Entity) RETURN count(e) AS c").single()["c"]
            return {"nodes": node_count, "relations": rel_count, "entities": ents}
