"""
「普通 Python 脚本 vs MinerU」PDF 解析对比（只读，不入库）。

用法：
  .venv\\Scripts\\python.exe compare_pdf.py doc\\GBT+20801.1-2020.pdf
  .venv\\Scripts\\python.exe compare_pdf.py doc\\a.pdf --open

说明：
  左边是「普通 Python」方案（PyMuPDF：文本 + find_tables 表格检测）；
  右边是把 MinerU 的解析结果（content_list.json）重放出来做对照。
  不写 Milvus / Neo4j，纯粹用来对比解析效果。

输出：
  data/compare_preview/index.html
  data/compare_preview/pages/*.jpg
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
from pathlib import Path

try:
    import pymupdf
except ImportError:
    import fitz as pymupdf  # type: ignore

ROOT = Path(__file__).resolve().parent
MINERU_CACHE = ROOT / "data/parsed/mineru"
OUT_ROOT = ROOT / "data/compare_preview"

DISCARD_TYPES = {
    "discarded", "header", "footer", "page_number",
    "aside_text", "page_footnote", "image", "equation",
    "interline_equation", "inline_equation",
}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def find_mineru_json(pdf: Path) -> Path | None:
    stem = pdf.stem
    hits = sorted(
        (MINERU_CACHE / stem).rglob("*_content_list.json"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    return hits[0] if hits else None


def find_mineru_pdfs(base: Path) -> tuple[Path | None, Path | None]:
    """返回 (origin.pdf, layout.pdf)。"""
    origin = layout = None
    for p in base.rglob("*_origin.pdf"):
        origin = p
    for p in base.rglob("*_layout.pdf"):
        layout = p
    return origin, layout


def mineru_blocks(items: list[dict]) -> dict[int, list[dict]]:
    by_page: dict[int, list[dict]] = {}
    for it in items:
        by_page.setdefault(int(it.get("page_idx", 0)), []).append(it)
    return by_page


def mineru_text(item: dict) -> str:
    t = item.get("type")
    if t == "table":
        body = item.get("table_body") or item.get("text") or ""
        return norm(re.sub(r"<[^>]+>", " ", body))
    if t == "list":
        return norm(" ".join(item.get("list_items") or []))
    return norm(item.get("text", ""))


def render_mineru_item(item: dict) -> str:
    t = item.get("type")
    text = mineru_text(item)
    if t == "table":
        body = item.get("table_body") or f"<pre>{html.escape(text)}</pre>"
        return f'<div class="mtbl">{body}</div>'
    if item.get("text_level"):
        return f'<h4>{html.escape(text)}</h4>'
    return f'<p>{html.escape(text)}</p>'


def pymupdf_tables(pdf: pymupdf.Document) -> dict[int, list[list[list[str | None]]]]:
    """返回 {page_idx: [ [ [cell,...], ... ] ] }，即每页若干张表，每张表是二维矩阵。"""
    out: dict[int, list[list[list[str | None]]]] = {}
    for i in range(pdf.page_count):
        tabs = pdf[i].find_tables().tables
        matrices = [] if tabs else [[[]]]
        for t in tabs:
            raw = t.extract()
            cleaned = [[("" if c is None else str(c).strip()) for c in row] for row in raw]
            matrices.append(cleaned)
        if tabs:
            out[i] = matrices
    return out


def render_matrix(matrix: list[list[str]]) -> str:
    if not matrix or not any(any(c for c in row) for row in matrix):
        return '<p class="muted">（未提取到单元内容）</p>'
    rows = []
    for r in matrix:
        cells = "".join(f"<td>{html.escape(c)}</td>" for c in r)
        rows.append(f"<tr>{cells}</tr>")
    return f'<table class="ptbl"><tbody>{"".join(rows)}</tbody></table>'


def main() -> None:
    ap = argparse.ArgumentParser(description="普通 Python vs MinerU PDF 解析对比")
    ap.add_argument("pdf", help="PDF 路径")
    ap.add_argument("--out", default=str(OUT_ROOT), help="输出目录")
    ap.add_argument("--open", action="store_true", help="生成后浏览器打开")
    args = ap.parse_args()

    pdf = Path(args.pdf).resolve()
    if not pdf.exists():
        raise SystemExit(f"文件不存在：{pdf}")

    doc = pymupdf.open(pdf)
    n_pages = doc.page_count

    mj_json = find_mineru_json(pdf)
    if not mj_json:
        raise SystemExit(
            f"没找到 {pdf.stem} 的 MinerU 解析结果。请先运行：\n"
            f"  .venv-mineru\\Scripts\\mineru.exe -p \"{pdf}\" -o data/parsed/mineru -b pipeline"
        )
    items = json.loads(mj_json.read_text(encoding="utf-8"))
    by_page = mineru_blocks(items)
    origin_pdf, layout_pdf = find_mineru_pdfs(mj_json.parent)

    # 普通 Python（PyMuPDF）逐页文本 + 表格
    py_text: dict[int, str] = {}
    for i in range(n_pages):
        py_text[i] = doc[i].get_text("text")
    py_tabs = pymupdf_tables(doc)

    # MinerU 统计
    mj_kept = [x for x in items if x.get("type") not in DISCARD_TYPES]
    mj_discarded = [x for x in items if x.get("type") in DISCARD_TYPES]
    mj_tables = [x for x in items if x.get("type") == "table"]

    # PyMuPDF 统计
    py_table_count = sum(len(v) for v in py_tabs.values() if v and v != [[]])

    # 页图
    out = Path(args.out).resolve()
    img_dir = out / "pages"
    img_dir.mkdir(parents=True, exist_ok=True)
    origin_doc = pymupdf.open(origin_pdf) if origin_pdf else doc
    layout_doc = pymupdf.open(layout_pdf) if layout_pdf else None
    page_imgs: dict[int, tuple[str, str]] = {}
    for i in range(n_pages):
        o = img_dir / f"p{i + 1}-origin.jpg"
        origin_doc[i].get_pixmap(dpi=110).save(o, jpg_quality=82)
        l = img_dir / f"p{i + 1}-layout.jpg"
        if layout_doc and i < layout_doc.page_count:
            layout_doc[i].get_pixmap(dpi=110).save(l, jpg_quality=82)
            page_imgs[i] = (o.name, l.name)
        else:
            page_imgs[i] = (o.name, "")

    # 逐页三栏
    page_html = []
    for i in range(n_pages):
        mj_items = by_page.get(i, [])
        mj_kept_p = [x for x in mj_items if x.get("type") not in DISCARD_TYPES]
        mj_disc_p = [x for x in mj_items if x.get("type") in DISCARD_TYPES]
        mj_body = "\n".join(render_mineru_item(x) for x in mj_kept_p)
        disc_html = ""
        if mj_disc_p:
            disc_items = "".join(
                f"<li><em>{html.escape(x.get('type','?'))}</em> {html.escape(mineru_text(x)[:60])}</li>"
                for x in mj_disc_p[:12]
            )
            disc_html = (
                f'<details class="disc"><summary>MinerU 丢弃 {len(mj_disc_p)} 块（页眉页脚等）</summary>'
                f"<ul>{disc_items}</ul></details>"
            )

        # PyMuPDF 栏
        py_raw = html.escape(py_text.get(i, "")).replace("\\n", "\n")
        py_tab_html = ""
        tabs = py_tabs.get(i) or []
        if tabs and tabs != [[]]:
            py_tab_html = f'<div class="py-tabs"><b class="tagged">PyMuPDF find_tables 检测到 {len(tabs)} 张表</b>'
            mat = tabs[0] if tabs else []
            py_tab_html += render_matrix(mat) + "</div>"
        else:
            py_tab_html = '<p class="muted">此页未检测到表格</p>'

        o_img, l_img = page_imgs[i]
        layout_col = (
            f'<figure><img src="pages/{l_img}" alt="MinerU 版面上"><figcaption>MinerU 版面框</figcaption></figure>'
            if l_img
            else ""
        )

        page_html.append(f"""
        <article class="page">
          <div class="page-head"><h2>第 {i + 1} 页</h2></div>
          <div class="grid">
            <section class="col">
              <h3 class="c1">原始页面</h3>
              <figure><img src="pages/{o_img}" alt="第 {i + 1} 页"></figure>
              {layout_col}
            </section>
            <section class="col">
              <h3 class="c2">普通 Python（PyMuPDF）</h3>
              <pre class="raw">{py_raw}</pre>
              {py_tab_html}
            </section>
            <section class="col">
              <h3 class="c3">MinerU（pipeline）</h3>
              <div class="mj">{mj_body}</div>
              {disc_html}
            </section>
          </div>
        </article>""")

    summary_rows = [
        ("文本提取", "直接读 PDF 文本层，秒级", "版面分析 + OCR，修正字形与顺序"),
        ("表格", "find_tables 靠表格线猜测，合并单元格会拆成重复/空单元", "结构化 HTML，保留 rowspan/colspan 合并语义"),
        ("公式 / 上下标", "按普通文本原样输出，易错位", "单独公式块（支持 LaTeX）"),
        ("图片", "只能整页绘制，不提取内容", "识别并单独标注图片块"),
        ("页眉页脚", "混在正文里，页码会污染结果", "识别为 discarded 块单独剔除"),
        ("扫描件", "无文本层时基本拿不到字", "OCR 可识别"),
        ("字形错误", "本例出现“!力容器”(应为“压力容器”)", "OCR 修正为正确文字"),
        ("版面顺序", "按 PDF 内部顺序，可能与视觉阅读顺序不符", "版面分析后按阅读顺序输出"),
        ("速度 / 资源", "毫秒~秒级，CPU/内存几乎为零", "需下载模型(~3.3GB)，CPU 约十几秒/页"),
    ]
    rows_html = "".join(
        f"<tr><th>{html.escape(dim)}</th><td>{html.escape(py)}</td><td>{html.escape(mj)}</td></tr>"
        for dim, py, mj in summary_rows
    )

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>普通 Python vs MinerU · PDF 解析对比</title>
<style>
  :root{{--bg:#f5f6f9;--card:#fff;--ink:#1b2333;--muted:#6b7280;--line:#e5e7eb;--blue:#2f6bff;--green:#047857;--amber:#b45309}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--ink);font-family:"Microsoft YaHei","PingFang SC","Segoe UI",sans-serif;line-height:1.65;font-size:13.5px}}
  header{{background:linear-gradient(120deg,#101a33,#1e3a8a 60%,#2f6bff);color:#fff;padding:28px 34px}}
  header h1{{margin:0 0 6px;font-size:23px}}
  header p{{margin:0;color:#c7d2fe;font-size:13px}}
  main{{max-width:1500px;margin:0 auto;padding:20px 20px 70px}}
  .stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}}
  .stat{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:13px 16px}}
  .stat b{{display:block;font-size:21px;color:var(--blue)}}
  .stat span{{color:var(--muted);font-size:12px}}
  .card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:16px;overflow:auto}}
  .card h3{{margin:0 0 10px;font-size:15px}}
  table.diff{{width:100%;border-collapse:collapse;font-size:12.8px}}
  table.diff th,table.diff td{{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}}
  table.diff th{{background:#f0f4ff;min-width:100px}}
  table.diff td:first-child{{color:#1e3a8a;font-weight:600}}
  .page{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-bottom:22px}}
  .page-head h2{{margin:0 0 12px;font-size:17px}}
  .grid{{display:grid;grid-template-columns:minmax(240px,0.9fr) 1fr 1fr;gap:14px}}
  .col{{min-width:0}}
  .col h3{{margin:0 0 8px;font-size:13px;padding:5px 10px;border-radius:6px;color:#fff}}
  .c1{{background:#475569}}.c2{{background:#b45309}}.c3{{background:#047857}}
  figure{{margin:0 0 8px}}
  figure img{{width:100%;height:auto;border:1px solid var(--line);border-radius:6px;display:block}}
  figcaption{{text-align:center;color:var(--muted);font-size:11px;margin-top:4px}}
  pre.raw{{background:#fbfaf7;border:1px solid #f0e6d8;border-radius:8px;padding:10px;white-space:pre-wrap;font-family:"Consolas",monospace;font-size:11.5px;max-height:600px;overflow:auto;margin:0 0 8px}}
  .mj{{background:#f5faf7;border:1px solid #d8eadf;border-radius:8px;padding:10px 12px}}
  .mj h4{{margin:10px 0 4px;font-size:13.5px;color:#065f46}}
  .mj p{{margin:4px 0;font-size:12.8px}}
  table.ptbl,table.mtbl table{{border-collapse:collapse;font-size:11.5px;margin:6px 0;width:100%}}
  table.ptbl td,table.mtbl td{{border:1px solid #d6d3d1;padding:4px 6px}}
  table.mtbl{{background:#fff;border:1px solid var(--line);border-radius:6px;padding:6px;margin-bottom:8px}}
  .tagged{{display:inline-block;background:#fff7ed;color:#b45309;border-radius:4px;padding:1px 8px;font-size:11px;margin-bottom:4px}}
  details.disc{{margin-top:8px;font-size:12px}}
  details.disc summary{{cursor:pointer;color:#b45309}}
  details.disc li{{font-size:11.5px;margin:3px 0;color:#57534e}}
  details.disc em{{color:#b45309;font-style:normal}}
  .muted{{color:var(--muted)}}
  @media(max-width:900px){{.grid{{grid-template-columns:1fr}}.stats{{grid-template-columns:1fr 1fr}}}}
</style>
</head>
<body>
<header>
  <h1>PDF 解析对比：普通 Python vs MinerU</h1>
  <p>{html.escape(pdf.name)} · {n_pages} 页 · 只读对比，不写 Milvus / Neo4j</p>
</header>
<main>
  <div class="stats">
    <div class="stat"><b>{n_pages}</b><span>页</span></div>
    <div class="stat"><b>{py_table_count}</b><span>PyMuPDF 检出的表</span></div>
    <div class="stat"><b>{len(mj_tables)}</b><span>MinerU 检出的表</span></div>
    <div class="stat"><b>{len(mj_discarded)}</b><span>MinerU 丢弃块</span></div>
  </div>

  <div class="card">
    <h3>一图看懂差异</h3>
    <table class="diff">{rows_html}</table>
  </div>

  {''.join(page_html)}
</main>
</body>
</html>"""

    out.mkdir(parents=True, exist_ok=True)
    html_path = out / "index.html"
    html_path.write_text(html_doc, encoding="utf-8")
    print(f"[完成] {html_path}")
    if args.open:
        os.startfile(html_path)  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()