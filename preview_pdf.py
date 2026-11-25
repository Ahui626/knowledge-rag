"""
PDF 解析效果预览（只读，不写 Milvus / Neo4j）。

用法：
  .venv\\Scripts\\python.exe preview_pdf.py doc\\GBT+20801.1-2020.pdf
  .venv\\Scripts\\python.exe preview_pdf.py doc\\xxx.pdf --force --open
  .venv\\Scripts\\python.exe preview_pdf.py doc\\a.pdf doc\\b.pdf

输出：
  data/preview/<文件名>/preview/index.html
  data/preview/<文件名>/preview/pages/*.jpg

页面内容：左侧原始页、右侧 MinerU 版面框，下方是逐块解析文本。
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import pymupdf
except ImportError:  # 兼容旧版 PyMuPDF
    import fitz as pymupdf  # type: ignore

ROOT = Path(__file__).resolve().parent
MINERU_CLI = ROOT / ".venv-mineru/Scripts/mineru.exe"
PARSED_CACHE = ROOT / "data/parsed/mineru"
PREVIEW_ROOT = ROOT / "data/preview"

DISCARD_TYPES = {
    "discarded", "header", "footer", "page_number",
    "aside_text", "page_footnote",
}
IMAGE_TYPES = {"image"}
EQUATION_TYPES = {"equation", "interline_equation", "inline_equation"}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def item_text(item: dict) -> str:
    if item.get("type") == "table":
        body = item.get("table_body") or item.get("text") or ""
        return norm(re.sub(r"<[^>]+>", " ", body))
    if item.get("type") == "list":
        return norm(" ".join(item.get("list_items") or []))
    return norm(item.get("text", ""))


def find_outputs(base: Path) -> dict[str, Path | None]:
    def newest(pattern: str) -> Path | None:
        hits = sorted(base.rglob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        return hits[0] if hits else None

    return {
        "content_list": newest("*_content_list.json"),
        "middle": newest("*_middle.json"),
        "markdown": newest("*.md"),
        "layout": newest("*_layout.pdf"),
        "span": newest("*_span.pdf"),
        "origin": newest("*_origin.pdf"),
    }


def find_existing_mineru(stem: str) -> Path | None:
    """优先复用 data/parsed 里已经解析过的结果，避免重复跑 MinerU。"""
    for base in [PREVIEW_ROOT / stem / "mineru", PARSED_CACHE / stem]:
        if base.exists() and find_outputs(base)["content_list"]:
            return base
    return None


def run_mineru(pdf: Path, out_root: Path, backend: str) -> Path:
    if not MINERU_CLI.exists():
        raise SystemExit(
            f"找不到 MinerU：{MINERU_CLI}\n"
            "请先安装 .venv-mineru 并下载模型，见 README「从零重建 Python 环境」。"
        )
    out_root.mkdir(parents=True, exist_ok=True)
    cmd = [str(MINERU_CLI), "-p", str(pdf), "-o", str(out_root), "-b", backend]
    if backend == "pipeline":
        cmd += ["-m", "auto"]

    env = dict(os.environ)
    env.update({
        "MINERU_TOOLS_CONFIG_JSON": str((ROOT / "mineru.json").resolve()),
        "MODELSCOPE_CACHE": str((ROOT / "data/.cache/modelscope").resolve()),
        "YOLO_CONFIG_DIR": str((ROOT / "data/.cache/ultralytics").resolve()),
        "MPLCONFIGDIR": str((ROOT / "data/.cache/matplotlib").resolve()),
        "MINERU_MODEL_SOURCE": "modelscope",
    })
    print(f"[MinerU] {' '.join(cmd)}")
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="ignore")
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-3000:]
        raise SystemExit(f"MinerU 解析失败：\n{tail}")
    return out_root


def rel_link(target: Path, base: Path) -> str:
    return Path(os.path.relpath(target, base)).as_posix()


def render_item(item: dict) -> str:
    typ = item.get("type")
    text = item_text(item)
    if typ == "table":
        return f'<pre class="tbl">{html.escape(text)}</pre>'
    if typ in EQUATION_TYPES:
        return f'<pre class="eq">{html.escape(text)}</pre>'
    if typ in IMAGE_TYPES:
        caption = " ".join(item.get("image_caption") or [])
        return f'<p class="img">[图片] {html.escape(norm(caption))}</p>'
    if typ == "list":
        items = item.get("list_items") or []
        if items:
            lis = "".join(f"<li>{html.escape(norm(x))}</li>" for x in items)
            return f"<ul>{lis}</ul>"
        return ""
    if item.get("text_level") or typ == "title":
        return f"<h4>{html.escape(text)}</h4>"
    return f"<p>{html.escape(text)}</p>"


def build_html(pdf: Path, base: Path, out_dir: Path, pages: int) -> Path:
    outs = find_outputs(base)
    content_list = outs["content_list"]
    if not content_list:
        raise SystemExit("没有找到 content_list.json，解析可能失败")

    items = json.loads(content_list.read_text(encoding="utf-8"))
    kept = [x for x in items if x.get("type") not in DISCARD_TYPES]
    discarded = [x for x in items if x.get("type") in DISCARD_TYPES]
    total_chars = sum(len(item_text(x)) for x in kept)
    tables = [x for x in kept if x.get("type") == "table"]
    headings = [x for x in kept if x.get("text_level")]
    images = [x for x in kept if x.get("type") in IMAGE_TYPES]

    by_page: dict[int, list[dict]] = {}
    for it in kept:
        by_page.setdefault(int(it.get("page_idx", 0)), []).append(it)

    artifacts = []
    for label, key in [
        ("content_list.json", "content_list"), ("middle.json", "middle"),
        ("Markdown", "markdown"), ("layout.pdf（版面框）", "layout"),
        ("span.pdf（文本片段）", "span"), ("origin.pdf（原始页）", "origin"),
    ]:
        if outs[key]:
            artifacts.append(f'<a href="{rel_link(outs[key], out_dir)}">{html.escape(label)}</a>')
    artifact_html = "\n".join(artifacts) or '<span class="muted">无</span>'

    discard_lines = []
    for it in discarded[:60]:
        t = item_text(it)
        if t:
            page = int(it.get("page_idx", 0)) + 1
            discard_lines.append(f"<li><span class='tag'>p{page} · {html.escape(it.get('type','?'))}</span> {html.escape(t[:120])}</li>")
    discard_html = "".join(discard_lines) or "<li class='muted'>没有丢弃块</li>"

    page_html = []
    for p in sorted(by_page):
        blocks = by_page[p]
        chars = sum(len(item_text(x)) for x in blocks)
        body = "\n".join(render_item(x) for x in blocks)
        page_html.append(f"""
        <article class="page">
          <div class="page-head">
            <h2>第 {p + 1} 页</h2>
            <span class="meta">{len(blocks)} 个块 · {chars} 字</span>
          </div>
          <div class="compare">
            <figure>
              <img src="pages/page-{p + 1}-origin.jpg" alt="第 {p + 1} 页原图">
              <figcaption>原始 PDF 页面</figcaption>
            </figure>
            <figure>
              <img src="pages/page-{p + 1}-layout.jpg" alt="第 {p + 1} 页版面检测">
              <figcaption>MinerU 版面框（block 级）</figcaption>
            </figure>
          </div>
          <div class="parsed">
            <div class="parsed-title">解析文本</div>
            {body}
          </div>
        </article>""")

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PDF 解析预览 · {html.escape(pdf.name)}</title>
<style>
  :root{{--bg:#f5f6f9;--card:#fff;--ink:#1b2333;--muted:#6b7280;--line:#e5e7eb;--blue:#2f6bff;--amber:#b45309}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--ink);font-family:"Microsoft YaHei","PingFang SC","Segoe UI",sans-serif;line-height:1.7;font-size:14px}}
  header{{background:linear-gradient(120deg,#101a33,#1e3a8a 60%,#2f6bff);color:#fff;padding:30px 36px}}
  header h1{{margin:0 0 6px;font-size:24px}}
  header p{{margin:0;color:#c7d2fe;font-size:13px}}
  main{{max-width:1180px;margin:0 auto;padding:22px 22px 60px}}
  .stats{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:18px}}
  .stat{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}}
  .stat b{{display:block;font-size:22px;color:var(--blue)}}
  .stat span{{color:var(--muted);font-size:12px}}
  .card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin-bottom:18px}}
  .card h3{{margin:0 0 10px;font-size:16px}}
  .links a{{display:inline-block;margin:4px 10px 4px 0;padding:7px 12px;border:1px solid var(--line);border-radius:8px;color:var(--blue);text-decoration:none;font-size:13px}}
  .links a:hover{{background:#eff4ff}}
  details summary{{cursor:pointer;color:var(--blue);font-size:13px}}
  details li{{font-size:12.5px;margin:4px 0;color:#374151}}
  .tag{{display:inline-block;background:#fff1f0;color:#b42318;border-radius:4px;padding:1px 6px;font-size:11px;margin-right:4px}}
  .page{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin-bottom:22px}}
  .page-head{{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:12px}}
  .page-head h2{{margin:0;font-size:18px}}
  .meta{{color:var(--muted);font-size:12px}}
  .compare{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
  figure{{margin:0;background:#fafbfe;border:1px solid var(--line);border-radius:10px;padding:8px}}
  figure img{{width:100%;height:auto;display:block;border-radius:4px}}
  figcaption{{text-align:center;color:var(--muted);font-size:12px;margin-top:6px}}
  .parsed{{margin-top:14px;border-top:1px dashed var(--line);padding-top:12px}}
  .parsed-title{{font-size:12px;color:var(--muted);margin-bottom:6px;letter-spacing:.5px}}
  .parsed h4{{margin:12px 0 4px;font-size:14.5px;color:#1e3a8a}}
  .parsed p{{margin:4px 0;font-size:13.5px}}
  .parsed ul{{margin:6px 0;padding-left:22px}}
  .tbl{{background:#f8fafc;border:1px solid var(--line);border-radius:8px;padding:10px;white-space:pre-wrap;font-size:12.5px;overflow:auto}}
  .eq{{background:#f5f3ff;border:1px solid #ddd6fe;border-radius:8px;padding:8px 10px;font-size:12.5px;overflow:auto}}
  .img{{color:var(--muted);font-size:12.5px}}
  .muted{{color:var(--muted)}}
  @media (max-width:800px){{.stats{{grid-template-columns:1fr 1fr}}.compare{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<header>
  <h1>PDF 解析效果预览</h1>
  <p>{html.escape(pdf.name)} · {html.escape(str(base.relative_to(ROOT)) if base.is_relative_to(ROOT) else str(base))} · 只读预览，不写 Milvus / Neo4j</p>
</header>
<main>
  <div class="stats">
    <div class="stat"><b>{pages}</b><span>页</span></div>
    <div class="stat"><b>{len(kept)}</b><span>保留块</span></div>
    <div class="stat"><b>{total_chars}</b><span>识别字符</span></div>
    <div class="stat"><b>{len(tables)}</b><span>表格 · {len(headings)} 标题 · {len(images)} 图片</span></div>
    <div class="stat"><b>{len(discarded)}</b><span>丢弃块（页眉页脚等）</span></div>
  </div>

  <div class="card links">
    <h3>原始产物</h3>
    {artifact_html}
  </div>

  <div class="card">
    <h3>被丢弃的块</h3>
    <details>
      <summary>展开查看 {len(discarded)} 个 discarded / header / footer 块</summary>
      <ul>{discard_html}</ul>
    </details>
  </div>

  {''.join(page_html)}
</main>
</body>
</html>"""

    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "index.html"
    html_path.write_text(html_doc, encoding="utf-8")
    return html_path


