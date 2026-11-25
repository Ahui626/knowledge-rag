import os
from dotenv import load_dotenv

load_dotenv()

# Embedding (text-embedding-v3 via OpenAI-compatible API)
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "").strip()
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").strip()
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v3").strip()
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "10"))

# LLM for extraction and QA (OpenAI-compatible)
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-plus").strip()

# Databases
MILVUS_URI = os.getenv("MILVUS_URI", "http://localhost:19530").strip()
MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "kb_chunks").strip()
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687").strip()
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j").strip()
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4j12345").strip()

# Retrieval
DENSE_TOP_K = int(os.getenv("DENSE_TOP_K", "10"))
SPARSE_TOP_K = int(os.getenv("SPARSE_TOP_K", "10"))
FUSION_TOP_K = int(os.getenv("FUSION_TOP_K", "6"))
RRF_K = int(os.getenv("RRF_K", "60"))
