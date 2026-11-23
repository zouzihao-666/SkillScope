# SkillScope

技能组合冲突诊断与阶段加载实验工具。

准备研究的问题：**为什么给 Agent 加了更多技能，任务反而可能做得更差？**

可以把 Skill 理解为工作指南。SkillScope 希望通过相同任务、不同指南组合的重复实验，找到值得进一步验证的退化组合，并尝试按工作阶段加载指南。

**当前为第 1 阶段：实验准备工具。已实现配置校验、对照分组、实验排期、输入内容指纹和阶段指令预览。尚未接入模型、执行代码、评分或发现真实冲突。**

[中文入门：一步步操作与作用](docs/step-by-step.md) · [开发路线](docs/roadmap.md) · [原始研究设计](docs/design.md)

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

当前所有命令都不请求模型 API，也不需要密钥。`plan` 默认保存至 `results/plan.json`；如果文件已经存在，请通过 `--output results/plan-02.json` 指定新路径，保护旧计划。

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

每次预览都新建一组消息，独立评分文件不加入消息。当前没有运行中的 Agent，因此还不能证明跨阶段隔离有效。后续阶段间需要传递代码和必要记录，并检验它们是否携带旧指南的影响。

## 目录

```text
src/skillscope/         核心代码：数据格式、读取、排期、阶段消息、命令入口
examples/skills/       2 份教学技能指南
examples/tasks/        任务说明与带缺陷的初始代码
examples/graders/      独立评分测试，尚未由运行器执行
tests/                 检查 SkillScope 工具自身的测试
docs/                  中文操作步骤、路线和原始方案
requirements-dev.lock 本阶段验证过的依赖版本
.github/workflows/     Windows/Linux 自动检查
results/               本地生成计划；Git 忽略
```

配置引用的文件必须在配置文件所在目录内。评分文件与待修复文件分别存放；当前只记录评分文件指纹。真正防止 Agent 修改评分规则，需要后续隔离运行器，单靠目录分开无法保证。

## 下一步

第 2 阶段准备接入 DeepSeek `deepseek-flash`，固定非思考模式，并实现工具调用、阶段状态机、调用预算和隔离评分。模型选择参考 [DeepSeek 官方工具调用示例](https://api-docs.deepseek.com/guides/tool_calls/)，实际服务以运行时可用模型为准。

`.env.example` 只是后续配置约定，当前程序不读取 `.env`。不要将模型密钥提交到仓库。

之后再做稳定退化案例搜集、顺序及长度对照、组合缩减，以及在新任务上的策略验证。完成这些真实实验前，不能宣称已经发现技能冲突或提升了完成率。

## 开发验证

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest -q
```

MIT License。
