<div align="center">

<!-- TODO: 有 logo 后替换 -->
<!-- <img src="docs/assets/logo.png" width="200" alt="ScholarAIO Logo"> -->

# ScholarAIO

**Scholar All-In-One — 为 AI agent 打造的科研知识基础设施。**

[English](README.md) | [中文](README_CN.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![MCP Tools](https://img.shields.io/badge/MCP_Tools-31-green.svg)](scholaraio/mcp_server.py)
[![Claude Code Skills](https://img.shields.io/badge/Claude_Code_Skills-22-purple.svg)](.claude/skills/)

</div>

---

你的 coding agent 已经能读代码、写代码、跑实验。ScholarAIO 给它加上一个结构化的论文知识库——于是同一个 agent，既能帮你写代码，也能检索文献、交叉验证结果、复现论文方法、起草文稿。一个终端，一个 agent，完成科研全流程。

<!-- TODO: 加 demo GIF -->
<!-- <div align="center">
  <img src="docs/assets/demo.gif" width="700" alt="ScholarAIO Demo">
</div> -->

## 快速开始

```bash
# 1. 安装
git clone https://github.com/ZimoLiao/scholaraio.git && cd scholaraio
pip install -e ".[full]"

# 2. 配置
cp config.local.example.yaml config.local.yaml
# 填入 API key（均为可选，见下方配置说明）

# 3. 启动
claude    # 在项目目录启动 Claude Code，开始对话
```

> 也可以直接用 CLI：`scholaraio search "你的主题"` | MCP 服务器：`scholaraio-mcp`

## 核心功能

|  | 功能 | 说明 |
|--|------|------|
| **PDF 解析** | 深度结构提取 | [MinerU](https://github.com/opendatalab/MinerU) → Markdown，图表、公式完整保留。支持期刊论文、学位论文、技术报告等多种文档类型 |
| **融合检索** | 关键词 + 语义 | FTS5 + Qwen3 嵌入 + FAISS → RRF 排序融合 |
| **主题发现** | 自动聚类 | BERTopic + 6 种交互式 HTML 可视化——同时支持主库和 explore 数据集 |
| **文献探索** | 多维度发现 | OpenAlex 9 维过滤（期刊、概念、作者、机构、关键词、来源类型、年份、引用量、文献类型）→ 向量化 → 聚类 → 检索 |
| **引用图谱** | 参考文献与影响力 | 正向/反向引用、共同引用分析 |
| **分层阅读** | 按需加载 | L1 元数据 → L2 摘要 → L3 结论 → L4 全文 |
| **多源导入** | 带上你的文献库 | Endnote XML/RIS、Zotero（API + SQLite，支持 collection → workspace 映射）、PDF、Markdown——更多来源持续接入 |
| **工作区** | 按项目组织 | 论文子集管理，支持范围内检索和 BibTeX 导出 |
| **学术写作** | AI 辅助撰写 | 文献综述、论文章节、引用验证、审稿回复、研究空白分析——每条引用可追溯至你自己的文献库 |
| **MCP 服务器** | 31 个工具 | Claude Desktop、Cursor 等 MCP 客户端均可调用 |

## 不只是论文管理

ScholarAIO 把 PDF 解析成干净的 Markdown，LaTeX 公式准确，图片附件完整。这意味着你的 coding agent 不只能"读"论文，还能：

- **复现方法** — 读算法描述，写出实现，直接运行
- **验证结论** — 从图表中提取数据，独立计算，交叉核对
- **推导公式** — 接着论文的推导继续展开，用数值计算验证边界条件
- **可视化结果** — 把论文数据和你自己的实验结果画在一起对比

知识库是基础设施，agent 在此之上能做什么，取决于你的想象力。

## 兼容你的 Agent

ScholarAIO 的设计目标是 **agent 无关**。目前已为多种 agent 和 IDE 提供开箱即用的配置：

| Agent / IDE | 集成方式 | 配置文件 |
|-------------|---------|---------|
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | 完整 skills + 指令 | `CLAUDE.md` + `.claude/skills/` |
| [Cursor](https://cursor.sh) | 指令 wrapper | `.cursorrules` |
| [Windsurf](https://codeium.com/windsurf) | 指令 wrapper | `.windsurfrules` |
| [Cline](https://github.com/cline/cline) | 指令 + skills | `.clinerules` + `.claude/skills/` |
| [GitHub Copilot](https://github.com/features/copilot) | 指令 wrapper | `.github/copilot-instructions.md` |
| [Codex](https://openai.com/codex) / OpenClaw | 完整指令 + skills | `AGENTS.md` + `.agents/skills/` |

**MCP 服务器**（`scholaraio-mcp`，31 个工具）适用于任何 MCP 兼容客户端。Skills 遵循开放的 [AgentSkills.io](https://agentskills.io) 标准——`.agents/skills/` 是 `.claude/skills/` 的符号链接，方便跨 agent 发现。

**从现有工具迁移？** 支持从 Endnote（XML/RIS）和 Zotero（Web API 或本地 SQLite）直接导入——PDF、元数据、引用关系一并迁入。更多导入源持续开发中。

## 工作流程

```
PDF → MinerU → 结构化 Markdown（图表 + LaTeX 公式保留）
                    ↓
          元数据提取（正则 + LLM 交叉验证）
          API 补全（Crossref / Semantic Scholar / OpenAlex）
                    ↓
          DOI 去重 → data/papers/<Author-Year-Title>/
                    ↓
      ┌─────────────┼─────────────┐
   FTS5 索引      FAISS 向量     BERTopic
   （关键词）     （语义）       （聚类）
      └─────────────┼─────────────┘
                    ↓
        你的 agent（Claude Code / Cursor / CLI / MCP / ...）
```

## 配置说明

主配置：`config.yaml`（进 git）。敏感信息：`config.local.yaml`（不进 git）。

| Key | 用途 | 获取方式 |
|-----|------|---------|
| `DEEPSEEK_API_KEY` | LLM——元数据提取、内容富化、学术讨论 | [DeepSeek](https://platform.deepseek.com/)（默认）或任意 OpenAI 兼容 API |
| `MINERU_API_KEY` | PDF → 结构化 Markdown | [mineru.net](https://mineru.net/apiManage/token) 免费申请，也可[本地部署](https://github.com/opendatalab/MinerU) |

> **均为可选。** 没有 LLM key：降级为纯正则提取。没有 MinerU key：直接将 `.md` 放入 `data/inbox/`。

嵌入模型（Qwen3-Embedding-0.6B，约 1.2 GB）首次使用时自动下载。默认从 ModelScope 下载（国内无需代理），海外用户设置 `embed.source: huggingface`。

完整配置参考 → [`config.yaml`](config.yaml)

## 三种使用方式

| 模式 | 适用场景 | 命令 |
|------|---------|------|
| **Agent**（推荐） | 完整科研工作流——对话式交互 | 项目目录下运行 `claude` 或你喜欢的 agent |
| **MCP 服务器** | Claude Desktop / Cursor 等 MCP 客户端 | `scholaraio-mcp` |
| **CLI** | 脚本、快速查询 | `scholaraio --help` |

<details>
<summary><strong>CLI 命令一览</strong></summary>

**检索与阅读**
```
scholaraio search QUERY       关键词检索（FTS5）
scholaraio vsearch QUERY      语义向量检索
scholaraio usearch QUERY      融合检索（关键词 + 语义）
scholaraio search-author NAME 按作者搜索
scholaraio top-cited          按引用量排序
scholaraio show PAPER         查看论文内容（L1-L4）
```

**入库与富化**
```
scholaraio pipeline PRESET    运行入库流水线（full|ingest|enrich|reindex）
scholaraio index              构建 FTS5 检索索引
scholaraio embed              生成语义向量
scholaraio enrich-toc         提取目录结构
scholaraio enrich-l3          提取结论段
scholaraio backfill-abstract  补全缺失摘要
scholaraio refetch            重新查询引用量
```

**引用图谱**
```
scholaraio refs PAPER         查看参考文献
scholaraio citing PAPER       查看被引论文
scholaraio shared-refs A B    共同参考文献分析
```

**探索与主题**
```
scholaraio explore fetch ...  文献探索（OpenAlex 多维过滤）
scholaraio explore search ... 探索库内检索
scholaraio topics             BERTopic 主题建模
```

**导入与导出**
```
scholaraio import-endnote     从 Endnote 导入
scholaraio import-zotero      从 Zotero 导入
scholaraio attach-pdf         为已有论文补充 PDF
scholaraio export bibtex      导出 BibTeX
scholaraio ws init NAME       创建工作区
scholaraio ws add NAME PAPER  添加论文到工作区
scholaraio ws search NAME Q   工作区内检索
```

**维护**
```
scholaraio audit              数据质量审计
scholaraio repair             修复元数据
scholaraio rename             标准化目录名
scholaraio migrate-dirs       迁移旧版目录结构
scholaraio setup              环境配置向导
scholaraio metrics            查看 LLM 用量统计
```

</details>

## 项目结构

```
scholaraio/          # Python 包——CLI、MCP 服务器、所有核心模块
  ingest/            #   PDF 解析 + 元数据提取流水线
  sources/           #   数据源适配（local / Endnote / Zotero）

.claude/skills/      # 22 个 agent skills（AgentSkills.io 格式）
.agents/skills/      # ↑ 符号链接，方便跨 agent 发现
data/papers/         # 你的论文库（不进 git）
data/inbox/          # 放入 PDF 即可入库
```

完整模块参考 → [`CLAUDE.md`](CLAUDE.md) 或 [`AGENTS.md`](AGENTS.md)

## 引用

如果 ScholarAIO 对你的研究有帮助，欢迎引用：

```bibtex
@software{scholaraio,
  author = {Liao, Zi-Mo},
  title = {ScholarAIO: AI-Native Research Terminal},
  year = {2026},
  url = {https://github.com/ZimoLiao/scholaraio},
  license = {MIT}
}
```

## 许可证

[MIT](LICENSE) © 2026 Zi-Mo Liao
