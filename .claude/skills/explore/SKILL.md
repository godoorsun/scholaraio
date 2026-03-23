---
name: explore
description: Explore literature by fetching papers from OpenAlex or importing local metadata files (CSV/TSV/JSON/JSONL), building local embeddings, running BERTopic clustering, and multi-mode search (semantic/keyword/unified). Data is isolated in data/explore/<name>/. Use when the user wants to survey a journal, archive external metadata-only corpora, explore a research field, analyze an author's output, or do landscape analysis.
version: 1.0.0
author: ZimoLiao/scholaraio
license: MIT
tags: ["academic", "research", "literature", "discovery", "openalex"]
---
# 多维文献探索

从 OpenAlex 拉取文献，或从本地 metadata 文件导入文献记录（仅标题/摘要/作者/链接也可），再做本地嵌入 + BERTopic 聚类 + 多模式搜索，用于文献调研和灵感碰撞。数据与主库完全隔离，但可以通过联邦搜索和主库一起检索。

## 执行逻辑

### 拉取论文

支持多种过滤维度，可任意组合：

```bash
# 按期刊 ISSN
scholaraio explore fetch --issn <ISSN> --name <名称> [--year-range <起-止>]

# 按研究概念
scholaraio explore fetch --concept <OpenAlex-concept-ID> --name <名称>

# 按作者
scholaraio explore fetch --author <OpenAlex-author-ID> --name <名称>

# 按机构
scholaraio explore fetch --institution <OpenAlex-institution-ID> --name <名称>

# 按关键词
scholaraio explore fetch --keyword "acoustic metamaterial" --name <名称>

# 多维组合 + 高引过滤
scholaraio explore fetch --institution I123 --year-range 2020-2025 --min-citations 50 --name <名称>

# 增量更新（追加新论文，DOI 去重）
scholaraio explore fetch --issn 0022-1120 --name jfm --incremental
```

全部过滤参数：
- `--issn` — 期刊 ISSN
- `--concept` — OpenAlex concept ID
- `--topic-id` — OpenAlex topic ID
- `--author` — OpenAlex author ID
- `--institution` — OpenAlex institution ID
- `--keyword` — 标题/摘要关键词搜索
- `--source-type` — 来源类型（journal/conference/repository）
- `--oa-type` — 论文类型（article/review 等）
- `--min-citations` — 最小引用量
- `--year-range` — 年份过滤（如 2020-2025）
- `--name` — 探索库名称（默认从 filter 推导）
- `--incremental` — 增量更新模式

常用期刊 ISSN：
- JFM (Journal of Fluid Mechanics): 0022-1120
- PoF (Physics of Fluids): 1070-6631
- JCP (Journal of Computational Physics): 0021-9991
- IJMF (Int J Multiphase Flow): 0301-9322

### 生成嵌入

```bash
scholaraio explore embed --name <名称> [--rebuild]
```

### 主题聚类

```bash
scholaraio explore topics --name <名称> --build
scholaraio explore topics --name <名称> --rebuild --nr-topics <N>
scholaraio explore topics --name <名称>
scholaraio explore topics --name <名称> --topic <ID> [--top N]
```

### 搜索（三种模式）

```bash
# 语义搜索（默认）
scholaraio explore search --name <名称> "<查询词>" [--top N]

# 关键词搜索（FTS5）
scholaraio explore search --name <名称> "<查询词>" --mode keyword

# 融合搜索（语义 + 关键词 RRF 排序）
scholaraio explore search --name <名称> "<查询词>" --mode unified
```

### 生成可视化

```bash
scholaraio explore viz --name <名称>
```

### 列出所有探索库

```bash
scholaraio explore list
```

### 查看探索库信息

```bash
scholaraio explore info
scholaraio explore info --name <名称>
```

对于全新探索库，完整流程是：fetch → embed → topics --build → viz

## 示例

用户说："帮我拉取 JFM 的全部论文"
→ 执行 `explore fetch --issn 0022-1120 --name jfm`

用户说："帮我看看 acoustic metamaterial 领域有哪些研究"
→ 执行 `explore fetch --keyword "acoustic metamaterial" --name acoustic-metamaterial`

用户说："拉取某机构近 5 年高引论文"
→ 执行 `explore fetch --institution I123 --year-range 2020-2025 --min-citations 50 --name inst-highcite`

用户说："在 JFM 里搜 drag reduction"
→ 执行 `explore search --name jfm "drag reduction"`

用户说："用关键词搜索 JFM 中的 turbulence"
→ 执行 `explore search --name jfm "turbulence" --mode keyword`

用户说："更新 JFM 探索库"
→ 执行 `explore fetch --issn 0022-1120 --name jfm --incremental`

用户说："我有哪些探索库"
→ 执行 `explore list`（或 `explore info`）

### 导入本地 metadata-only 论文集

当用户手头有一批只有 `title / abstract / authors / download_url` 的记录时，不要强行并入主库；优先创建独立 explore 库。

```bash
# 一次性导入本地 metadata 文件，并自动构建 explore.db + embedding
scholaraio explore import --name <名称> --file <records.csv|json|jsonl|tsv>

# 增量追加（按 stable paper_id 去重）
scholaraio explore import --name <名称> --file <records.csv> --incremental

# 只写 papers.jsonl，稍后再单独建 embedding
scholaraio explore import --name <名称> --file <records.csv> --no-embed
scholaraio explore embed --name <名称>
```

补充规则：
- 如果源文件放在 `data/inbox/` 下，`explore import` 成功后会自动删除该源文件，避免重复处理
- 如果源文件在库外其他位置，不会擅自删除

兼容字段：
- 必需：`title`
- 推荐：`abstract`、`authors`、`year`、`doi`、`download_url`
- 常见别名也可用：`paper_title` / `summary` / `author_names` / `url` / `pdf_url` 等

导入后的数据结构：
- `data/explore/<name>/papers.jsonl`
- `data/explore/<name>/explore.db`
- `data/explore/<name>/faiss.index`
- `data/explore/<name>/faiss_ids.json`

适用场景：
- 用户有大批 metadata-only 论文，不想污染主库
- 用户想保留下载链接，供后续人工挑选
- 用户想让这些记录和主库一起搜索，用来碰撞新想法

### 和主库一起检索

当用户明确想把 explore 库和主库一起检索时，用联邦搜索：

```bash
# 主库 + 某个 explore 库
scholaraio fsearch "<查询词>" --scope main,explore:<名称>

# 主库 + 所有 explore 库
scholaraio fsearch "<查询词>" --scope main,explore:*
```

联邦搜索的用途：
- 看某个 idea 在“已入库核心论文”和“外部候选论文”之间怎么碰撞
- 快速发现 explore 里哪些结果已经在主库中存在
- 在不把 metadata-only 记录并入主库的前提下，扩大检索面
