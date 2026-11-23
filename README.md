# SkillScope

技能组合冲突诊断与阶段加载实验工具。

准备研究的问题：**为什么给 Agent 加了更多技能，任务反而可能做得更差？**

可以把 Skill 理解为工作指南。SkillScope 希望通过相同任务、不同指南组合的重复实验，找到值得进一步验证的退化组合，并尝试按工作阶段加载指南。

**当前 v0.5：支持冻结批次、真实库多文件技能对照、阶段加载、预算与中断核算、外部评分和诊断前提检查。自动组合缩减与策略学习尚未完成。**

[中文入门](docs/step-by-step.md) · [跑通真实任务](docs/first-real-run.md) · [试运行记录](docs/smoke-results.md) · [开发路线](docs/roadmap.md) · [原始研究设计](docs/design.md)

第三阶段已完成：[逐步操作与作用](docs/stage3-guide.md) · [执行前固定的方案](docs/stage3-protocol.md) · [结论与异常解释](docs/stage3-findings.md) · [原始数据及报告](artifacts/stage3-20261123/report.md)。

本轮主实验 143/144 次完成任务，唯一失败是反向加载的一次输出截断；没有观察到满足预先规则的稳定退化候选。含预检共 442 次实际模型调用、510,231 tokens；按固定高峰价上界估算约 USD 0.24075，并非账户账单。

后续已按[五步路线](docs/next-steps.md)开始执行：[40 次输出预算复核与多文件原型结果](docs/continuation-results.md)。反向配置在 1,024 tokens 下通过 3/5，在 2,048 下通过 5/5；这是待复核的预算敏感模式。导入型多文件原型已完成一次模型自主修复，外部隐藏测试 19/19；全部工程失败也已归档，不作为真实仓库效果证明。

已补齐[真实目录与首批真实库任务](docs/directory-and-calibration.md)。第一轮 4 次无技能运行均在阶段额度耗尽时停止，未执行最终隐藏评分；不能据此推断任务语义难度。[完整记录](artifacts/repo-calibration-20261123/report.json)与[阶段控制器修订方案](docs/phase-finish-protocol.md)分别保留。

随后两次工程协议验证也未进入最终评分，全部记录保留；该轮共 38 次请求，费用上界估算约 USD 0.03738。v4 改为控制器在阶段额度结束时自动切换并交接真实工具日志。

v4 已完成[真实 API 验证与独立校准](artifacts/controller-v4-20261123/report.json)：工程验证隐藏测试 9/9；新校准中注释题 2/2、反斜杠题 1/2，全部到达最终评分。共 50 次请求、204,116 tokens，费用上界估算约 USD 0.04703，工程样本不计入校准。

[首轮真实库技能对照已记录全部 36 项排期](docs/repo-skill-findings.md)：20 次通过、13 次功能失败、1 次格式失败、2 次环境中断。部分单技能本身表现较差，关键对照也有缺失评分，未达到预设组合退化候选标准。335 次请求尝试中 2 次响应与费用未知；已保存响应估算 USD 0.44175，另预留 USD 0.448512，保守合计约 USD 0.89026，不能当作实际账单。保留题没有模型调用或评分。

## 快速开始

