"""
Milvus 向量库：稠密向量 + BM25 稀疏向量混合检索。
Milvus 2.6 内置 BM25 Function + 中文 analyzer，不需要额外的稀疏模型；
两路召回后用 RRF 融合排序。
"""
from typing import List, Dict, Any, Tuple
from pymilvus import (
    connections,
    utility,
    FieldSchema,
    CollectionSchema,
    DataType,
    Collection,
    Function,
    FunctionType,
    RRFRanker,
    AnnSearchRequest,
)
from config import (
    MILVUS_URI,
    MILVUS_COLLECTION,
    EMBEDDING_DIM,
    DENSE_TOP_K,
    SPARSE_TOP_K,
    FUSION_TOP_K,
    RRF_K,
)

PK_FIELD = "id"
TEXT_FIELD = "text"
DOC_ID_FIELD = "doc_id"
DOC_TITLE_FIELD = "doc_title"
CHUNK_ID_FIELD = "chunk_id"
CHUNK_INDEX_FIELD = "chunk_index"
DENSE_FIELD = "dense_vector"
SPARSE_FIELD = "sparse_vector"
OUTPUT_FIELDS = [TEXT_FIELD, DOC_ID_FIELD, DOC_TITLE_FIELD, CHUNK_ID_FIELD, CHUNK_INDEX_FIELD]


class MilvusStore:
    def __init__(self, create: bool = False):
        connections.connect(uri=MILVUS_URI)
        self.collection_name = MILVUS_COLLECTION
        self.dense_top_k = DENSE_TOP_K
        self.sparse_top_k = SPARSE_TOP_K
        self.fusion_top_k = FUSION_TOP_K
        self.rrf_k = RRF_K

        if utility.has_collection(self.collection_name):
            self.collection = Collection(self.collection_name)
            self.collection.load()
        elif create:
            self._create_collection()
        else:
            raise RuntimeError(
                f"Collection {self.collection_name} 不存在，请先执行 python ingest.py --rebuild"
            )

    def _create_collection(self) -> Collection:
        fields = [
            FieldSchema(name=PK_FIELD, dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(
                name=TEXT_FIELD,
                dtype=DataType.VARCHAR,
                max_length=8192,
                enable_analyzer=True,
                analyzer_params={"type": "chinese"},
            ),
            FieldSchema(name=DOC_ID_FIELD, dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name=DOC_TITLE_FIELD, dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name=CHUNK_ID_FIELD, dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name=CHUNK_INDEX_FIELD, dtype=DataType.INT64),
            FieldSchema(name=DENSE_FIELD, dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
            FieldSchema(name=SPARSE_FIELD, dtype=DataType.SPARSE_FLOAT_VECTOR),
        ]
        schema = CollectionSchema(fields, enable_dynamic_field=False)
        # 关键：把 text 字段自动分析成稀疏向量，供 BM25 检索
        schema.add_function(
            Function(
                name="text_bm25",
                function_type=FunctionType.BM25,
                input_field_names=[TEXT_FIELD],
                output_field_names=[SPARSE_FIELD],
            )
        )
        col = Collection(self.collection_name, schema, consistency_level="Strong")
        self.collection = col

        col.create_index(
            DENSE_FIELD,
            {"index_type": "AUTOINDEX", "metric_type": "COSINE", "params": {}},
        )
        col.create_index(
            SPARSE_FIELD,
            {"index_type": "SPARSE_INVERTED_INDEX", "metric_type": "BM25", "params": {}},
        )
        col.load()
        return col

    def add_chunks(self, chunks: List[Dict[str, Any]], dense_embeddings: List[List[float]]) -> List[int]:
        """插入 chunks。稀疏向量由 Milvus 的 BM25 Function 自动生成，无需传入。"""
        entities = []
        for c, emb in zip(chunks, dense_embeddings):
            entities.append({
                TEXT_FIELD: c[TEXT_FIELD],
                DOC_ID_FIELD: c["doc_id"],
                DOC_TITLE_FIELD: c["doc_title"],
                CHUNK_ID_FIELD: c["chunk_id"],
                CHUNK_INDEX_FIELD: c["chunk_index"],
                DENSE_FIELD: emb,
            })
        res = self.collection.insert(entities)
        return list(res.primary_keys)

    def flush(self):
        self.collection.flush()

    def _hit_to_dict(self, hit) -> Dict[str, Any]:
        return {
            "id": hit.id,
            "score": hit.distance,
            "text": hit.entity.get(TEXT_FIELD),
            "doc_id": hit.entity.get(DOC_ID_FIELD),
            "doc_title": hit.entity.get(DOC_TITLE_FIELD),
            "chunk_id": hit.entity.get(CHUNK_ID_FIELD),
            "chunk_index": hit.entity.get(CHUNK_INDEX_FIELD),
        }

    def dense_search(self, query_vector: List[float], limit: int | None = None) -> List[Dict[str, Any]]:
        res = self.collection.search(
            data=[query_vector],
            anns_field=DENSE_FIELD,
            param={"metric_type": "COSINE", "params": {}},
            limit=limit or self.dense_top_k,
            output_fields=OUTPUT_FIELDS,
        )
        return [self._hit_to_dict(h) for h in res[0]]

    def sparse_search(self, query_text: str, limit: int | None = None) -> List[Dict[str, Any]]:
        # 全文检索：查稀疏向量字段，data 仍传原始文本，服务端用同一 analyzer 转成 BM25 稀疏向量
        res = self.collection.search(
            data=[query_text],
            anns_field=SPARSE_FIELD,
            param={"metric_type": "BM25", "params": {}},
            limit=limit or self.sparse_top_k,
            output_fields=OUTPUT_FIELDS,
        )
        return [self._hit_to_dict(h) for h in res[0]]

    def hybrid_search(
        self,
        query_text: str,
        query_vector: List[float],
        expr: str | None = None,
    ) -> List[Dict[str, Any]]:
        """Dense + BM25 双路召回，RRF 融合后返回 top-k。"""
        reqs = [
            AnnSearchRequest(
                data=[query_vector],
                anns_field=DENSE_FIELD,
                param={"metric_type": "COSINE", "params": {}},
                limit=self.dense_top_k,
                expr=expr,
            ),
            AnnSearchRequest(
                data=[query_text],
                anns_field=SPARSE_FIELD,
                param={"metric_type": "BM25", "params": {}},
                limit=self.sparse_top_k,
                expr=expr,
            ),
        ]
        results = self.collection.hybrid_search(
            reqs=reqs,
            rerank=RRFRanker(k=self.rrf_k),
            limit=self.fusion_top_k,
            output_fields=OUTPUT_FIELDS,
        )
        return [self._hit_to_dict(h) for h in results[0]]

    def count(self) -> int:
        return self.collection.num_entities

    def drop(self):
        if utility.has_collection(self.collection_name):
            utility.drop_collection(self.collection_name)
