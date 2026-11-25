# MinIO 使用教学

本文教你理解并使用 **MinIO（对象存储）**，直接复用本项目已有的 MinIO 服务和 `doc/` 下的 RAG 文件作演示数据。

演示脚本：`minio_demo.py`（一个命令跑完整生命周期）。

---

## 一、MinIO 是什么，为什么本项目里已经有它

MinIO 是一个**对象存储**（Object Storage），实现了亚马逊 **S3 协议**。你可以把它理解成：

> 一个「用 HTTP 存大文件」的服务——不是传统的文件夹层级，而是把文件（object）放进桶（bucket），用唯一名字（key）存取。

**它在本项目里早就存在**：Milvus 2.6 standalone 依赖 etcd + MinIO，MinIO 负责存 Milvus 的数据（段文件、日志等）。所以你在 `docker-compose.yml` 里看到的 `minio` 服务，本来是给 Milvus 用的，现在我们直接拿它来学习对象存储。

用它的理由：

| 对比 | 本地文件系统 | 传统数据库 | **MinIO 对象存储** |
|---|---|---|---|
| 访问方式 | 路径 | SQL | **HTTP + S3 API** |
| 大文件/二进制 | 行 | 不擅长 | **擅长（视频/PDF/图片）** |
| 跨机器共享 | 难 | 难 | **天生网络化** |
| 扩容 | 加盘 | 分库分表 | **横向加节点** |

---

## 二、三个核心概念

1. **Bucket（桶）**：顶层容器，类似"根目录"，全局唯一命名。本项目里已经有 `milvus`（Milvus 用）和 `rag-demo`（我们的演示桶）。
2. **Object（对象）**：桶里的一个文件，用 `object_name`（key）唯一标识。
3. **Prefix（前缀）**：object 名里的 `rag-docs/`，只是名字里带斜杠，**MinIO 没有真正的"目录"**，`list_objects(prefix="rag-docs/")` 靠前缀过滤来"模拟目录"。

一句话：`bucket + object_name` = 文件的实际地址，例如
`rag-demo / rag-docs / GBT+20801.1-2020.pdf`。

---

## 三、本项目的 MinIO 配置

来自 [docker-compose.yml](../docker-compose.yml) 的 `minio` 服务：

| 项 | 值 |
|---|---|
| S3 API 端点 | `http://localhost:9000`（程序连它） |
| 网页控制台 | `http://localhost:9001`（人看它） |
| 账号 | `minioadmin` |
| 密码 | `minioadmin` |
| 数据卷 | `minio_data` |

**启动只启动 MinIO（不拉 Milvus 那些）：**

```powershell
docker compose up -d minio
```

**打开网页控制台**：浏览器访问 http://localhost:9001 ，用 `minioadmin / minioadmin` 登录，就能看到 `rag-demo` 桶及其中的对象（演示脚本已把数据放进去）。

---

## 四、Python SDK 常见操作

先装 SDK（已完成，minio 7.x）：

```powershell
.venv\Scripts\python.exe -m pip install minio   # 本项目用 uv：
uv pip install --python .venv\Scripts\python.exe minio
```

### 4.1 连接

```python
from minio import Minio

client = Minio(
    "localhost:9000",
    access_key="minioadmin",
    secret_key="minioadmin",
    secure=False,          # 本地 http，不上 TLS
)
```

### 4.2 桶：查 / 建 / 删

```python
for b in client.list_buckets():          # 列出所有桶
    print(b.name, b.creation_date)

if not client.bucket_exists("rag-demo"): # 判断是否存在
    client.make_bucket("rag-demo")       # 新建

client.remove_bucket("rag-demo")         # 删除（桶必须为空）
```

### 4.3 上传

```python
# 从本地文件上传
client.fput_object("rag-demo", "rag-docs/a.pdf", "doc/a.pdf")

# 从内存字节上传
data = b"hello minio"
client.put_object("rag-demo", "rag-docs/hello.txt", io.BytesIO(data), len(data))
```

> 坑：`fput_object` 默认 `content_type` 是 `application/octet-stream`（本演示里也看到了）。想让浏览器/程序按类型识别，上传时显式传：
> `client.fput_object(..., content_type="application/pdf")`。

### 4.4 列出对象

```python
for obj in client.list_objects("rag-demo", prefix="rag-docs/", recursive=True):
    print(obj.object_name, obj.size, obj.last_modified)
```

### 4.5 读元数据（不下载内容）

```python
st = client.stat_object("rag-demo", "rag-docs/a.pdf")
print(st.size, st.etag, st.content_type, st.last_modified)
```

