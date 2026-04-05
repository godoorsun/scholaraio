---
name: ingest
description: Ingest papers, patents, and documents from inbox into the knowledge base. Runs the pipeline to convert PDFs via MinerU (auto-splits long PDFs), Office files (DOCX/XLSX/PPTX) via MarkItDown, extract metadata, deduplicate by DOI or patent publication number, and build indexes. Supports four inboxes - regular papers, patents, theses, and general documents. Use when the user has new papers, patents, or documents to process, wants to run the pipeline, or rebuild indexes.
version: 1.0.0
author: ZimoLiao/scholaraio
license: MIT
tags: ["academic", "papers", "patent", "pipeline", "pdf", "docx", "office"]
---
# 入库文档

将 inbox 中的 PDF、Office 文档（DOCX/XLSX/PPTX）或 Markdown 文件处理入库。支持论文、专利、学位论文和一般文档四种入库类型。

## 支持的文件格式

| 格式 | 放入目录 | 处理方式 |
|------|----------|----------|
| `.pdf` | `data/inbox/` 或 `data/inbox-doc/` | MinerU 转 Markdown |
| `.pdf` / `.md` | `data/inbox-patent/` | 专利文献（按公开号去重） |
| `.docx` `.xlsx` `.pptx` | `data/inbox-doc/` | MarkItDown 转 Markdown |
| `.md` | 任意 inbox | 直接入库（跳过转换） |

## 执行逻辑

1. 根据用户意图选择预设：
   - **入库新文档**（默认）：使用 `ingest` 预设（= mineru, extract, dedup, ingest, embed, index）
   - **完整处理**：使用 `full` 预设（= mineru, extract, dedup, ingest, toc, l3, embed, index）
   - **仅重建索引**：使用 `reindex` 预设（= embed, index）
   - **仅内容富化**：使用 `enrich` 预设（= toc, l3, embed, index）

   > **注意**：`inbox-doc/` 始终使用专用步骤 `office_convert, mineru, extract_doc, ingest`，不受 preset 影响。`inbox-patent/` 和 `inbox-thesis/` 也有各自的固定流程。preset 中的 papers 级步骤（toc, l3）和 global 级步骤（embed, index）在处理完所有 inbox 后统一执行。

2. 执行流水线命令：

```bash
scholaraio pipeline <preset> [--dry-run] [--no-api] [--force] [--inspect]
```

可用预设：`full` | `ingest` | `enrich` | `reindex`

常用选项：
- `--dry-run` — 预览处理，不写文件
- `--no-api` — 离线模式，跳过外部 API 查询
- `--force` — 强制重新处理（toc/l3 等步骤）
- `--inspect` — 展示处理详情
- `--steps STEPS` — 自定义步骤序列（逗号分隔），如 `--steps toc,l3,index`
- `--list` — 列出所有可用步骤和预设

3. pipeline 会依次处理四个 inbox 目录：
   - `data/inbox/` — 普通论文（有 DOI 才入库，无 DOI 且非 thesis 转 pending）
   - `data/inbox-patent/` — 专利文献（按公开号去重，自动标记 patent，跳过 DOI 去重）
   - `data/inbox-thesis/` — 学位论文（跳过 DOI 去重，自动标记 thesis）
   - `data/inbox-doc/` — 非论文文档（技术报告、讲义、Word/Excel/PPT、标准文档等，跳过 DOI 去重，LLM 生成标题/摘要）

4. Office 文件处理流程（`data/inbox-doc/` 中的 DOCX/XLSX/PPTX）：
   - `step_office_convert`（MarkItDown）→ 转换为 `<stem>.md`
   - `step_extract_doc`（LLM 生成标题/摘要）
   - `step_ingest`（写入 `data/papers/`）
   - **依赖**：需安装 `pip install 'markitdown[docx,pptx,xlsx]'`

5. 专利文献处理逻辑（`data/inbox-patent/`）：
   - 自动提取公开号（CN/US/EP/WO/JP/KR/DE/FR/GB/TW/IN/AU 等格式）
   - 按公开号去重（非 DOI），跳过 DOI 检查
   - 自动标记 `paper_type: patent`

6. 无 DOI 论文的处理逻辑：
   - 来自 `data/inbox-thesis/` → 直接标记为 thesis 并入库
   - 来自 `data/inbox-doc/` → 标记为 document 类型，LLM 生成标题和摘要后入库
   - 来自 `data/inbox/` → LLM 分析判断是否 thesis
     - 是 thesis → 标记并入库
     - 不是 thesis → 转入 `data/pending/` 待人工确认

7. 超长 PDF（>100 页）自动切分为短 PDF 分段转换后合并。

## 执行约束

- 默认不要为了提速而临时拆成“本地并行 MinerU 预转换”再二次入库。除非用户明确要求特殊流程，否则统一使用标准 `pipeline ingest/full`。
- MinerU 产出的图片资源必须跟正文一起入库。无论中间目录名是 `*_images` 还是 `*_mineru_images`，最终论文目录里都必须规范成单一的 `images/` 文件夹，并与 `paper.md` 中的图片引用保持一致。

## 示例

用户说："我放了几篇新论文到 inbox，帮我入库"
→ 执行 `pipeline ingest`

用户说："把新论文全部处理完，包括提取目录和结论"
→ 执行 `pipeline full`

用户说："我有几份技术报告放在 inbox-doc 里了"
→ 执行 `pipeline ingest`（pipeline 自动处理四个 inbox 目录）

用户说："我把一个 Word 文档放进 inbox-doc 了"
→ 执行 `pipeline ingest`（自动用 MarkItDown 转换 DOCX）

用户说："我有几篇专利放在 inbox-patent 了"
→ 执行 `pipeline ingest`（自动处理四个 inbox 目录，专利按公开号去重）

用户说："重新建索引"
→ 执行 `pipeline reindex`
