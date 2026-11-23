# SkillScope：一步步操作与作用

本阶段目标：看懂实验如何组织，并确认程序加载了正确的资料。现在相当于搭实验台，尚未请模型做题。

## 1. 进入项目目录

在 PowerShell 中执行：

```powershell
Set-Location -LiteralPath 'D:\Study\Agent Harness项目\SkillScope'
```

作用：指定接下来操作的项目位置。SkillScope 是独立仓库，旁边的 TransferGuard 不进入这个仓库。

## 2. 准备专用环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" -c requirements-dev.lock
```

作用：准备项目专用的 Python 工具箱。

- `venv` 创建专用环境，已创建时可以跳过。
- `pip install` 安装项目及其依赖。
- `-e` 采用开发模式，修改源码后不必重新安装。
- `[dev]` 同时安装测试和代码检查工具。
- `-c` 使用本阶段验证过的依赖版本。

直接使用 `.venv` 里的 Python，无需激活环境或调整 PowerShell 执行策略。

## 3. 检查材料清单

```powershell
.\.venv\Scripts\python.exe -m skillscope check
```

应看到配置有效、2 个技能、2 个任务，开发任务和验收任务各 1 个。

作用：提前发现路径错误、重复编号、阶段拼写错误和空文件，避免到调用模型时才发现问题。

打开 `examples/experiment.json`，可以把它看成材料清单：

- `skills` 指定有哪些指南、指南放在哪里、属于哪个阶段。
- `tasks` 指定题目、初始代码与独立评分文件。
- `split` 指定用于开发诊断（discovery）还是后续验收（holdout）。

输出的“输入指纹”类似材料编号。指南内容、阶段、题目、评分规则或模型配置改变，指纹也会改变。

## 4. 生成实验排期

```powershell
.\.venv\Scripts\python.exe -m skillscope plan
```

首次生成 `results/plan.json`，包含 15 次计划运行：1 道开发题 × 5 组配置 × 3 次重复。

作用：在做实验前明确“做哪道题、带哪些指南、重复几次”。当前只生成计划，没有调用模型或产生成绩。

5 组分别是不加载、仅 A、仅 B、始终加载 A+B、按阶段加载 A/B。

为什么要测单份指南？如果 A 单独就有害，A+B 变差不能直接证明是组合冲突。

为什么重复？模型可能偶然失败。3 次只是教学起点，正式结论需要更多重复和不确定性分析。

计划会打乱执行顺序。`--seed` 控制打乱过程，不是模型随机种子。

再次生成时请换一个输出文件；程序拒绝覆盖旧计划：

```powershell
.\.venv\Scripts\python.exe -m skillscope plan --repeats 5 --seed 43 --output results/plan-02.json
```

## 5. 亲眼看看阶段加载

```powershell
.\.venv\Scripts\python.exe -m skillscope preview --condition all --stage investigate
.\.venv\Scripts\python.exe -m skillscope preview --condition scoped --stage investigate
.\.venv\Scripts\python.exe -m skillscope preview --condition scoped --stage implement
.\.venv\Scripts\python.exe -m skillscope preview --condition scoped --stage verify
```

作用：直接检查准备发送给模型的消息。

- `all`：调查、修改、验收阶段始终保留两份指南。
- `scoped + investigate`：调查阶段只有根因分析指南。
- `scoped + implement`：修改阶段只有最小修复指南。
- `scoped + verify`：验收阶段没有额外技能，仍有基本工作规则。

消息中的 `system` 是工作规则，`user` 是题目和初始代码。独立评分测试不加入消息。

当前每次预览都新建消息，但没有运行中的 Agent。后续还要设计代码和必要记录怎样在阶段间传递，再检验是否真的减少旧指南的影响。

## 6. 检查工具本身

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

作用：自动检查排期是否平衡、验收题是否混入开发计划、阶段指南是否正确、旧计划是否受保护。

`tests/` 检查 SkillScope 本身；`examples/graders/` 将来判断模型修复的代码是否正确。工具测试通过不等于模型做题成功。

## 7. 理解 Git 与 GitHub

- Git 在本地记录版本，方便比较和回退。
- GitHub 保存远程副本、展示项目、运行自动检查。
- commit 是保存一份可追踪的版本快照。
- push 是把本地快照上传到 GitHub。

完成首次关联后，后续常用流程如下：

```powershell
git status
git diff
git add src tests docs README.md
git commit -m "Describe the actual change"
git push
```

只暂存本次相关文件。`.gitignore` 已排除专用环境、本地密钥和生成计划。

## 下一步

接下来接入 DeepSeek `deepseek-flash` 非思考模式，让模型真正处理一道题，再用隔离环境里的独立测试评分。

当前尚无模型客户端与评分运行器，填写 `.env` 还不能启动真实实验；`.env.example` 是后续配置约定。到接入时在本机填写密钥，不要发到聊天或提交到仓库。
