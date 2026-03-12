---
name: citation-check
description: Verify citations in AI-generated or human-written text against the local knowledge base and external APIs. Catches hallucinated references, wrong metadata, and missing papers. Use when the user wants to check if citations are real and accurate.
---

# 引用验证

检查文本中的引用是否真实、准确，防止 AI 幻觉引用和元数据错误。

**重要背景**：AI 生成的学术文本中约 40% 的引用可能是幻觉（编造的论文、张冠李戴、元数据拼凑）。即使是人类写的文本也常有年份/期刊名错误。本 skill 的目标是在投稿前消灭所有引用问题。

## 前提

用户提供待检查的文本（粘贴、文件路径、或指定 workspace 中的草稿文件）。
如有 workspace，优先在工作区范围内验证。

## 执行逻辑

### 1. 提取引用

从文本中提取所有引用，识别格式：
- `(Author, Year)` / `Author (Year)` — 括号引用
- `\cite{key}` / `\citep{key}` / `\citet{key}` — LaTeX 引用
- `[N]` — 编号引用（需配合参考文献列表）

### 2. 逐条验证

对每条引用执行三层检查：

**Layer 1 — 本地库匹配**
```bash
scholaraio search-author "<Author>" --top 5
scholaraio usearch "<关键词 from title>" --top 5
```
在本地库中找到匹配论文后，核对：作者名、年份、标题、期刊是否一致。

**Layer 2 — DOI/元数据核验**
如果本地库有匹配，读取 meta.json 中的 DOI 和详细元数据交叉比对。
如果本地库无匹配，提醒用户——该引用不在工作区/知识库中。

**Layer 3 — 内容一致性**
对于关键引用（支撑核心论点的），加载 L2-L3 检查：
```bash
scholaraio show <dir_name> --layer 3
```
验证：文本中对该论文的描述是否与论文实际内容一致？是否存在过度解读或断章取义？

### 3. 输出报告

生成验证报告，每条引用标注状态：

| 状态 | 含义 |
|------|------|
| **VERIFIED** | 本地库有匹配，元数据一致 |
| **METADATA MISMATCH** | 找到论文但作者/年份/标题有出入 |
| **NOT IN LIBRARY** | 本地库中无此论文 |
| **CONTENT MISMATCH** | 论文内容与文中描述不符 |
| **SUSPICIOUS** | 无法验证，可能为幻觉引用 |

对每条问题引用给出具体修复建议。

## 常见问题模式

- **AI 幻觉引用**：作者名和年份拼凑出一篇不存在的论文——标记 SUSPICIOUS
- **张冠李戴**：引用了真实论文但描述的是另一篇的内容——标记 CONTENT MISMATCH
- **元数据错误**：年份差一年、期刊名拼错、一作搞错——标记 METADATA MISMATCH 并给出正确值
- **过度引用**：一个论点堆了 5+ 引用但大部分并不直接相关——建议精简

## 示例

用户说："帮我检查这段文字里的引用是否正确"
→ 提取引用，逐条在本地库中搜索验证，输出报告

用户说："检查 workspace/my-paper/introduction.md 里的引用"
→ 读取文件，提取引用，在工作区范围内验证
