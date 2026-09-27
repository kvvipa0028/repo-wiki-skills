# 先阅读、分析和规划，再写正文

这是生成顺序的硬要求。首次生成不允许边读少数模块边写样页，再从已有页面补出目录。全工程阅读可以分批进行，不要求把全部原文同时放进上下文；每批保存发现和未读清单。当前输入未完整读完、整体分析未完成或模块目录缺项时，继续研究，不能进入正文阶段。

## 1. 文件清单与完整阅读

```bash
mkdir -p "$WIKI/_meta"
python3 "$SKILL/scripts/wiki_check.py" inventory --repo "$REPO" --wiki "$WIKI" --root . > "$WIKI/_meta/inventory.json"
```

完整工程默认 root 为 `.`；用户明确要求子系统才缩小范围。可重复 --root。命令输出真实文件内容散列，不代表阅读完成；不要把库存自动转换成全部 read。它跳过 `.git`、`__pycache__`、`node_modules`、`.venv`、`venv`、`.cache` 和当前 Wiki 输出；仍应核对这些目录中是否混入用户要求的独立源码，若有则明确调整分析范围，不能依赖跳过规则隐去能力。已初始化 submodule 的源码要纳入，未初始化/外部缺失依赖记录阻塞与范围边界。

完整阅读范围内源码（含私有实现与不在主调用链上的独立库）、公开接口、配置/数据模型、代码生成、构建选择、测试与相关设计资料。长文件按行段接续，保留进度，不能只读开头或符号摘要就标 read。数据库采用只读 schema/相关表与消费者核对；二进制不当作文本读，但不能因其是 SQLite 就排除配置语义。实际重复构建物、旧 Wiki 副本、无语义缓存可以逐项说明 nonsemantic；源码、配置、未使用库不属于该分类。真实秘密材料不进入正文或证据输出。

大清单先保存为文件，按模块/目录分批阅读；工具输出截断不代表清单结束。长任务可把各批实际阅读记录存到 `_meta/`，最后机械合并并检查遗漏，但不能把 inventory 自动转换为 read 或用模板批量编造发现。

阅读要回答：工程目标和入口是什么，各能力如何实现，模块之间怎样调用/传数据，哪些 callback/注册/动态派发决定真实路径，配置/构建如何选择实现，测试说明哪些边界。保存 `_meta/overview.md` 的全工程分析；模块事实卡可同时形成。每条记录能定位已经读过的内容与实际发现，不能只写“已看”。

使用 `read --source <仓库相对文件> --start-line 1 --end-line N` 分段读取，逐批实际阅读显示的内容。省略范围则读取全文；工具输出截断时继续用更小范围读完。命令把当前 hash 与已展示行段追加到历史，analyze 要求所有文本行的当前版本记录齐全。别的工具读取若没有可验证记录，迁移时重新分段读取，不补造历史。

SQLite 等二进制采用只读 schema/数据/消费者分析并保留实际报告；`method=structured` 格式见 state.md。文本源码的 AST 提取不能用此模式放行。

## 2. 阅读记录与模块分析

将实际阅读记录写入 `_meta/analysis-review.json`。以下仅展示形状；files 必须与 inventory 的全部文件一对一对应，modules 包含分析后发现的全部模块。

```json
{
  "schema_version": 7,
  "scope": {"request": "完整覆盖整个工程", "roots": ["."], "user_exclusions": []},
  "modules": [
    {"id": "counter", "name": "计数模块", "paths": ["src/counter.py"],
     "summary": "实际核对的职责、入口、关键对象、调用关系、配置与边界；不能照抄本示例",
     "capabilities": [{"id": "counter-add", "name": "计数更新", "description": "实际更新与通知机制",
       "source_anchors": [{"path": "src/counter.py", "start": 1, "end": 1, "quote": "替换为真实源码摘录及行号"}]}]}
  ],
  "files": [
    {"path": "src/counter.py", "status": "read", "method": "full_text", "modules": ["counter"],
     "evidence": "实际完整阅读的范围和结论，例如构造、add/reset、提交与通知顺序及消费者位置"}
  ],
  "open_findings": []
}
```

files.status：

- `read`：实际阅读完成；modules 关联所属模块，evidence 记阅读范围与发现。空文件也可记录为空，不能伪造行号。
- `nonsemantic`：有依据的无语义/重复物；category 为 cache/build_output/duplicate/asset，modules 为空，evidence 说明类别与原因。源码/配置/数据库不能因此跳过；秘密材料不得通过 read 展示，应保留明确读取限制。
- `user_excluded`：必须匹配 scope.user_exclusions 的真实用户排除，modules 为空。
- 未读、无法读取、缺依赖而无法完成模块分析：保留 `blocked` 或待办，不能通过 analyze。已能独立开展的模块研究继续进行，不能宣称整仓分析完成。

模块 paths 为 scope 内真实路径，可重叠用于共享源码；不把所有独立库合并成一个“工具库”来省略模块图。跨模块文件可关联多个模块。全部模块必须有实际 read 的输入支撑。symlink 要记录链接性质并把实际目标纳入明确授权的范围；脚本不会将链接目标自动视为已读。

```bash
python3 "$SKILL/scripts/wiki_check.py" analyze --repo "$REPO" --wiki "$WIKI" --review-file "$WIKI/_meta/analysis-review.json"
```

脚本保存 `_meta/analysis.json`，绑定全部输入散列、阅读/模块分析记录及 overview。初次生成此时若已有正文会拒绝。既有 Wiki 迁移/增量使用 `--reuse-existing --reason "具体原因"` 保留旧正文基线，不能用此选项掩盖本轮跳过前期工作。每次分析与规划均追加保留前后阶段记录。

## 3. 整体目录确认

分析通过后，再把全部模块展开为完整分层目录，在 `_meta/planning.md` 说明分类依据、完整目录树、模块到页面的映射和跨模块主题。写好 v7 plan：scope 与 analysis 完全一致，modules 的 id/name/paths 一致；每个模块都有负责页面及各自调用关系图、调用时序图的位置。分析的每个 capability 都要映射到独立解释标题、读者问题和两类图的覆盖说明。目录不是固定篇数模板，也不能只列一期样页而漏掉剩余模块。

```bash
python3 "$SKILL/scripts/wiki_check.py" plan --repo "$REPO" --wiki "$WIKI"
```

成功保存 `_meta/workflow.json` 后才写读者正文，包括代表页、README 导航和 REPORT。首次目录确认前，正文不得相对分析时的基线新增/改写。后续任务结构或图位置变更，要先更新规划并重新 plan；单纯推进 coverage.status/gaps 或 page.next 不要求重做目录。

源文件新增/删除/变化或 overview 改动会使分析过期；补读变更，复用有记录且未变的阅读结果，重新 analyze 与 plan 后继续。目录只是可修订的整体基线，不是禁止发现新知识；新增模块需要先加入分析和规划，不能跳过该模块两类图。

这些检查只能证明记录齐全、对应版本及阶段检查点存在，不能证明模型真正读懂源码，也不能阻止任意外部写文件。执行者必须遵守顺序，人工核对阅读记录和模块粒度，不自动批量填 read/pass。
