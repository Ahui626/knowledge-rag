"""
文档解析：
- PDF 交给 MinerU（保留标题层级、表格、阅读顺序），输出统一 block 结构
- DOCX 用 python-docx 直接解析（MinerU 的 Office 支持依赖 LibreOffice，本机不装）
解析结果缓存到 data/parsed/docs.json，避免重复跑 MinerU。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

DOC_DIR = Path("doc")
PARSED_DIR = Path("data/parsed")
MINERU_OUT = PARSED_DIR / "mineru"
DOCS_CACHE = PARSED_DIR / "docs.json"
MINERU_PY = Path(".venv-mineru/Scripts/python.exe")
MINERU_CLI = Path(".venv-mineru/Scripts/mineru.exe")

HEADING_PATTERNS = [
    re.compile(r"^第[一二三四五六七八九十百]+[章节]"),
    re.compile(r"^[一二三四五六七八九十]+、"),
    re.compile(r"^\d+(\.\d+)*[、.．]?\s*\S"),
]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _is_heading(text: str, style: str = "") -> tuple[bool, int]:
    style_l = (style or "").lower()
    if "heading" in style_l or style_l.startswith("标题"):
        m = re.search(r"(\d)", style_l)
        level = int(m.group(1)) if m else 1
        return True, level
    t = text.strip()
    if len(t) <= 40 and HEADING_PATTERNS[1].match(t):
        return True, 1
    if len(t) <= 40 and HEADING_PATTERNS[0].match(t):
        return True, 1
    if len(t) <= 40 and re.match(r"^\d+(\.\d+)*[、.．]?\s*\S", t) and len(t) < 30:
        return True, 2
    return False, 0


def parse_docx(path: Path) -> dict[str, Any]:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(str(path))
    blocks: list[dict[str, Any]] = []
    title = path.stem

    for child in doc.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            p = Paragraph(child, doc)
            text = _norm(p.text)
            if not text:
                continue
            is_h, level = _is_heading(text, p.style.name if p.style else "")
            if is_h:
                blocks.append({"type": "title", "text": text, "level": level, "page": 0})
            else:
                blocks.append({"type": "text", "text": text, "page": 0})
        elif tag == "tbl":
            table = Table(child, doc)
            rows = []
            for row in table.rows:
                cells = [_norm(c.text) for c in row.cells]
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows:
                blocks.append({"type": "table", "text": "\n".join(rows), "page": 0})

    if blocks and blocks[0]["type"] == "title":
        title = blocks[0]["text"]
    return {
        "doc_id": path.stem,
        "title": title,
        "source": path.name,
        "doc_type": "留学政策" if "留学" in path.name or "计划" in path.name else "标准规范",
        "blocks": blocks,
    }


def _run_mineru(pdf: Path) -> None:
    """调用 MinerU CLI，输出到 data/parsed/mineru/<stem>/..."""
    if not MINERU_CLI.exists():
        raise RuntimeError("MinerU 未安装，无法解析 PDF")
    out_dir = MINERU_OUT / pdf.stem
    if out_dir.exists() and any(out_dir.rglob("*.md")):
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(MINERU_CLI),
        "-p", str(pdf),
        "-o", str(out_dir),
        "-b", "pipeline",
        "-m", "auto",
    ]
    # 把模型缓存和工具配置都放在项目目录，避免写入用户目录
    env = dict(os.environ)
    env.update({
        "MINERU_TOOLS_CONFIG_JSON": str(Path("mineru.json").resolve()),
        "MODELSCOPE_CACHE": str(Path("data/.cache/modelscope").resolve()),
        "YOLO_CONFIG_DIR": str(Path("data/.cache/ultralytics").resolve()),
        "MPLCONFIGDIR": str(Path("data/.cache/matplotlib").resolve()),
        "MINERU_MODEL_SOURCE": "modelscope",
    })
    print("  [MinerU]", " ".join(cmd))
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        errors="ignore", env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"MinerU 解析失败: {proc.stderr[-2000:]}")


def _blocks_from_content_list(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    blocks = []
    for item in data:
        typ = item.get("type")
        page = int(item.get("page_idx", 0)) + 1
        if typ == "text":
            text = _norm(item.get("text", ""))
            if text:
                blocks.append({"type": "text", "text": text, "page": page})
        elif typ == "title":
            text = _norm(item.get("text", ""))
            if text:
                blocks.append({"type": "title", "text": text, "level": int(item.get("text_level", 1)), "page": page})
        elif typ == "table":
            body = item.get("table_body") or item.get("text") or ""
            body = re.sub(r"<[^>]+>", " ", body)
            body = _norm(body)
            if body:
                blocks.append({"type": "table", "text": body, "page": page})
    return blocks


def _blocks_from_markdown(path: Path) -> list[dict[str, Any]]:
    blocks = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("!["):
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", s)
        if m:
            blocks.append({"type": "title", "text": _norm(m.group(2)), "level": len(m.group(1)), "page": 0})
        else:
            blocks.append({"type": "text", "text": _norm(s), "page": 0})
    return blocks


def parse_pdf(path: Path) -> dict[str, Any]:
    _run_mineru(path)
    out_dir = MINERU_OUT / path.stem
    content_lists = sorted(out_dir.rglob("*content_list.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if content_lists:
        blocks = _blocks_from_content_list(content_lists[0])
    else:
        mds = sorted(out_dir.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not mds:
            raise RuntimeError(f"MinerU 没有输出 {path.name}")
        blocks = _blocks_from_markdown(mds[0])
    title = path.stem
    for b in blocks:
        if b["type"] == "title":
            title = b["text"]
            break
    return {
        "doc_id": path.stem,
        "title": title,
        "source": path.name,
        "doc_type": "标准规范",
        "blocks": blocks,
    }


def parse_all(force: bool = False) -> list[dict[str, Any]]:
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    if DOCS_CACHE.exists() and not force:
        return json.loads(DOCS_CACHE.read_text(encoding="utf-8"))

    docs = []
    files = sorted(list(DOC_DIR.glob("*.docx")) + list(DOC_DIR.glob("*.pdf")))
    for f in files:
        print(f"[解析] {f.name}")
        if f.suffix.lower() == ".docx":
            docs.append(parse_docx(f))
        elif f.suffix.lower() == ".pdf":
            docs.append(parse_pdf(f))
    DOCS_CACHE.write_text(json.dumps(docs, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[解析] 完成，共 {len(docs)} 篇")
    return docs


if __name__ == "__main__":
    parse_all(force="--force" in sys.argv)