`etag` 是内容的哈希，可用来判断文件是否变化。

### 4.6 下载

```python
client.fget_object("rag-demo", "rag-docs/a.pdf", "data/out/a.pdf")  # 下载到本地文件

resp = client.get_object("rag-demo", "rag-docs/a.pdf")              # 读成字节流
bytes = resp.read(); resp.close(); resp.release_conn()
```

### 4.7 预签名 URL（临时下载链接）

这是对象存储最有用的能力之一：**生成一个带签名的 URL，有效期内任何人无需账号密码就能下载/上传**。

```python
from datetime import timedelta
url = client.presigned_get_object("rag-demo", "rag-docs/a.pdf",
                                  expires=timedelta(days=7))
# http://localhost:9000/rag-demo/rag-docs/a.pdf?X-Amz-Algorithm=...&X-Amz-Signature=...
```

- 适合：给前端/外部生成临时下载链接，不泄露长期凭据。
- 坑：本地单机 MinIO 默认 region 是 `us-east-1`，URL 里 `X-Amz-Credential` 会出现它，正常现象，不用改。

### 4.8 删除

```python
client.remove_object("rag-demo", "rag-docs/a.pdf")   # 删对象
client.remove_bucket("rag-demo")                      # 删桶（先清空）
```

---

## 五、一个完整演示（脚本做了什么）

`minio_demo.py` 把上面串成一条链路，每步有打印：

```
连接 → 列出桶 → 创建桶 rag-demo → 上传 doc/ 下 5 个文件
     → 列出对象 → stat 元数据 → 下载 → 生成预签名 URL → （可选）清理
```

直接跑（默认跑完会删除演示数据）：

```powershell
.venv\Scripts\python.exe minio_demo.py
```

**保留数据在控制台里看**（跳过第 8 步清理）：

```powershell
$env:MINIO_DEMO_KEEP="1"; .venv\Scripts\python.exe minio_demo.py
```

跑完打开 http://localhost:9001 就能看到 `rag-demo` 桶里的东西。

---

## 六、和本项目 RAG 的关系

```
doc/*.pdf, *.docx
   │  解析（MinerU / python-docx）
   ▼
文本块 ──embedding──> Milvus（向量存储）
                        │
                        └── 底层靠 MinIO 存数据段
```

- **MinIO 在这里是"底座"**：Milvus 内部用 S3 协议把它的向量段、日志存到 MinIO。
- **也可以把 MinIO 直接当"原始文件仓库"**：把 `doc/` 原始文件、`data/parsed/` 解析结果、渲染图等都上传上去，做对象存储的归档。

这正是对象存储的典型定位：**存字节（文件），不做查询**；要"按内容查询"交给 Milvus/数据库。

---

## 七、常用命令速查

```powershell
# 启动 / 停止
docker compose up -d minio
docker compose stop minio

# 运行演示（保留数据）
$env:MINIO_DEMO_KEEP="1"; .venv\Scripts\python.exe minio_demo.py

# 看日志
docker compose logs -f minio

# 控制台
start http://localhost:9001
```

---

## 八、常见坑

1. **`secure=False`**：本地没配 TLS，必须设 False；连远端 https 的 MinIO 要 `secure=True`。
2. **region 报错**：MinIO 单机默认 `us-east-1`，一般不用显式指定；遇到 region 相关报错先在 client 里补 `region="us-east-1"`。
3. **`content_type` 一直是 `application/octet-stream`**：上传时手动传 `content_type`。
4. **中文/特殊字符文件名**：SDK 会自动 URL 编码，`+`、`/` 会变形（本演示文件名里的 `+` 在 URL 里成了 `%2B`），属正常。
5. **删 bucket 前先清空**：非空桶 `remove_bucket` 会失败。
6. **凭证别硬编码进生产代码**：用环境变量（脚本里已从 `MINIO_ENDPOINT / MINIO_ROOT_USER / MINIO_ROOT_PASSWORD` 读）。

---

## 九、练习

1. 在控制台 http://localhost:9001 手动建一个 bucket、再上传一个文件，体会 GUI 和 SDK 是同一套 API。
2. 改 `minio_demo.py`，上传 `data/parsed/` 下的 MinerU 解析结果（markdown + json）到新桶 `rag-parsed`。
3. 给 `fput_object` 加 `content_type="application/pdf"`，再看 stat 的变化。
4. 生成一个 60 秒的预签名 URL，过一会儿再访问，观察它失效。
5. 用 `client.put_object` 从内存字节上传一段字符串，理解"对象可以是任意字节，不一定是文件"。