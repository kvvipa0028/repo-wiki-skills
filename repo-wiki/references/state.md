# v7 工作状态与验收

Python 3.9+ 标准库；实际图表渲染还需要本机 `mmdc`（Mermaid CLI）及其浏览器依赖。路径均为实际路径，不运行示例占位参数。输出为普通 Markdown。生成过程按单写者执行状态命令，不能多个进程同时改台账。

## 命令顺序

SKILL、REPO、WIKI 由执行者设为实际绝对路径：

```bash
mkdir -p "$WIKI/_meta"
python3 "$SKILL/scripts/wiki_check.py" inventory --repo "$REPO" --wiki "$WIKI" --root . > "$WIKI/_meta/inventory.json"
# 逐文件、逐段实际阅读输出，再记发现；不能把输出丢弃后批量标 read。
python3 "$SKILL/scripts/wiki_check.py" read --repo "$REPO" --wiki "$WIKI" --source src/counter.py --start-line 1 --end-line 100
# 当前版本所有文件读完，写 overview.md 和 analysis-review.json 后：
python3 "$SKILL/scripts/wiki_check.py" analyze --repo "$REPO" --wiki "$WIKI" --review-file "$WIKI/_meta/analysis-review.json"
# 整体目录 planning.md 和 plan.json 完整后：
python3 "$SKILL/scripts/wiki_check.py" plan --repo "$REPO" --wiki "$WIKI"
# 此后才写正文，逐页完成实际复核：
python3 "$SKILL/scripts/wiki_check.py" render --repo "$REPO" --wiki "$WIKI" --page content/counter/README.md
python3 "$SKILL/scripts/wiki_check.py" check --repo "$REPO" --wiki "$WIKI" --page content/counter/README.md
python3 "$SKILL/scripts/wiki_check.py" checkpoint --repo "$REPO" --wiki "$WIKI" --page content/counter/README.md --review-file "$WIKI/_meta/reviews/counter.json"
python3 "$SKILL/scripts/wiki_check.py" status --repo "$REPO" --wiki "$WIKI"
# 全部页面完成，含导航/报告里的辅助图，做全量渲染与范围复核：
python3 "$SKILL/scripts/wiki_check.py" render --repo "$REPO" --wiki "$WIKI"
python3 "$SKILL/scripts/wiki_check.py" scope-review --repo "$REPO" --wiki "$WIKI" --review-file "$WIKI/_meta/reviews/scope.json"
python3 "$SKILL/scripts/wiki_check.py" finish --repo "$REPO" --wiki "$WIKI"
```

`read` 范围必须有效，不会截断到 EOF；省略范围读取全文。记录只证明源码被工具展示，不证明已理解。每次阅读后保留实际发现、剩余未读范围，输出截断时重读较小片段。`render --renderer /实际路径/mmdc` 可指定 executable，不接收 shell 命令。复用完全相同图内容和有效 SVG 的记录；缺工具、错误或超时均不算 pass。

## 阅读与分析

`analysis-review.json` 使用 `schema_version: 7`，其余 scope/files/modules 结构见 [前期流程](preparation.md)。文本 `status=read` 必须 `method=full_text` 且有当前 hash 的完整行段记录；抽样、AST、仅头部均不能通过。

二进制语义输入（例如 SQLite）使用 `method=structured`，在该文件记录中添加：

```json
{"inspection": {
  "method": "实际只读查询方法、涉及 schema/表及消费者的说明",
  "source_sha256": "所检查源文件的实际 SHA256",
  "report": "_meta/reading/project-db.md",
  "report_sha256": "真实查询结果与分析报告的实际 SHA256"
}}
```

报告记录实际方法、范围、发现与未能检查的内容；有缺口保留 blocked。不要保存凭据或无关数据。文本源码不能走 structured 来规避全文阅读。nonsemantic 需 category 与理由，源码/配置/数据库不允许直接归入无语义。字节完全一致的重复副本可填 category=duplicate、duplicate_of=实际已读文件路径；脚本核实 hash 相同且原件已读，不能仅凭文件名相同跳过。

分析模块除 id/name/paths/summary 外，必须有全部独立能力 `capabilities`。每项包括全局唯一 id、name、description、source_anchors。source_anchors 为：

```json
[{"path":"src/counter.py","start":12,"end":18,"quote":"该范围内逐字一致的关键源码片段"}]
```

不是让执行者使用上述虚构行号；必须从本仓源码取得。二进制能力的代码论据可引用实际解析器/消费者，二进制数据本身另见绑定的 inspection 报告。

## 完整目录 plan.json

顶层字段：`schema_version:7`、baseline、scope、coverage、modules、pages。

- scope：request、roots、user_exclusions，与分析完全一致。roots 为仓库相对路径，无 glob；exclusions 仅记录真实用户排除及原因。
- coverage：每项 area、paths、pages、status、gaps；status 为 planned/partial/blocked/complete/excluded。complete 必须有页面且无 gaps；excluded 需实际用户排除。
- pages：path、title、kind、objective、parent、questions、sections、sources、watch、cards、depends_on、next。kind 为 overview/design/flow/reference/guide；parent/depends_on 不能形成环。sections 使用完整 Markdown 标题，如 `## 更新机制`；questions 为实际读者问题，不预设源码不存在的能力。
- modules：id/name/paths 与分析全部模块一致，directory 为该模块独有的 Wiki 相对文件夹，pages 均须在此目录内；每个模块有两类独立图位置及全部能力的映射。directory 位于 content/ 下，不允许共享、越界、别名链接或包含 ..；模块 pages 不能共用同一文件。公共页位置见 [规划布局](planning.md)。