def make_preview(pdf: Path, out_base: Path, force: bool, backend: str) -> Path:
    stem = pdf.stem
    base = None if force else find_existing_mineru(stem)
    if base is None:
        run_root = out_base / stem / "mineru"
        if force and run_root.exists():
            shutil.rmtree(run_root)
        run_mineru(pdf, run_root, backend)
        base = run_root

    outs = find_outputs(base)
    if not outs["content_list"] or not outs["origin"] or not outs["layout"]:
        raise SystemExit(f"MinerU 输出不完整：{base}")

    out_dir = out_base / stem / "preview"
    img_dir = out_dir / "pages"
    if img_dir.exists():
        shutil.rmtree(img_dir)
    img_dir.mkdir(parents=True, exist_ok=True)

    origin = pymupdf.open(outs["origin"])
    layout = pymupdf.open(outs["layout"])
    page_count = min(len(origin), len(layout))
    for i in range(page_count):
        origin[i].get_pixmap(dpi=110).save(img_dir / f"page-{i + 1}-origin.jpg", jpg_quality=82)
        layout[i].get_pixmap(dpi=110).save(img_dir / f"page-{i + 1}-layout.jpg", jpg_quality=82)

    return build_html(pdf, base, out_dir, page_count)


def main() -> None:
    ap = argparse.ArgumentParser(description="PDF 解析效果预览（不入库）")
    ap.add_argument("pdfs", nargs="+", help="一个或多个 PDF 路径")
    ap.add_argument("--out", default=str(PREVIEW_ROOT), help="预览输出根目录")
    ap.add_argument("--force", action="store_true", help="忽略已有解析结果，重新跑 MinerU")
    ap.add_argument("--backend", default="pipeline", help="MinerU 后端，默认 pipeline")
    ap.add_argument("--open", action="store_true", help="生成后用默认浏览器打开")
    args = ap.parse_args()

    out_base = Path(args.out).resolve()
    for raw in args.pdfs:
        pdf = Path(raw).resolve()
        if not pdf.exists() or pdf.suffix.lower() != ".pdf":
            print(f"[跳过] 不是 PDF：{raw}")
            continue
        html_path = make_preview(pdf, out_base, args.force, args.backend)
        print(f"[完成] {html_path}")
        if args.open:
            os.startfile(html_path)  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()
