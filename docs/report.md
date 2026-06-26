# loop-iteration 阶段性汇报

> self-iterate：一个 Claude-Code 原生的 agent harness 自迭代循环。
> 用户只需提供一份 `.self-iterate/<goal>/` 评测规格，循环就会自动改写 agent 的
> prompt/skills/tools，直到一个可验证的目标达成。

## 一、阶段性成果

### 核心能力
- **状态机驱动的自迭代循环**：`baseline → maker/checker 轮次 → goal-check → report`，
  全程以 `.self-iterate/runs/<run_id>/state.json` 推进，CLI 强制阶段顺序与 `max_rounds` 上限，
  可中断恢复、幂等。无需外部 ralph/autopilot。
- **maker/checker 分离**：maker（`harness-rewriter`）改 harness，checker（`goal-checker`）
  与可选的 `quality-judge` 用可验证命令打分——做的人永远不给自己判「完成」。
- **多适配器类型**（`agent.type` in `goal.yaml`）：
  - `claude-p`（默认，零代码覆盖所有 Claude-Code 原生 agent）
  - `command`（有 CLI 的 agent）
  - `python-import`（进程内 agent，~5 行 shim）
  - `custom` + drop-in `run_case.py`（任意协议兜底）
- **质量护栏**：程序化 `no_overfit` 维度（非 LLM，可靠）+ 可选 LLM `quality.md`
  对 harness 文件本身打分；质量回归低于基线的轮次不能成为 winner、不能判定目标达成。
- **实时 dashboard**：5 面板 SPA（进度 / 概览 / 质量 / cases / diff），启动时自动开浏览器。

### 工程质量
- **178 个测试全绿**，覆盖 scoring / gates / judge / adapter / case_runner / goal_check /
  state / dashboard / quality / 多适配器集成 / golden-round 端到端。
- **hermetic**：每轮在 detached git worktree 中改 harness，源仓库全程字节不变；
  worktree 崩溃安全清理。
- **out-of-the-box**：`setup` 自动解析 agent 自己的 venv（`agent.venv`）、自动加载 `.env`，
  venv-less agent 自动 bootstrap。

### 已 dogfood 验证
- toy agent（`examples/toy`）：1 轮即把模糊指令锐化为「恰好一个裸词」，composite 1.0，
  `goal_check` exit 0，源仓库未动。
- 已在真实 in-process / 本地服务型 agent 上验证适配器泛化（内部 dogfood）。

### 发布
- 已 plugin-ization：`.claude-plugin/plugin.json` + `marketplace.json`，作为 Claude Code 插件分发。
- 已发布到 GitHub：`https://github.com/wellenzheng/loop-iteration`。
- 发布前完成敏感信息清理：移除本机绝对路径、取消跟踪 `.loop/` 运行历史、
  匿名化内部项目引用、内部设计文档（`docs/superpowers/`）不进公开仓库。

## 二、Quick Start

### 1. 安装插件
要求 Python 3.11+。在 Claude Code 中：
```
/plugin marketplace add wellenzheng/loop-iteration
/plugin install self-iterate@loop-iteration
```

### 2. 跑通 toy 示例（5 分钟验证）
```bash
git clone https://github.com/wellenzheng/loop-iteration
cd loop-iteration/examples/toy
```
在 Claude Code 中打开 `examples/toy` 目录，运行：
```
/self-iterate toward toy-basic
```
循环会改写 `CLAUDE.md` 直到「答单词题恰好输出一个裸词」，目标达成后自动停止，
dashboard 实时展示每轮分数与 harness diff。

### 3. 用在你自己的 agent 上
在你的 agent 仓库根目录运行：
```
/self-iterate setup
```
交互式生成评测规格（你逐项确认）：
```
.self-iterate/<goal>/
  goal.yaml     # 阈值 / 权重 / 回归策略 / 可选 agent:/harness: 覆盖
  cases.json    # 你的 QA 集
  gates.py      # 程序化 gate（GATES = {name: fn}）
  rubric.md     # LLM 评分维度
  quality.md    # 可选：对 harness 文件本身打分的护栏
  # 可选 run_case.py — 非 Claude-CLI agent 的兜底
```
然后启动循环：
```
/self-iterate toward <goal>
```
`done` 是一个命令退出码，不是主观判断——`goal_check` exit 0 即目标达成。

## 三、仓库结构
```
.claude-plugin/        插件清单
skills/                /self-iterate + /self-iterate-setup
agents/                maker / checker / quality-judge 子代理
scripts/loop_iter/     Python CLI（评分 / gate / judge / 状态机 / dashboard）
examples/toy/          最小可跑示例
tests/                 178 个测试
```
