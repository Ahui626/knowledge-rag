"""
MinIO 对象存储教学 Demo（复用本项目的 MinIO 服务 + doc/ 下的 RAG 文件）。

不依赖 Milvus，纯演示 MinIO 的常用操作：
  - 连接 / 列出 / 创建 bucket
  - 上传文件、上传整个目录
  - 列出对象（含 prefix 模拟目录）
  - 读取对象元数据 stat
  - 下载对象
  - 生成预签名 URL（临时下载链接）
  - 删除对象 / 删除 bucket

运行：
  .venv\\Scripts\\python.exe minio_demo.py

先确保 MinIO 已启动：
  docker compose up -d minio

控制台（网页管理界面）：http://localhost:9001  （账号 minioadmin / minioadmin）
S3 API 端点：             http://localhost:9000
"""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from minio import Minio
from minio.error import S3Error

ROOT = Path(__file__).resolve().parent
LOCAL_DIR = ROOT / "doc"          # 用之前的 RAG 文件当演示数据
DOWNLOAD_DIR = ROOT / "data/minio_download"

# 和 docker-compose.yml 里的 minio 服务保持一致
ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
ACCESS_KEY = os.getenv("MINIO_ROOT_USER", "minioadmin")
SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD", "minioadmin")
DEMO_BUCKET = "rag-demo"
PREFIX = "rag-docs"               # object 名里的“目录”其实只是一个前缀


def connect() -> Minio:
    return Minio(
        ENDPOINT,
        access_key=ACCESS_KEY,
        secret_key=SECRET_KEY,
        secure=False,            # 本地 http，不开 TLS
    )


def ensure_bucket(client: Minio, bucket: str) -> None:
    if client.bucket_exists(bucket):
        print(f"  [已存在] bucket: {bucket}")
    else:
        client.make_bucket(bucket)
        print(f"  [新建] bucket: {bucket}")


def demo() -> None:
    client = connect()
    print(f"[连接成功] {ENDPOINT}\n")

    # 1. 列出已有 bucket（会看到 Milvus 用的那个 'milvus'）
    print("== 1. 列出所有 bucket ==")
    for b in client.list_buckets():
        print(f"  - {b.name}  (创建于 {b.creation_date:%Y-%m-%d %H:%M})")
    print()

    # 2. 创建我们的演示 bucket
    print("== 2. 创建/确认 bucket ==")
    ensure_bucket(client, DEMO_BUCKET)
    print()

    # 3. 上传 doc/ 下所有文件（用 prefix 模拟目录）
    print(f"== 3. 上传目录 {LOCAL_DIR} -> {DEMO_BUCKET}/{PREFIX}/ ==")
    for f in sorted(LOCAL_DIR.iterdir()):
        if not f.is_file():
            continue
        object_name = f"{PREFIX}/{f.name}"
        client.fput_object(DEMO_BUCKET, object_name, str(f))
        print(f"  [上传] {f.name}  ({f.stat().st_size} 字节) -> {object_name}")
    print()

    # 4. 列出对象
    print(f"== 4. 列出 {DEMO_BUCKET} 里的对象 ==")
    for obj in client.list_objects(DEMO_BUCKET, prefix=PREFIX, recursive=True):
        print(f"  - {obj.object_name:45s}  {obj.size:>8} 字节  {obj.last_modified:%Y-%m-%d}")
    print()

    # 5. 读元数据
    demo_obj = f"{PREFIX}/GBT+20801.1-2020.pdf"
    print(f"== 5. stat 元数据: {demo_obj} ==")
    st = client.stat_object(DEMO_BUCKET, demo_obj)
    for k in ("object_name", "size", "etag", "content_type", "last_modified"):
        print(f"  {k:15s} {getattr(st, k)}")
    print()

    # 6. 下载
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = DOWNLOAD_DIR / "GBT+20801.1-2020.pdf"
    print(f"== 6. 下载 {demo_obj} -> {dest} ==")
    client.fget_object(DEMO_BUCKET, demo_obj, str(dest))
    print(f"  [完成] 大小 {dest.stat().st_size} 字节")
    print()

    # 7. 预签名 URL（临时下载链接，无需账号密码）
    print("== 7. 预签名 URL（7 天有效）==")
    url = client.presigned_get_object(DEMO_BUCKET, demo_obj, expires=timedelta(days=7))
    print(f"  {url}")
    print()

    # 8. 删除演示（可选，注释掉则保留数据）
    print("== 8. 清理演示对象 ==")
    answer = os.getenv("MINIO_DEMO_KEEP", "").strip().lower()
    if answer in ("1", "yes", "true"):
        print("  检测到 MINIO_DEMO_KEEP，跳过删除，保留数据。")
    else:
        for obj in list(client.list_objects(DEMO_BUCKET, prefix=PREFIX, recursive=True)):
            client.remove_object(DEMO_BUCKET, obj.object_name)
            print(f"  [删除] {obj.object_name}")
        client.remove_bucket(DEMO_BUCKET)
        print(f"  [删除] bucket {DEMO_BUCKET}")
    print()


if __name__ == "__main__":
    try:
        demo()
    except S3Error as e:
        print(f"[MinIO 错误] code={e.code} message={e.message}")
        raise SystemExit(1)