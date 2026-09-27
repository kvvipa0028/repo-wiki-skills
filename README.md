# Repo Wiki Skills

面向代码仓库的 Wiki 生成技能，当前版本 **7.1.0**。

先阅读并分析工程，再按模块规划目录，生成带源码依据的中文 Wiki。每个模块包含 Mermaid 调用关系图和调用时序图，并按模块分文件夹保存。

## 核心流程

```text
inventory → read → analyze → plan → 正文与图 → render → checkpoint → scope-review → finish
```

- 全工程阅读记录绑定文件版本与实际读取行段；抽样、AST 摘要不能冒充全文阅读。
- 独立能力逐项映射到正文问题与章节，防止只有主链路的概述。
- 每个模块有独立文件夹、调用图和时序图；支持领域与子模块嵌套。
- 图表必须实际渲染；复核记录核对正文摘录、源码行段与引用。
- 阶段历史和已提交问题保留，不能通过清空问题或批量补 pass 宣称完成。

这些检查验证记录、版本和结构，不能自动证明自然语言准确、调用语义正确或能力发现完整。仍需生成者实际阅读源码并复核。

## 安装

将本仓库的整个 `repo-wiki/` 文件夹放入工具的技能目录，不要只复制 SKILL.md。常见位置：

| 工具 | 技能目录 |
|---|---|
| Codex | `~/.codex/skills/repo-wiki/` |
| Claude Code | `~/.claude/skills/repo-wiki/` |
| 已配置共享技能根的工具 | `~/.agents/skills/repo-wiki/` |

如已有同名技能，请先备份。安装后在新会话中加载技能，避免沿用旧版缓存。其他工具可读取 SKILL.md，或按其技能发现机制配置目录。

## 使用

向支持技能的助手提出请求，例如：

> 使用 repo-wiki 完整阅读并分析当前工程，按模块规划目录后生成中文 Wiki。每个模块单独放在文件夹中，包含调用关系图和时序图，不省略独立能力与失败路径。

详细说明：

- [技能入口](repo-wiki/SKILL.md)
- [阅读与分析](repo-wiki/references/preparation.md)
- [模块与文件夹规划](repo-wiki/references/planning.md)
- [正文标准](repo-wiki/references/writing.md)
- [调用图与时序图](repo-wiki/references/diagrams.md)
- [状态格式、命令与迁移](repo-wiki/references/state.md)
- [质量复核](repo-wiki/references/quality.md)

典型产物布局：

```text
wiki/
├── README.md
├── REPORT.md
├── content/
│   ├── _overview/
│   ├── _flows/
│   ├── scheduler/
│   │   ├── README.md
│   │   └── calls.md
│   └── generator/
│       ├── README.md
│       └── publishing.md
└── _meta/
```

## 环境与测试

校验脚本需要 Python 3.9+，使用标准库。图表实际渲染还需要 Mermaid CLI 的 `mmdc` 命令及可用浏览器依赖。缺少渲染环境时可以继续撰写，但不能通过完整交付验收。

在本仓库根目录执行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s repo-wiki/tests -v
python3 repo-wiki/scripts/wiki_check.py --help
```

测试中的 renderer test double 用来测试校验流程，不等于真实 Mermaid 语法验证。实际生成 Wiki 时仍须执行 `render`。

## 发布范围

本仓库仅包含通用技能说明、脚本、合成测试用例与使用文档，不包含被分析工程的源码、生成 Wiki、会话日志、数据库、个人配置或本机缓存。实际使用产生的 `_meta/` 记录可能涉及被分析仓库的内容，发布生成的 Wiki 时应另行审查。
