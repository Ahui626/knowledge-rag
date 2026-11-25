# PDF 解析对比：普通 Python vs MinerU

本文回答一个高频问题：**用普通 Python 脚本解析 PDF 能到什么程度？和 MinerU 差多少？表格/格式解析效果如何？**

结论先说：**对「有正常文本层」的 PDF，PyMuPDF 拿正文够用、还特别快；但一遇到表格合并单元格、页眉页脚、公式/上下标、扫描件、字形错乱，普通脚本就露馅，MinerU 的优势立刻拉开。**

配套可视化对比界面：运行

```powershell
.venv\Scripts\python.exe compare_pdf.py doc\GBT+20801.1-2020.pdf --open
```

会生成 `data/compare_preview/index.html`，逐页把「原始页 / PyMuPDF 解析 / MinerU 解析」三栏并排看。

---

## 一、普通 Python 能解析到什么程度

先分清「普通 Python」其实分好几档，能力差很多：

| 库 | 拿到什么 | 表格 | OCR | 版面顺序 | 资源 |
|---|---|---|---|---|---|
| `pypdf` | 纯文本字符串 | 无 | 无 | 无 | 极轻 |
| `PyMuPDF`(fitz/pymupdf) | 文本块、坐标、`find_tables` | 靠表格线猜测 | 无 | 弱 | 轻、快 |
| `pdfplumber` | 字符级坐标 + 表格 | 规则表格强 | 无 | 弱 | 轻 |
| **MinerU** | 结构化文档（标题/正文/表格/公式/图片） | HTML + 合并语义 | 有 | 有 | 重（模型 ~3.3GB） |

核心原理差异：

- **普通脚本 = 读 PDF 里已经存在的「文本层」**。PDF 本质是“把字画在哪的指令”，脚本只是按作者写好的顺序把字符拼回来。文本层好就快又准，文本层烂（扫描件、乱码映射）就废。
- **MinerU = 版面分析 + OCR + 多模型识别**。先把页面当图片重新“看”一遍，识别区块、表、公式，再逐块 OCR/识别，所以不依赖原文本层质量。

---

## 二、实测对比（GB/T 20801.1-2020，8 页）

### 1. 字形的坑

PyMuPDF 直接抓文本层，抓出了这种东西：

```
ｇ）锅炉、!力容器以及加热炉的内部管道...
```

`!力容器` 其实是 **“压力容器”**——原 PDF 把“压”字的字形映射坏了，普通脚本”忠实“地把错字原样输出。MinerU 走 OCR，直接识别成正确的“压力容器”。

### 2. 页码 / 页眉页脚混入

PyMuPDF 的正文里混进了 `１`（页脚页码）、`犌犅／犜２０８０１．１—２０２０`（页眉）这种噪声，你得自己写规则去过滤。

MinerU 把它们识别成 `discarded / page_number / header` 块，**22 个这类块被单独剔除**，正文干净。

### 3. 表格：都能找到，但质量差一档

本文档有 3 张表（第 7、8 页）。两者**都检测到了 3 张表**，数量一样，但内容语义不同：

- **PyMuPDF `find_tables()`** 靠表格线猜行列，**合并单元格会变空**：

  ```
  ['名 称', None, '类别', '判 据']
  ['ＧＢ５０１６０—２００８', '可燃气体', '甲', '…']
  [None, None, '乙', '…']          ← 合并上去的“可燃气体”变 None，语义丢了
  ```

- **MinerU** 输出结构化 HTML，**保留 rowspan/colspan**：

  ```html
  <td rowspan=2 colspan=1>GB50160—2008</td>
  <td rowspan=6 colspan=1>可燃液体</td>
  ```

  “这个值跨几行/几列”的语义被完整保留，能无损转 Markdown / DataFrame。

### 4. 公式、上下标、图片、扫描件

- 本文档没有独立公式，但表格里有上下标（如 `ＭＰａ`、化学式）。PyMuPDF 按普通文本原样输出，上下标位置丢失；MinerU 单独识别公式块并支持 LaTeX。
- 图片：PyMuPDF 只能整页绘制，不给图片内容；MinerU 会标注出图片块。
- 扫描件：这是最悬殊的一项——纯扫描 PDF 没有文本层，PyMuPDF 基本输出空；MinerU 靠 OCR 正常识别。

### 5. 速度 / 资源

| | PyMuPDF | MinerU(pipeline) |
|---|---|---|
| 速度 | 8 页 ≈ 秒级 | 8 页 ≈ 100 秒（约 13 秒/页，CPU） |
| 内存 | 近乎 0 | 峰值约 2.8GB |
| 依赖 | 一个 wheel | 模型组约 3.3GB + 首次下载 |

---

## 三、什么时候用哪个

- **只要正文、文档是规范生成的（Word/LaTeX 导出）**：PyMuPDF / pypdf 足够，快、省、离线。
- **表格为主、结构清晰**：可先试 PyMuPDF `find_tables`，复杂跨行跨列时上 `pdfplumber`，仍不够再 MinerU。
- **扫描件 / 版面复杂 / 要公式 / 要版面顺序 / 建 RAG 知识库**：直接 MinerU，别纠结。
- **生产 RAG 管线**：`解析用 MinerU + 检索用 Milvus`，各司其职——这正是本项目早期 `ingest.py` 的选择。

---

## 四、相关资料

- 可视化对比界面：`data/compare_preview/index.html`（脚本 `compare_pdf.py`）
- MinerU 单工具预览（只 MinerU）：`preview_pdf.py` → `data/preview/<文件>/preview/index.html`
- 完整处理链路说明：`docs/技术链路说明.md`