需要 Python 3.12 或更高版本。以下为 Windows PowerShell 命令，在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" -c requirements-dev.lock
.\.venv\Scripts\python.exe -m skillscope check
.\.venv\Scripts\python.exe -m skillscope plan
.\.venv\Scripts\python.exe -m skillscope preview --condition scoped --stage investigate
.\.venv\Scripts\python.exe -m pytest -q
```

Linux/macOS 将 `.\.venv\Scripts\python.exe` 换为 `.venv/bin/python`。命令默认从当前目录的 `examples/experiment.json` 读取输入；其他位置请传 `--config /path/to/experiment.json`。

以上准备命令都不请求模型 API，也不需要密钥。`plan` 默认保存至 `results/plan.json`；如果文件已经存在，请通过 `--output results/plan-02.json` 指定新路径，保护旧计划。

命令行文本输出统一为 UTF-8，支持英文 Windows 系统及输出重定向。

## 第一个实验长什么样

示例只有 2 份技能指南、2 道小型代码修复任务，用于验证流程。它们不是已确认的冲突案例，也不足以支持统计结论。

| 分组 | 加载的指南 | 作用 |
| --- | --- | --- |
| `baseline` | 不加载 | 记录无技能时的表现 |
| `single-root-cause` | 仅根因调查，三个阶段均保留 | 观察单份指南的影响 |
| `single-minimal-fix` | 仅最小修改，三个阶段均保留 | 观察另一份指南的影响 |
| `all` | 两份指南，三个阶段均保留 | 后续与单份指南比较 |
| `scoped` | 调查阶段只加载根因调查；修改阶段只加载最小修改；验收阶段不加载技能 | 后续与全部加载比较 |

默认只选 `discovery` 中的 1 道任务：**1 道任务 × 5 组配置 × 3 次重复 = 15 次计划运行**。每次运行设调查、修改、验收三个阶段。15 是排期数量，不是模型调用次数或成功次数。

另一道任务在 `holdout`，留作后续验收；只有显式传入 `--split holdout` 才会进入计划。教学示例公开存放，后续正式评测需要新增未参与调试的任务，并在固定策略后再使用。

`--seed` 只控制计划运行顺序，不保证未来模型输出可复现。计划包含输入快照和 SHA-256 指纹，帮助辨认两次实验是否使用相同资料；不能保证模型服务底层版本不变。

## 看看阶段加载

```powershell
.\.venv\Scripts\python.exe -m skillscope preview --condition all --stage investigate
.\.venv\Scripts\python.exe -m skillscope preview --condition scoped --stage investigate
.\.venv\Scripts\python.exe -m skillscope preview --condition scoped --stage implement
.\.venv\Scripts\python.exe -m skillscope preview --condition scoped --stage verify
```

每个阶段都新建消息，独立评分文件不加入消息。真实运行时，修改阶段只额外接收调查摘要，检查阶段只额外接收候选代码；不追加完整聊天历史。摘要和代码仍可能携带旧指南的影响，隔离效果需要后续对照实验验证。

## 跑一道真实任务

需要可用的 DeepSeek API 密钥，以及已启动的 Docker Linux 容器引擎。

```powershell
Copy-Item .env.example .env
# 在本机编辑 .env，填写 DEEPSEEK_API_KEY。
# 如果 Docker 不在 PATH，在 .env 中填写 SKILLSCOPE_DOCKER 的完整路径。
.\.venv\Scripts\python.exe -m skillscope sandbox-build
.\.venv\Scripts\python.exe -m skillscope run --task clamp --condition baseline --output results/my-baseline-001
```

已有 `.env` 时跳过复制，保留原配置。模型名称由 `examples/experiment.json` 指定，不通过环境变量偷偷覆盖。仅 `run` 调用模型；默认 3 次请求、每次最多输出 1,024 tokens、无 SDK 自动重试，固定非思考模式。这个上限不包含输入 token。

`run` 只运行指定的一道题和一个分组，不会自动执行 `plan` 的 15 次排期。数据保存在新建输出目录中，已有目录会被拒绝。`--allow-holdout` 才允许显式运行验收题。

评分时，可信 pytest 测试留在宿主机，候选代码在无网络、只读挂载、非 root、限制资源的容器中执行；每次函数调用使用新容器。测试通过 JSON 代理调用公开函数，支持本项目 6 道教学任务及其普通 JSON 位置参数，保留顶层列表/字典修改和返回值与参数的顶层身份关系；不支持任意 Python 对象、关键字参数、跨调用状态或通用代码仓库任务。评分测试是可信输入。

基础镜像固定摘要，实际运行还记录本地镜像 ID。模型返回的别名不能证明服务端权重版本固定。日志中的费用保持未知，不根据 token 数编造账单。

## 目录

```text
src/skillscope/         核心代码：数据格式、读取、排期、阶段消息、命令入口
examples/skills/       2 份教学技能指南
examples/tasks/        任务说明与带缺陷的初始代码
examples/graders/      容器外执行的可信独立评分测试
tests/                 检查 SkillScope 工具自身的测试
docs/                  中文操作步骤、路线和原始方案
requirements-dev.lock 本阶段验证过的依赖版本
.github/workflows/     Windows/Linux 自动检查
results/               本地计划、调用日志、候选代码、评分记录；Git 忽略
benchmarks/stage3/     六份人工技能、四道开发题、两道保留题与参考实现
artifacts/             经检查后公开的实验摘要与压缩原始记录
```

配置引用的文件必须在配置文件所在目录内。单函数模式只挂载候选代码文件；目录模式只挂载清单指定的源码和资源，不挂载密钥、宿主机评分文件或 Docker socket。模型不能自行改变评分规则。目录能力与首批真实任务见[逐步说明](docs/directory-and-calibration.md)，最新结果见[真实库对照报告](docs/repo-skill-findings.md)。

## 下一步

已接入 DeepSeek `deepseek-flash`，固定非思考模式。工具格式参考 [DeepSeek 官方示例](https://api-docs.deepseek.com/guides/tool_calls/)。2026-11-23 的无技能和阶段加载两次管道试运行均通过 9 项测试，仅验证运行链路。

`.env` 由本机读取并被 Git 忽略。不要将模型密钥提交到仓库。

第三阶段通过 12 组配置、每题 3 次重复观察技能影响；先做 4 次基线预检，再随机执行 144 次主实验。保留题不请求模型。使用固定高峰价格记录费用上界估算，API/环境错误保持未知；统计区间只作描述，不代表新任务总体效果。方案、评分标准和候选阈值在执行前固定。

查看计划与重新生成已有报告都不请求模型：

```powershell
.\.venv\Scripts\python.exe -m skillscope plan --config benchmarks/stage3/experiment.json --controls --output results/my-stage3-plan.json
.\.venv\Scripts\python.exe -m skillscope report results/stage3-20261123
```

真实批次命令、费用预算和续跑要求见[第三阶段教程](docs/stage3-guide.md)。后续组合缩减与策略验证需要可复查的退化候选；证据不足时如实记录负面结果。

## 开发验证

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest -q
```

默认跳过真实 Docker 测试，不调用模型。构建镜像后可另行验证容器功能：

```powershell
$env:SKILLSCOPE_TEST_DOCKER = 'docker' # 或 docker.exe 的完整路径
.\.venv\Scripts\python.exe -m pytest tests/test_sandbox_integration.py tests/test_stage3_corpus_integration.py tests/test_repo_execution.py tests/test_upstream_tasks.py -q
```

CI 在 Windows/Linux 检查工具代码，并在 Linux 运行真实 Docker 测试；CI 不配置模型密钥，不产生模型 API 费用。

SkillScope 自有代码采用 MIT License；`benchmarks/upstream` 中 python-dotenv 源码保留其 BSD-3-Clause 许可证。