模块计划形状（填写真实内容，不照抄虚构 counter）：

```json
{
  "id":"counter","name":"计数器","paths":["src/counter.py"],
  "directory":"content/counter",
  "pages":["content/counter/README.md"],
  "diagrams":{
    "call":{"page":"content/counter/README.md","section":"## 调用关系"},
    "sequence":{"page":"content/counter/README.md","section":"## 更新时序"}
  },
  "capabilities":[{
    "id":"counter-add","page":"content/counter/README.md","section":"## 更新机制",
    "question":"数值更新与通知按什么顺序发生？",
    "diagram_coverage":{
      "call":"具体说明该能力对应的入口、内部调用、通知绑定",
      "sequence":"具体说明对应场景、状态提交和通知先后"
    }
  }]
}
```

capability 的 section/question 必须在负责页任务内，每项能力有独立解释标题。不能漏掉分析清单中的能力。每个模块的 call/sequence 位置必须唯一，不能用全局图抵算。两图是最低要求，复杂模块应补图。正文完成前 coverage 保持真实进度；不能用页数等于计划数证明独立能力已覆盖。

## 页面 review

沿用六项 checks：task_assumptions、source_fidelity、explanation、examples、diagrams、scope_boundaries，每项含 status/evidence。只有 examples 和不承担必需图的辅助页 diagrams 可有依据地 not_applicable；其他需要实际 pass。不能从模板/长度/标题自动生成判断。

answers 一对一覆盖 questions，每项字段：

```json
{
 "question":"与计划相同的真实问题",
 "section":"## 实际答案标题",
 "body_quote":"该标题下确实存在的正文摘录",
 "conclusion":"该问题独有的实际核对结果，不能与其他问题复制相同结论",
 "sources":["src/counter.py"],
 "source_anchors":[{"path":"src/counter.py","start":12,"end":18,"quote":"实际源码片段"}]
}
```

sources 必须在页面输入快照内；anchors 必须引用这些文件并匹配行段原文。摘录匹配不代表论据能支持结论，这一判断仍须实际审阅。源码链接文字若标了行号，必须与链接 target 一致；不自动修复为文件头/首个 token。

`diagram_reviews` 为该页承担的每个模块必需图各记一项：

- 公共字段：module（ID）、kind（call/sequence）、section、status（pass）、source_anchors。
- call：entry_and_binding（入口与实际绑定）、edge_meaning（关键边含义）、non_edges（哪些时序/构造/数据关系不能画成调用）。
- sequence：scenario（具体触发场景）、ordering_and_state（调用顺序及状态变化）、failure_and_exit（失败出口与不执行的后续动作，无失败时说明源码依据）。

不是逐边 JSON；每条边都须核对，记录关键判断和高风险边界。渲染与语义结果分开，二者均满足才能 checkpoint。

`open_findings` 非空时拒绝验收。已经提交过的问题不能通过改成空列表消失；重审的 `resolutions` 每项含 finding（与原问题相同字符串）、change（实际修正/重新核验）、source_anchors。历史问题即使已经解决，也保留解决记录以便之后复核。

## 全范围 review

字段：

- areas：每项 area/pages/assessment，对应全部未 excluded 的 coverage。
- discovery_sources：实际仓库发现依据文件，不是生成 Wiki。
- cross_page_checks：具体的跨页概念、绑定、状态、引用与导航核对。
- capability_checks：每个 capability 一项 `{id,status:"pass",assessment,source_anchors}`，从真实入口反查机制与使用说明是否充分，不能只复述 plan。
- open_findings/resolutions：规则同页面复核。

scope-review 仅在全部页面通过后记录，绑定计划、全工程输入、页面检查点和发现依据。修改正文、来源、阅读分析或目录后必须重审受影响内容。

## 阶段历史、增量与旧格式

工具追加 `_meta/history.jsonl`，保留阅读事件、分析/规划/复核的输入、成功/失败和历史阶段内容。记录的是工具观察时间，不是源码 mtime 或外部程序的起始时间。hash 链能检查缺行/损坏，不是防恶意改写的安全边界；程序也不能拦截其他进程随意写正文。

旧产物先保留正文，通过 `analyze --reuse-existing --reason "实际原因"` 记录旧正文基线及旧阶段快照，再规划完整 v7 目录。v7.1 沿用 schema_version=7，新增必填的模块 directory；原有平铺页面需规划到模块文件夹，修正导航/相对源码链接、pages/coverage/depends_on/parent、能力与图位置及 review，重新验收受影响页面。迁移完成不能宣称原生成过程已遵循新要求。禁止重置历史、手造读源/渲染记录、直接改 state/workflow/scope-review 或修改验收器绕过失败。

源码变更后分段读新版本、更新实际发现，重新 analyze 与 plan。未变且有记录的源码可复用。人工正文修改先看 diff、保留有效内容，实际复核后 checkpoint 可加 --accept-edits；此参数不是内容认证。先验收依赖页，再验收依赖它的页面。

旧 schema 可做兼容的 check/status/checkpoint，finish 只接受完整 v7。不能只改版本号或批量给旧内容盖章。`ready_for_delivery=true` 表示机械条件与当前复核记录齐全，不保证自然语言正确、模块发现毫无遗漏、运行验证通过，也不能证明与某参考 Wiki 同质量。交付报告必须说明这些边界。
