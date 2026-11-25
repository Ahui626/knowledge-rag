# knowledge-rag

本地 RAG 知识库：**Milvus 混合检索 + Neo4j 知识图谱 + MinerU 文档解析**，并附带 MinIO、MCP 的教学 Demo。

## 技术栈

- **文档解析**：MinerU 2.6.5（PDF）/ python-docx（DOCX）
- **向量化**：阿里云 `text-embedding-v3`（1024 维）
- **向量库**：Milvus 2.6（稠密向量 + 内置 BM25 稀疏向量，RRF 融合排序）
- **知识图谱**：Neo4j 5.26（文档 → 段落 → 实体 → 关系）
- **问答**：DeepSeek（OpenAI 兼容接口）
- **服务**：FastAPI + 单页网页（检索 / 问答 / 图谱浏览）

## 快速开始

```powershell
# 1. 配置密钥：复制模板并填入 key
copy .env.example .env          # EMBEDDING_API_KEY 必填，LLM_API_KEY 选填

# 2. 启动依赖（Milvus / etcd / MinIO / Neo4j）
docker compose up -d

# 3. 建库（解析 → 分块 → 向量化 → 写 Milvus → 写 Neo4j）
.venv\Scripts\python.exe ingest.py

# 4. 启动网页
.venv\Scripts\uvicorn.exe server:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000

> Python 环境：`uv venv --python 3.12 .venv && uv pip install -r requirements.txt`；PDF 解析另需 MinerU（见 [技术链路说明](docs/技术链路说明.md)）。

## 目录结构

```
doc/               原始资料（docx / pdf）
docs/              教学文档与架构图
mcp_demo/          MCP 协议 Demo（stdio / HTTP / OAuth / GitHub 工具）
static/            网页前端
parser.py          MinerU / python-docx 解析
chunker.py         标题优先分块
embedding.py       text-embedding-v3 向量化
milvus_store.py    Milvus 建表与混合检索
extractor.py       实体关系抽取
kg.py              Neo4j 读写
ingest.py          一键入库
server.py          FastAPI 服务
minio_demo.py      MinIO 对象存储演示
compare_pdf.py     普通 Python vs MinerU 解析对比
preview_pdf.py     只看 PDF 解析效果（不写库）
```

## 文档

- [技术链路说明](docs/技术链路说明.md) —— 解析、分块、embedding、混合检索、图谱
- [面试问答](docs/面试问答.md) —— 项目讲解与高频问题
- [PDF 解析对比](docs/pdf解析对比.md) —— 普通 Python vs MinerU
- [MinIO 使用教学](docs/MinIO使用教学.md) —— 对象存储常用操作
- [MCP 教学 Demo](mcp_demo/README.md) —— stdio / HTTP / OAuth / 外部工具

## License

MIT
